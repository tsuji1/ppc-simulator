#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
#   "pymongo>=4.6",
# ]
# ///
import argparse
import csv
import gzip
import os
import struct
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from bson import ObjectId
from pymongo import MongoClient


CounterRows = List[List[int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze UnifiedCache first/second miss detail counters saved in MongoDB. "
            "Stored data is aggregated by cache set and prefix length; individual IPs "
            "are not present in current result documents."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI (default: DATABASE_URL env or mongodb://localhost:27017/)",
    )
    parser.add_argument("--db", default="db", help="Database name")
    parser.add_argument("--collection", default="simulator_results", help="Collection name")
    parser.add_argument("--rule-file-name", default=None, help="Optional rule_file_name filter")
    parser.add_argument("--trace-file-name", default=None, help="Optional trace_file_name filter")
    parser.add_argument("--processed", type=int, default=None, help="Optional processed packet count filter")
    parser.add_argument("--way", type=int, default=None, help="Optional UnifiedCache way filter")
    parser.add_argument(
        "--cache-index-type",
        type=int,
        default=None,
        help="Optional UnifiedCache cacheindextype filter",
    )
    parser.add_argument(
        "--insertion-policy",
        choices=("exclusive", "inclusive"),
        default=None,
        help="Optional UnifiedCache insertionpolicy filter",
    )
    parser.add_argument("--start-exp", type=int, default=6, help="Start exponent, inclusive")
    parser.add_argument("--end-exp", type=int, default=14, help="End exponent, inclusive")
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        help="Number of second-miss set/prefix hotspots to write",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/unified_miss_details",
        help="Directory for CSV and Markdown reports",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="MongoDB server selection timeout in milliseconds",
    )
    return parser.parse_args()


def expected_capacities(start_exp: int, end_exp: int) -> List[int]:
    if start_exp > end_exp:
        raise ValueError("--start-exp must be less than or equal to --end-exp")
    return [1 << exp for exp in range(start_exp, end_exp + 1)]


def build_query(args: argparse.Namespace, capacities: List[int]) -> Dict[str, object]:
    query: Dict[str, object] = {
        "simulator_result.type": "UnifiedCache",
        "simulator_result.parameter.size": {"$in": capacities},
    }
    if args.rule_file_name:
        query["rule_file_name"] = args.rule_file_name
    if args.trace_file_name:
        query["trace_file_name"] = args.trace_file_name
    if args.processed is not None:
        query["simulator_result.processed"] = args.processed
    if args.way is not None:
        query["simulator_result.parameter.way"] = args.way
    if args.cache_index_type is not None:
        query["simulator_result.parameter.cacheindextype"] = args.cache_index_type
    if args.insertion_policy is not None:
        query["simulator_result.parameter.insertionpolicy"] = args.insertion_policy
    return query


def nested_get(doc: Dict[str, object], path: Iterable[str]) -> object:
    cur: object = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def decode_compressed_counter_rows(blob: object, rows: Optional[int], field_name: str) -> CounterRows:
    if blob is None:
        return []

    raw = gzip.decompress(bytes(blob))
    if len(raw) % 4 != 0:
        raise ValueError(f"{field_name} decompressed byte length is not divisible by 4")
    values = [value for (value,) in struct.iter_unpack("<I", raw)]
    if len(values) % 32 != 0:
        raise ValueError(f"{field_name} value count is not divisible by 32")

    decoded_rows = len(values) // 32
    if rows is not None and decoded_rows != rows:
        raise ValueError(f"{field_name} has {decoded_rows} rows; expected unified_stat_rows={rows}")

    return [values[i * 32 : (i + 1) * 32] for i in range(decoded_rows)]


def decode_legacy_counter_rows(rows: object) -> CounterRows:
    if not rows:
        return []
    return [[int(value) for value in row] for row in rows]


def counter_rows_from_doc(doc: Dict[str, object]) -> Tuple[CounterRows, CounterRows, CounterRows]:
    row_count = doc.get("unified_stat_rows")
    rows = int(row_count) if row_count is not None else None

    hit_blob = doc.get("hit_count_list_compressed")
    first_blob = doc.get("first_miss_count_compressed")
    second_blob = doc.get("second_miss_count_compressed")
    if hit_blob is not None or first_blob is not None or second_blob is not None:
        hit = decode_compressed_counter_rows(hit_blob, rows, "hit_count_list_compressed")
        first = decode_compressed_counter_rows(first_blob, rows, "first_miss_count_compressed")
        second = decode_compressed_counter_rows(second_blob, rows, "second_miss_count_compressed")
        return hit, first, second

    statdetail = nested_get(doc, ("simulator_result", "statdetail"))
    hit_rows = None
    first_rows = None
    second_rows = None
    if isinstance(statdetail, dict):
        hit_rows = statdetail.get("cachelinehitcount") or statdetail.get("CachelineHitCount")
        first_rows = statdetail.get("cachelinefirstmisscount") or statdetail.get("CachelineFirstMissCount")
        second_rows = statdetail.get("cachelinesecondmisscount") or statdetail.get("CachelineSecondMissCount")
    return (
        decode_legacy_counter_rows(hit_rows),
        decode_legacy_counter_rows(first_rows),
        decode_legacy_counter_rows(second_rows),
    )


def row_prefix_sum(rows: CounterRows, prefix_len: int) -> int:
    return sum(row[prefix_len] for row in rows if prefix_len < len(row))


def counter_total(rows: CounterRows) -> int:
    return sum(sum(row) for row in rows)


def counter_line_total(rows: CounterRows, set_idx: int) -> int:
    if set_idx >= len(rows):
        return 0
    return sum(rows[set_idx])


def max_row_count(*row_groups: CounterRows) -> int:
    return max((len(rows) for rows in row_groups), default=0)


def nonzero_prefix_count(rows: CounterRows, set_idx: int) -> int:
    if set_idx >= len(rows):
        return 0
    return sum(1 for value in rows[set_idx] if value)


def dominant_prefix(rows: CounterRows, set_idx: int) -> Tuple[str, int]:
    if set_idx >= len(rows) or not rows[set_idx]:
        return "", 0
    prefix_len, value = max(enumerate(rows[set_idx]), key=lambda item: item[1])
    if not value:
        return "", 0
    return str(prefix_len), int(value)


def percent(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator * 100.0) if denominator else 0.0:.6f}"


def percentile(values: List[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def gini(values: List[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    total = sum(ordered)
    if total == 0:
        return 0.0
    weighted_sum = sum((idx + 1) * value for idx, value in enumerate(ordered))
    count = len(ordered)
    return (2.0 * weighted_sum) / (count * total) - (count + 1.0) / count


def configure_capacity_axis(ax, rows: List[Dict[str, object]]) -> None:
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([f"2^{int(row['capacity_exp'])}" for row in rows], rotation=0)


def plot_cacheline_unused_ratio(rows: List[Dict[str, object]], output_path: str) -> None:
    plottable = [row for row in rows if int(row["doc_count"]) > 0 and int(row["total_cachelines"]) > 0]
    if not plottable:
        return

    active = [float(row["active_cacheline_ratio_percent"]) for row in plottable]
    unused = [float(row["unused_cacheline_ratio_percent"]) for row in plottable]
    x = list(range(len(plottable)))

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.bar(x, active, color="#2563eb", label="Active set")
    ax.bar(x, unused, bottom=active, color="#cbd5e1", label="Unused set")
    configure_capacity_axis(ax, plottable)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Cache capacity")
    ax.set_ylabel("Share of cache sets (%)")
    ax.set_title("UnifiedCache Active/Unused Cache Sets")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def plot_cacheline_miss_skew(rows: List[Dict[str, object]], output_path: str) -> None:
    plottable = [row for row in rows if int(row["doc_count"]) > 0 and int(row["total_miss"]) > 0]
    if not plottable:
        return

    x = list(range(len(plottable)))
    p50 = [float(row["p50_cacheline_total_miss"]) + 1.0 for row in plottable]
    p90 = [float(row["p90_cacheline_total_miss"]) + 1.0 for row in plottable]
    p99 = [float(row["p99_cacheline_total_miss"]) + 1.0 for row in plottable]
    max_values = [float(row["max_cacheline_total_miss"]) + 1.0 for row in plottable]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(x, p50, color="#475569", marker="o", linewidth=2.0, label="p50 + 1")
    ax.plot(x, p90, color="#2563eb", marker="s", linewidth=2.0, label="p90 + 1")
    ax.plot(x, p99, color="#f59e0b", marker="^", linewidth=2.0, label="p99 + 1")
    ax.plot(x, max_values, color="#dc2626", marker="D", linewidth=2.0, label="max + 1")
    configure_capacity_axis(ax, plottable)
    ax.set_yscale("log")
    ax.set_xlabel("Cache capacity")
    ax.set_ylabel("Total miss per set (log scale)")
    ax.set_title("UnifiedCache Cache-Set Miss Skew")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def plot_cacheline_miss_distribution(rows: List[Dict[str, object]], output_path: str) -> None:
    by_capacity: Dict[int, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        if int(row["doc_count"]) > 0:
            by_capacity[int(row["capacity"])].append(row)
    capacities = sorted(by_capacity)
    if not capacities:
        return

    fig, axes = plt.subplots(len(capacities), 1, figsize=(13, max(7, 1.8 * len(capacities))), squeeze=False)
    for ax, capacity in zip(axes[:, 0], capacities):
        capacity_rows = sorted(by_capacity[capacity], key=lambda row: int(row["set_idx"]))
        x = [int(row["set_idx"]) for row in capacity_rows]
        first = [int(row["first_miss"]) + 1 for row in capacity_rows]
        second = [int(row["second_miss"]) + 1 for row in capacity_rows]
        exp = capacity.bit_length() - 1
        unused = sum(1 for row in capacity_rows if int(row["total_activity"]) == 0)

        ax.plot(x, first, color="#2563eb", linewidth=0.9, label="first miss + 1")
        ax.plot(x, second, color="#dc2626", linewidth=0.9, label="second miss + 1")
        ax.set_yscale("log")
        ax.set_ylabel(f"2^{exp}")
        ax.grid(True, alpha=0.25)
        ax.set_title(f"capacity=2^{exp}, sets={len(capacity_rows)}, unused={unused}", loc="left", fontsize=9)
        if x:
            ax.set_xlim(min(x), max(x))
    axes[0, 0].legend(loc="upper right")
    axes[-1, 0].set_xlabel("set_idx")
    fig.suptitle("UnifiedCache First/Second Miss by Cache Set", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def plot_prefix_hit_distribution(rows: List[Dict[str, object]], output_path: str) -> None:
    by_capacity: Dict[int, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        if int(row["doc_count"]) > 0:
            by_capacity[int(row["capacity"])].append(row)
    capacities = sorted(by_capacity)
    if not capacities:
        return

    fig, axes = plt.subplots(len(capacities), 1, figsize=(12, max(5.5, 2.5 * len(capacities))), squeeze=False)
    for ax, capacity in zip(axes[:, 0], capacities):
        capacity_rows = sorted(by_capacity[capacity], key=lambda row: int(row["prefix_len"]))
        prefix_lens = [int(row["prefix_len"]) for row in capacity_rows]
        hit_shares = [float(row["hit_share_percent"]) for row in capacity_rows]
        exp = capacity.bit_length() - 1

        ax.bar(prefix_lens, hit_shares, color="#2563eb", width=0.72)
        ax.set_ylabel(f"2^{exp}\nHit share (%)")
        ax.set_ylim(0, max(hit_shares) * 1.18 if hit_shares else 1)
        ax.set_xticks(prefix_lens)
        ax.grid(axis="y", alpha=0.3)
        ax.set_title(f"capacity=2^{exp}: cumulative cache hits by hit prefix length", loc="left", fontsize=10)
    axes[-1, 0].set_xlabel("Prefix length of hit cache entry")
    fig.tight_layout()
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def object_id_to_str(value: object) -> str:
    if isinstance(value, ObjectId):
        return str(value)
    return str(value) if value is not None else ""


def timestamp_to_str(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else ""


def cache_tag_length_to_str(value: object) -> str:
    if not value:
        return ""
    try:
        return ",".join(f"{int(pair[0])}-{int(pair[1])}" for pair in value)
    except (TypeError, ValueError, IndexError):
        return str(value)


def sum_counter_vector(values: object) -> int:
    if values is None:
        return 0
    if isinstance(values, dict):
        iterable = values.values()
    else:
        iterable = values
    return sum(int(value) for value in iterable)


def write_csv(path: str, fieldnames: List[str], rows: List[Dict[str, object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: List[Dict[str, object]], columns: List[str], max_rows: int = 20) -> str:
    if not rows:
        return "No rows.\n"
    lines = []
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    if len(rows) > max_rows:
        lines.append(f"\nShowing {max_rows} of {len(rows)} rows.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    try:
        capacities = expected_capacities(args.start_exp, args.end_exp)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2

    os.makedirs(args.output_dir, exist_ok=True)

    projection = {
        "_id": 1,
        "timestamp": 1,
        "rule_file_name": 1,
        "trace_file_name": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter.size": 1,
        "simulator_result.parameter.way": 1,
        "simulator_result.parameter.cacheindextype": 1,
        "simulator_result.parameter.cachetaglength": 1,
        "simulator_result.parameter.insertionpolicy": 1,
        "simulator_result.statdetail.cachelinehitcount": 1,
        "simulator_result.statdetail.cachelinefirstmisscount": 1,
        "simulator_result.statdetail.cachelinesecondmisscount": 1,
        "simulator_result.statdetail.CachelineHitCount": 1,
        "simulator_result.statdetail.CachelineFirstMissCount": 1,
        "simulator_result.statdetail.CachelineSecondMissCount": 1,
        "simulator_result.statdetail.exclusiverejectedfirstmisscount": 1,
        "simulator_result.statdetail.exclusiverejectedsecondmisscount": 1,
        "simulator_result.statdetail.inclusivenonleafinsertedcount": 1,
        "simulator_result.statdetail.ExclusiveRejectedFirstMissCount": 1,
        "simulator_result.statdetail.ExclusiveRejectedSecondMissCount": 1,
        "simulator_result.statdetail.InclusiveNonLeafInsertedCount": 1,
        "unified_stat_encoding": 1,
        "unified_stat_rows": 1,
        "hit_count_list_compressed": 1,
        "first_miss_count_compressed": 1,
        "second_miss_count_compressed": 1,
    }

    query = build_query(args, capacities)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    docs: List[Dict[str, object]] = []
    try:
        collection = client[args.db][args.collection]
        docs = list(collection.find(query, projection).sort("simulator_result.parameter.size", 1))
    finally:
        client.close()

    if not docs:
        print("No UnifiedCache documents found for the selected filters.", file=sys.stderr)
        return 1

    prefix_totals: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(
        lambda: {"hit_count": 0, "first_miss": 0, "second_miss": 0, "doc_count": 0}
    )
    hotspot_totals: Dict[Tuple[int, int, int], int] = defaultdict(int)
    cacheline_totals: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(
        lambda: {
            "hit_count": 0,
            "first_miss": 0,
            "second_miss": 0,
            "doc_count": 0,
            "active_doc_count": 0,
            "miss_active_doc_count": 0,
            "first_prefix_count": 0,
            "second_prefix_count": 0,
        }
    )
    capacity_usage: Dict[int, Dict[str, int]] = defaultdict(
        lambda: {
            "doc_count": 0,
            "total_cachelines": 0,
            "active_cachelines": 0,
            "unused_cachelines": 0,
            "no_miss_cachelines": 0,
            "first_only_miss_cachelines": 0,
            "second_only_miss_cachelines": 0,
            "both_miss_cachelines": 0,
            "hit_count": 0,
            "first_miss": 0,
            "second_miss": 0,
        }
    )
    doc_rows: List[Dict[str, object]] = []

    for doc in docs:
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {}) if isinstance(sim, dict) else {}
        capacity = int(param.get("size"))
        way = param.get("way", "")
        cache_index_type = param.get("cacheindextype", "")
        insertion_policy = param.get("insertionpolicy", "exclusive")
        processed = sim.get("processed", "") if isinstance(sim, dict) else ""
        statdetail = sim.get("statdetail", {}) if isinstance(sim, dict) else {}
        if not isinstance(statdetail, dict):
            statdetail = {}
        exclusive_rejected_first = sum_counter_vector(
            statdetail.get("exclusiverejectedfirstmisscount")
            or statdetail.get("ExclusiveRejectedFirstMissCount")
        )
        exclusive_rejected_second = sum_counter_vector(
            statdetail.get("exclusiverejectedsecondmisscount")
            or statdetail.get("ExclusiveRejectedSecondMissCount")
        )
        inclusive_non_leaf_inserted = sum_counter_vector(
            statdetail.get("inclusivenonleafinsertedcount")
            or statdetail.get("InclusiveNonLeafInsertedCount")
        )
        hit_rows, first_rows, second_rows = counter_rows_from_doc(doc)
        row_count = max_row_count(hit_rows, first_rows, second_rows)
        hit_total = counter_total(hit_rows)
        first_total = counter_total(first_rows)
        second_total = counter_total(second_rows)
        total_miss_values: List[int] = []
        active_cachelines = 0
        unused_cachelines = 0
        no_miss_cachelines = 0
        first_only_miss_cachelines = 0
        second_only_miss_cachelines = 0
        both_miss_cachelines = 0
        max_total_miss = 0
        max_total_miss_set_idx = ""
        max_second_miss = 0
        max_second_miss_set_idx = ""

        for set_idx in range(row_count):
            line_hit = counter_line_total(hit_rows, set_idx)
            line_first = counter_line_total(first_rows, set_idx)
            line_second = counter_line_total(second_rows, set_idx)
            line_total_miss = line_first + line_second
            line_total_activity = line_hit + line_total_miss
            total_miss_values.append(line_total_miss)

            if line_total_activity:
                active_cachelines += 1
            else:
                unused_cachelines += 1
            if not line_total_miss:
                no_miss_cachelines += 1
            elif line_first and line_second:
                both_miss_cachelines += 1
            elif line_first:
                first_only_miss_cachelines += 1
            elif line_second:
                second_only_miss_cachelines += 1

            if line_total_miss > max_total_miss:
                max_total_miss = line_total_miss
                max_total_miss_set_idx = str(set_idx)
            if line_second > max_second_miss:
                max_second_miss = line_second
                max_second_miss_set_idx = str(set_idx)

            cacheline_key = (capacity, set_idx)
            cacheline_totals[cacheline_key]["hit_count"] += line_hit
            cacheline_totals[cacheline_key]["first_miss"] += line_first
            cacheline_totals[cacheline_key]["second_miss"] += line_second
            cacheline_totals[cacheline_key]["doc_count"] += 1
            if line_total_activity:
                cacheline_totals[cacheline_key]["active_doc_count"] += 1
            if line_total_miss:
                cacheline_totals[cacheline_key]["miss_active_doc_count"] += 1
            cacheline_totals[cacheline_key]["first_prefix_count"] += nonzero_prefix_count(first_rows, set_idx)
            cacheline_totals[cacheline_key]["second_prefix_count"] += nonzero_prefix_count(second_rows, set_idx)

        capacity_usage[capacity]["doc_count"] += 1
        capacity_usage[capacity]["total_cachelines"] += row_count
        capacity_usage[capacity]["active_cachelines"] += active_cachelines
        capacity_usage[capacity]["unused_cachelines"] += unused_cachelines
        capacity_usage[capacity]["no_miss_cachelines"] += no_miss_cachelines
        capacity_usage[capacity]["first_only_miss_cachelines"] += first_only_miss_cachelines
        capacity_usage[capacity]["second_only_miss_cachelines"] += second_only_miss_cachelines
        capacity_usage[capacity]["both_miss_cachelines"] += both_miss_cachelines
        capacity_usage[capacity]["hit_count"] += hit_total
        capacity_usage[capacity]["first_miss"] += first_total
        capacity_usage[capacity]["second_miss"] += second_total

        doc_rows.append(
            {
                "document_id": object_id_to_str(doc.get("_id")),
                "timestamp": timestamp_to_str(doc.get("timestamp")),
                "capacity_exp": capacity.bit_length() - 1,
                "capacity": capacity,
                "way": way,
                "cache_index_type": cache_index_type,
                "insertion_policy": insertion_policy,
                "cache_tag_length": cache_tag_length_to_str(param.get("cachetaglength")),
                "processed": processed,
                "rule_file_name": doc.get("rule_file_name", ""),
                "trace_file_name": doc.get("trace_file_name", ""),
                "stat_rows": row_count,
                "hit_count": hit_total,
                "first_miss": first_total,
                "second_miss": second_total,
                "total_miss": first_total + second_total,
                "exclusive_rejected_first": exclusive_rejected_first,
                "exclusive_rejected_second": exclusive_rejected_second,
                "exclusive_rejected_total": exclusive_rejected_first + exclusive_rejected_second,
                "inclusive_non_leaf_inserted": inclusive_non_leaf_inserted,
                "active_cachelines": active_cachelines,
                "unused_cachelines": unused_cachelines,
                "no_miss_cachelines": no_miss_cachelines,
                "active_cacheline_ratio_percent": percent(active_cachelines, row_count),
                "unused_cacheline_ratio_percent": percent(unused_cachelines, row_count),
                "no_miss_cacheline_ratio_percent": percent(no_miss_cachelines, row_count),
                "max_cacheline_total_miss": max_total_miss,
                "max_cacheline_total_miss_set_idx": max_total_miss_set_idx,
                "max_cacheline_second_miss": max_second_miss,
                "max_cacheline_second_miss_set_idx": max_second_miss_set_idx,
                "gini_cacheline_total_miss": f"{gini(total_miss_values):.6f}",
            }
        )

        for prefix_len in range(32):
            hit = row_prefix_sum(hit_rows, prefix_len)
            first = row_prefix_sum(first_rows, prefix_len)
            second = row_prefix_sum(second_rows, prefix_len)
            if hit == 0 and first == 0 and second == 0:
                continue
            key = (capacity, prefix_len)
            prefix_totals[key]["hit_count"] += hit
            prefix_totals[key]["first_miss"] += first
            prefix_totals[key]["second_miss"] += second
            prefix_totals[key]["doc_count"] += 1

        for set_idx, row in enumerate(second_rows):
            for prefix_len, value in enumerate(row):
                if value:
                    hotspot_totals[(capacity, set_idx, prefix_len)] += int(value)

    prefix_rows: List[Dict[str, object]] = []
    capacity_hit_totals: Dict[int, int] = defaultdict(int)
    for (capacity, _prefix_len), values in prefix_totals.items():
        capacity_hit_totals[capacity] += values["hit_count"]
    for (capacity, prefix_len), values in sorted(prefix_totals.items()):
        hit = values["hit_count"]
        first = values["first_miss"]
        second = values["second_miss"]
        total = first + second
        total_activity = hit + total
        prefix_rows.append(
            {
                "capacity_exp": capacity.bit_length() - 1,
                "capacity": capacity,
                "prefix_len": prefix_len,
                "hit_count": hit,
                "first_miss": first,
                "second_miss": second,
                "total_miss": total,
                "total_activity": total_activity,
                "hit_share_percent": f"{(hit / capacity_hit_totals[capacity] * 100.0) if capacity_hit_totals[capacity] else 0.0:.6f}",
                "hit_ratio_percent": f"{(hit / total_activity * 100.0) if total_activity else 0.0:.6f}",
                "first_miss_ratio_percent": f"{(first / total * 100.0) if total else 0.0:.6f}",
                "second_miss_ratio_percent": f"{(second / total * 100.0) if total else 0.0:.6f}",
                "doc_count": values["doc_count"],
            }
        )

    hit_prefix_rows = [row for row in prefix_rows if int(row["hit_count"]) > 0]
    hit_prefix_rows.sort(key=lambda row: (-int(row["hit_count"]), int(row["capacity"]), int(row["prefix_len"])))
    first_prefix_rows = [row for row in prefix_rows if int(row["first_miss"]) > 0]
    first_prefix_rows.sort(key=lambda row: (-int(row["first_miss"]), int(row["capacity"]), int(row["prefix_len"])))
    second_prefix_rows = [row for row in prefix_rows if int(row["second_miss"]) > 0]
    second_prefix_rows.sort(key=lambda row: (-int(row["second_miss"]), int(row["capacity"]), int(row["prefix_len"])))

    dominant_second_prefix: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for (capacity, set_idx, prefix_len), value in hotspot_totals.items():
        key = (capacity, set_idx)
        current = dominant_second_prefix.get(key)
        if current is None or value > current[1]:
            dominant_second_prefix[key] = (prefix_len, value)

    capacity_total_miss: Dict[int, int] = defaultdict(int)
    capacity_total_activity: Dict[int, int] = defaultdict(int)
    for (capacity, _set_idx), values in cacheline_totals.items():
        total_miss = values["first_miss"] + values["second_miss"]
        total_activity = values["hit_count"] + total_miss
        capacity_total_miss[capacity] += total_miss
        capacity_total_activity[capacity] += total_activity

    cacheline_rows: List[Dict[str, object]] = []
    miss_values_by_capacity: Dict[int, List[int]] = defaultdict(list)
    for (capacity, set_idx), values in sorted(cacheline_totals.items()):
        first = values["first_miss"]
        second = values["second_miss"]
        total_miss = first + second
        total_activity = values["hit_count"] + total_miss
        dominant = dominant_second_prefix.get((capacity, set_idx), ("", 0))
        miss_values_by_capacity[capacity].append(total_miss)
        cacheline_rows.append(
            {
                "capacity_exp": capacity.bit_length() - 1,
                "capacity": capacity,
                "set_idx": set_idx,
                "hit_count": values["hit_count"],
                "first_miss": first,
                "second_miss": second,
                "total_miss": total_miss,
                "total_activity": total_activity,
                "first_miss_ratio_percent": percent(first, total_miss),
                "second_miss_ratio_percent": percent(second, total_miss),
                "miss_share_percent": percent(total_miss, capacity_total_miss[capacity]),
                "activity_share_percent": percent(total_activity, capacity_total_activity[capacity]),
                "doc_count": values["doc_count"],
                "active_doc_count": values["active_doc_count"],
                "miss_active_doc_count": values["miss_active_doc_count"],
                "first_prefix_count": values["first_prefix_count"],
                "second_prefix_count": values["second_prefix_count"],
                "dominant_second_prefix_len": dominant[0],
                "dominant_second_prefix_miss": dominant[1],
            }
        )

    top_cacheline_rows = [
        row for row in cacheline_rows if int(row["first_miss"]) > 0 or int(row["second_miss"]) > 0
    ]
    top_cacheline_rows.sort(
        key=lambda row: (
            -int(row["second_miss"]),
            -int(row["first_miss"]),
            int(row["capacity"]),
            int(row["set_idx"]),
        )
    )

    cacheline_usage_rows: List[Dict[str, object]] = []
    for capacity in capacities:
        values = capacity_usage[capacity]
        doc_count = values["doc_count"]
        total_cachelines = values["total_cachelines"]
        total_miss = values["first_miss"] + values["second_miss"]
        line_miss_values = miss_values_by_capacity.get(capacity, [])
        cacheline_usage_rows.append(
            {
                "capacity_exp": capacity.bit_length() - 1,
                "capacity": capacity,
                "doc_count": doc_count,
                "total_cachelines": total_cachelines,
                "avg_cachelines_per_doc": f"{(total_cachelines / doc_count) if doc_count else 0.0:.2f}",
                "active_cachelines": values["active_cachelines"],
                "unused_cachelines": values["unused_cachelines"],
                "no_miss_cachelines": values["no_miss_cachelines"],
                "active_cacheline_ratio_percent": percent(values["active_cachelines"], total_cachelines),
                "unused_cacheline_ratio_percent": percent(values["unused_cachelines"], total_cachelines),
                "no_miss_cacheline_ratio_percent": percent(values["no_miss_cachelines"], total_cachelines),
                "first_only_miss_cachelines": values["first_only_miss_cachelines"],
                "second_only_miss_cachelines": values["second_only_miss_cachelines"],
                "both_miss_cachelines": values["both_miss_cachelines"],
                "hit_count": values["hit_count"],
                "first_miss": values["first_miss"],
                "second_miss": values["second_miss"],
                "total_miss": total_miss,
                "second_miss_ratio_percent": percent(values["second_miss"], total_miss),
                "p50_cacheline_total_miss": f"{percentile(line_miss_values, 0.50):.2f}",
                "p90_cacheline_total_miss": f"{percentile(line_miss_values, 0.90):.2f}",
                "p99_cacheline_total_miss": f"{percentile(line_miss_values, 0.99):.2f}",
                "max_cacheline_total_miss": max(line_miss_values) if line_miss_values else 0,
                "gini_cacheline_total_miss": f"{gini(line_miss_values):.6f}",
            }
        )

    hotspot_rows = [
        {
            "capacity_exp": capacity.bit_length() - 1,
            "capacity": capacity,
            "set_idx": set_idx,
            "prefix_len": prefix_len,
            "second_miss": value,
        }
        for (capacity, set_idx, prefix_len), value in hotspot_totals.items()
    ]
    hotspot_rows.sort(key=lambda row: (-int(row["second_miss"]), int(row["capacity"]), int(row["set_idx"])))
    hotspot_rows = hotspot_rows[: args.top_n]

    doc_rows.sort(key=lambda row: (-int(row["second_miss"]), int(row["capacity"])))

    prefix_csv = os.path.join(args.output_dir, "unified_miss_by_prefix.csv")
    hit_csv = os.path.join(args.output_dir, "unified_hit_by_prefix.csv")
    first_csv = os.path.join(args.output_dir, "unified_first_miss_by_prefix.csv")
    second_csv = os.path.join(args.output_dir, "unified_second_miss_by_prefix.csv")
    hotspot_csv = os.path.join(args.output_dir, "unified_second_miss_hotspots.csv")
    doc_csv = os.path.join(args.output_dir, "unified_doc_summary.csv")
    cacheline_csv = os.path.join(args.output_dir, "unified_cacheline_by_set.csv")
    cacheline_usage_csv = os.path.join(args.output_dir, "unified_cacheline_usage_summary.csv")
    unused_graph = os.path.join(args.output_dir, "unified_cacheline_unused_ratio.png")
    distribution_graph = os.path.join(args.output_dir, "unified_cacheline_miss_distribution.png")
    skew_graph = os.path.join(args.output_dir, "unified_cacheline_miss_skew.png")
    prefix_hit_graph = os.path.join(args.output_dir, "unified_hit_by_prefix.png")
    report_md = os.path.join(args.output_dir, "unified_miss_detail_report.md")
    ip_md = os.path.join(args.output_dir, "second_miss_ip_investigation.md")

    prefix_fields = [
        "capacity_exp",
        "capacity",
        "prefix_len",
        "hit_count",
        "first_miss",
        "second_miss",
        "total_miss",
        "total_activity",
        "hit_share_percent",
        "hit_ratio_percent",
        "first_miss_ratio_percent",
        "second_miss_ratio_percent",
        "doc_count",
    ]
    doc_fields = [
        "document_id",
        "timestamp",
        "capacity_exp",
        "capacity",
        "way",
        "cache_index_type",
        "insertion_policy",
        "cache_tag_length",
        "processed",
        "rule_file_name",
        "trace_file_name",
        "stat_rows",
        "hit_count",
        "first_miss",
        "second_miss",
        "total_miss",
        "exclusive_rejected_first",
        "exclusive_rejected_second",
        "exclusive_rejected_total",
        "inclusive_non_leaf_inserted",
        "active_cachelines",
        "unused_cachelines",
        "no_miss_cachelines",
        "active_cacheline_ratio_percent",
        "unused_cacheline_ratio_percent",
        "no_miss_cacheline_ratio_percent",
        "max_cacheline_total_miss",
        "max_cacheline_total_miss_set_idx",
        "max_cacheline_second_miss",
        "max_cacheline_second_miss_set_idx",
        "gini_cacheline_total_miss",
    ]
    hotspot_fields = ["capacity_exp", "capacity", "set_idx", "prefix_len", "second_miss"]
    cacheline_fields = [
        "capacity_exp",
        "capacity",
        "set_idx",
        "hit_count",
        "first_miss",
        "second_miss",
        "total_miss",
        "total_activity",
        "first_miss_ratio_percent",
        "second_miss_ratio_percent",
        "miss_share_percent",
        "activity_share_percent",
        "doc_count",
        "active_doc_count",
        "miss_active_doc_count",
        "first_prefix_count",
        "second_prefix_count",
        "dominant_second_prefix_len",
        "dominant_second_prefix_miss",
    ]
    cacheline_usage_fields = [
        "capacity_exp",
        "capacity",
        "doc_count",
        "total_cachelines",
        "avg_cachelines_per_doc",
        "active_cachelines",
        "unused_cachelines",
        "no_miss_cachelines",
        "active_cacheline_ratio_percent",
        "unused_cacheline_ratio_percent",
        "no_miss_cacheline_ratio_percent",
        "first_only_miss_cachelines",
        "second_only_miss_cachelines",
        "both_miss_cachelines",
        "hit_count",
        "first_miss",
        "second_miss",
        "total_miss",
        "second_miss_ratio_percent",
        "p50_cacheline_total_miss",
        "p90_cacheline_total_miss",
        "p99_cacheline_total_miss",
        "max_cacheline_total_miss",
        "gini_cacheline_total_miss",
    ]

    write_csv(prefix_csv, prefix_fields, prefix_rows)
    write_csv(hit_csv, prefix_fields, hit_prefix_rows)
    write_csv(first_csv, prefix_fields, first_prefix_rows)
    write_csv(second_csv, prefix_fields, second_prefix_rows)
    write_csv(hotspot_csv, hotspot_fields, hotspot_rows)
    write_csv(doc_csv, doc_fields, doc_rows)
    write_csv(cacheline_csv, cacheline_fields, cacheline_rows)
    write_csv(cacheline_usage_csv, cacheline_usage_fields, cacheline_usage_rows)
    plot_cacheline_unused_ratio(cacheline_usage_rows, unused_graph)
    plot_cacheline_miss_distribution(cacheline_rows, distribution_graph)
    plot_cacheline_miss_skew(cacheline_usage_rows, skew_graph)
    plot_prefix_hit_distribution(hit_prefix_rows, prefix_hit_graph)

    total_first = sum(int(row["first_miss"]) for row in doc_rows)
    total_second = sum(int(row["second_miss"]) for row in doc_rows)
    total_miss = total_first + total_second
    total_exclusive_rejected_first = sum(int(row["exclusive_rejected_first"]) for row in doc_rows)
    total_exclusive_rejected_second = sum(int(row["exclusive_rejected_second"]) for row in doc_rows)
    total_inclusive_non_leaf_inserted = sum(int(row["inclusive_non_leaf_inserted"]) for row in doc_rows)
    filters = {
        "capacity_range": f"2^{args.start_exp}..2^{args.end_exp}",
        "rule_file_name": args.rule_file_name or "(not filtered)",
        "trace_file_name": args.trace_file_name or "(not filtered)",
        "processed": args.processed if args.processed is not None else "(not filtered)",
        "way": args.way if args.way is not None else "(not filtered)",
        "cache_index_type": args.cache_index_type if args.cache_index_type is not None else "(not filtered)",
        "insertion_policy": args.insertion_policy or "(not filtered)",
    }

    with open(report_md, "w", encoding="utf-8") as f:
        f.write("# UnifiedCache miss detail report\n\n")
        f.write("## Scope\n\n")
        for key, value in filters.items():
            f.write(f"- {key}: {value}\n")
        f.write(f"- documents: {len(doc_rows)}\n")
        f.write(f"- total_first_miss: {total_first}\n")
        f.write(f"- total_second_miss: {total_second}\n")
        f.write(f"- total_exclusive_rejected_first: {total_exclusive_rejected_first}\n")
        f.write(f"- total_exclusive_rejected_second: {total_exclusive_rejected_second}\n")
        f.write(f"- total_inclusive_non_leaf_inserted: {total_inclusive_non_leaf_inserted}\n")
        f.write(f"- second_miss_ratio: {(total_second / total_miss * 100.0) if total_miss else 0.0:.6f}%\n\n")

        f.write("## Important limitation\n\n")
        f.write(
            "Current MongoDB result documents do not contain per-IP miss records. "
            "For UnifiedCache, stored detail counters are aggregated as "
            "`cache set x prefix length` arrays in `first_miss_count_compressed` and "
            "`second_miss_count_compressed`. Each row is one `UnifiedCacheLine` set, "
            "not an individual way slot. Therefore, this report can identify "
            "prefix-length and set hot spots, but cannot list the exact IP addresses "
            "that caused second misses from existing DB data alone.\n\n"
        )
        f.write(
            "`exclusive_rejected_second` counts repeated miss attempts for prefixes that "
            "the exclusive leaf-only insertion gate refused to insert. It is an upper-bound "
            "signal for misses that inclusive insertion could remove; the actual hit-rate "
            "effect must be checked by running `--cache-insertion-policy inclusive`.\n\n"
        )

        f.write("## Cacheline usage summary\n\n")
        f.write(
            markdown_table(
                cacheline_usage_rows,
                [
                    "capacity_exp",
                    "capacity",
                    "doc_count",
                    "total_cachelines",
                    "active_cachelines",
                    "unused_cachelines",
                    "unused_cacheline_ratio_percent",
                    "second_miss",
                    "max_cacheline_total_miss",
                    "gini_cacheline_total_miss",
                ],
            )
        )
        f.write("\n## Top cacheline/set miss hot spots\n\n")
        f.write(
            markdown_table(
                top_cacheline_rows,
                [
                    "capacity_exp",
                    "capacity",
                    "set_idx",
                    "first_miss",
                    "second_miss",
                    "total_miss",
                    "miss_share_percent",
                    "dominant_second_prefix_len",
                    "dominant_second_prefix_miss",
                ],
            )
        )
        f.write("\n## Generated graphs\n\n")
        for path in (unused_graph, distribution_graph, skew_graph, prefix_hit_graph):
            f.write(f"- {os.path.basename(path)}\n")
        f.write("\n")

        f.write("## Top prefix-hit lengths\n\n")
        f.write(
            markdown_table(
                hit_prefix_rows,
                [
                    "capacity_exp",
                    "capacity",
                    "prefix_len",
                    "hit_count",
                    "hit_share_percent",
                    "hit_ratio_percent",
                    "doc_count",
                ],
            )
        )
        f.write("\n")
        f.write("## Top first-miss prefix lengths\n\n")
        f.write(markdown_table(first_prefix_rows, ["capacity_exp", "capacity", "prefix_len", "first_miss", "doc_count"]))
        f.write("\n## Top second-miss prefix lengths\n\n")
        f.write(markdown_table(second_prefix_rows, ["capacity_exp", "capacity", "prefix_len", "second_miss", "doc_count"]))
        f.write("\n## Top second-miss set/prefix hot spots\n\n")
        f.write(markdown_table(hotspot_rows, hotspot_fields))
        f.write("\n## Top documents by second miss\n\n")
        f.write(markdown_table(doc_rows, ["document_id", "capacity_exp", "capacity", "way", "cache_index_type", "first_miss", "second_miss"], 10))
        f.write("\n## Generated CSV files\n\n")
        for path in (prefix_csv, hit_csv, first_csv, second_csv, hotspot_csv, doc_csv, cacheline_csv, cacheline_usage_csv):
            f.write(f"- {os.path.basename(path)}\n")

    with open(ip_md, "w", encoding="utf-8") as f:
        f.write("# Second-miss IP investigation\n\n")
        f.write("## Can existing DB results answer this?\n\n")
        f.write(
            "No. The saved UnifiedCache documents only retain aggregate counters by "
            "cache set and prefix length. The runtime structure has `UniqueDstIP` and "
            "`UniqueDstIPHitCount`, but those maps are not persisted to MongoDB. "
            "The `cacheDebugFileOutputEnabled` constant is currently false, and its "
            "debug path is threshold-based rather than a complete second-miss IP log.\n\n"
        )
        f.write("## What this report provides instead\n\n")
        f.write(
            "- `unified_second_miss_by_prefix.csv`: second misses grouped by capacity and prefix length.\n"
            "- `unified_hit_by_prefix.csv`: cumulative cache hits grouped by capacity and hit prefix length.\n"
            "- `unified_second_miss_hotspots.csv`: largest second-miss cache-set/prefix hot spots.\n"
            "- `unified_cacheline_by_set.csv`: first/second misses and hit counts grouped by cache set.\n"
            "- `unified_cacheline_usage_summary.csv`: active/unused cache-set counts by capacity.\n"
            "- `unified_doc_summary.csv`: result documents sorted by second-miss count.\n\n"
        )
        f.write("## To capture exact IPs in future runs\n\n")
        f.write(
            "Add explicit persistence for second-miss IP/prefix events, or add a bounded "
            "top-N map to the UnifiedCache stat output before insertion. The minimum useful "
            "fields are capacity, way, cache index type, set index, prefix length, masked "
            "destination prefix, and count.\n"
        )

    print(f"Saved report: {report_md}")
    print(f"Saved report: {ip_md}")
    print(f"Saved CSV: {prefix_csv}")
    print(f"Saved CSV: {hit_csv}")
    print(f"Saved CSV: {first_csv}")
    print(f"Saved CSV: {second_csv}")
    print(f"Saved CSV: {hotspot_csv}")
    print(f"Saved CSV: {doc_csv}")
    print(f"Saved CSV: {cacheline_csv}")
    print(f"Saved CSV: {cacheline_usage_csv}")
    print(f"Saved graph: {unused_graph}")
    print(f"Saved graph: {distribution_graph}")
    print(f"Saved graph: {skew_graph}")
    print(f"Saved graph: {prefix_hit_graph}")
    print(f"documents: {len(doc_rows)}")
    print(f"total first miss: {total_first}")
    print(f"total second miss: {total_second}")
    print(f"total exclusive rejected first: {total_exclusive_rejected_first}")
    print(f"total exclusive rejected second: {total_exclusive_rejected_second}")
    print(f"total inclusive non-leaf inserted: {total_inclusive_non_leaf_inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
