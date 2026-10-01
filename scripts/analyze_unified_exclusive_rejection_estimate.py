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
import os
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate UnifiedCache misses that may be caused by exclusive leaf-only insertion "
            "using existing whole-cache miss counters. This does not require rerunning traces."
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
    parser.add_argument("--cache-index-type", type=int, default=None, help="Optional cache index type filter")
    parser.add_argument(
        "--cache-tag-length",
        default=None,
        help="Optional exact cache tag length filter, e.g. 9-24,9-24,10-24,10-24",
    )
    parser.add_argument("--start-exp", type=int, default=6, help="Start exponent, inclusive")
    parser.add_argument("--end-exp", type=int, default=14, help="End exponent, inclusive")
    parser.add_argument(
        "--output",
        default="scripts/reports/unified_exclusive_rejection_estimate/unified_exclusive_rejection_estimate.png",
        help="Output PNG path",
    )
    parser.add_argument(
        "--csv-output",
        default="scripts/reports/unified_exclusive_rejection_estimate/unified_exclusive_rejection_estimate.csv",
        help="Output CSV path",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000, help="MongoDB server selection timeout")
    return parser.parse_args()


def expected_capacities(start_exp: int, end_exp: int) -> List[int]:
    if start_exp > end_exp:
        raise ValueError("--start-exp must be less than or equal to --end-exp")
    return [1 << exp for exp in range(start_exp, end_exp + 1)]


def parse_cache_tag_length(spec: Optional[str]) -> Optional[List[List[int]]]:
    if not spec:
        return None
    parsed: List[List[int]] = []
    for part in spec.split(","):
        fields = part.strip().split("-")
        if len(fields) != 2:
            raise ValueError(f"invalid --cache-tag-length item: {part}")
        parsed.append([int(fields[0]), int(fields[1])])
    return parsed


def max_tag_end(cache_tag_length: object) -> int:
    if not cache_tag_length:
        return 24
    return max(int(pair[1]) for pair in cache_tag_length)


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
    cache_tag_length = parse_cache_tag_length(args.cache_tag_length)
    if cache_tag_length is not None:
        query["simulator_result.parameter.cachetaglength"] = cache_tag_length
    return query


def nested_get(doc: Dict[str, object], path: Iterable[str]) -> object:
    cur: object = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def vector(values: object) -> List[int]:
    if values is None:
        return []
    if isinstance(values, dict):
        return [int(values.get(str(i), values.get(i, 0))) for i in range(32)]
    return [int(value) for value in values]


def fetch_rows(collection, query: Dict[str, object], capacities: List[int]) -> List[Dict[str, object]]:
    projection = {
        "_id": 0,
        "simulator_result.parameter.size": 1,
        "simulator_result.parameter.cachetaglength": 1,
        "simulator_result.processed": 1,
        "simulator_result.hit": 1,
        "simulator_result.statdetail.wholecachefirstmisscount": 1,
        "simulator_result.statdetail.wholecachesecondmisscount": 1,
        "simulator_result.statdetail.WholeCacheFirstMissCount": 1,
        "simulator_result.statdetail.WholeCacheSecondMissCount": 1,
    }
    stats = defaultdict(
        lambda: {
            "doc_count": 0,
            "counter_doc_count": 0,
            "missing_counter_docs": 0,
            "processed": 0,
            "hit": 0,
            "miss": 0,
            "exclusive_rejected_first_estimate": 0,
            "exclusive_rejected_second_estimate": 0,
        }
    )

    for doc in collection.find(query, projection):
        capacity = nested_get(doc, ("simulator_result", "parameter", "size"))
        processed = nested_get(doc, ("simulator_result", "processed"))
        hit = nested_get(doc, ("simulator_result", "hit"))
        if capacity is None or processed is None or hit is None:
            continue

        stat = stats[int(capacity)]
        stat["doc_count"] += 1

        statdetail = nested_get(doc, ("simulator_result", "statdetail"))
        if not isinstance(statdetail, dict):
            stat["missing_counter_docs"] += 1
            continue
        first = vector(statdetail.get("wholecachefirstmisscount") or statdetail.get("WholeCacheFirstMissCount"))
        second = vector(statdetail.get("wholecachesecondmisscount") or statdetail.get("WholeCacheSecondMissCount"))
        if not first or not second:
            stat["missing_counter_docs"] += 1
            continue

        stat["counter_doc_count"] += 1
        stat["processed"] += int(processed)
        stat["hit"] += int(hit)
        stat["miss"] += int(processed) - int(hit)
        tag_length = nested_get(doc, ("simulator_result", "parameter", "cachetaglength"))
        reject_start = max_tag_end(tag_length) + 1
        stat["exclusive_rejected_first_estimate"] += sum(first[reject_start:])
        stat["exclusive_rejected_second_estimate"] += sum(second[reject_start:])

    rows: List[Dict[str, object]] = []
    for capacity in capacities:
        stat = stats[capacity]
        processed = stat["processed"]
        hit = stat["hit"]
        miss = stat["miss"]
        rejected_second = stat["exclusive_rejected_second_estimate"]
        current_hit_rate = hit / processed * 100.0 if processed else 0.0
        potential_hit_rate = (hit + rejected_second) / processed * 100.0 if processed else 0.0
        rows.append(
            {
                "capacity_exp": capacity.bit_length() - 1,
                "capacity": capacity,
                "doc_count": stat["doc_count"],
                "counter_doc_count": stat["counter_doc_count"],
                "missing_counter_docs": stat["missing_counter_docs"],
                "processed": processed,
                "hit": hit,
                "miss": miss,
                "hit_rate_percent": current_hit_rate,
                "exclusive_rejected_first_estimate": stat["exclusive_rejected_first_estimate"],
                "exclusive_rejected_second_estimate": rejected_second,
                "exclusive_rejected_second_per_miss_percent": rejected_second / miss * 100.0 if miss else 0.0,
                "potential_inclusive_hit_rate_percent": potential_hit_rate,
                "potential_hit_rate_gain_points": potential_hit_rate - current_hit_rate,
            }
        )
    return rows


def write_csv(rows: List[Dict[str, object]], output_path: str) -> None:
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fieldnames = [
        "capacity_exp",
        "capacity",
        "doc_count",
        "counter_doc_count",
        "missing_counter_docs",
        "processed",
        "hit",
        "miss",
        "hit_rate_percent",
        "exclusive_rejected_first_estimate",
        "exclusive_rejected_second_estimate",
        "exclusive_rejected_second_per_miss_percent",
        "potential_inclusive_hit_rate_percent",
        "potential_hit_rate_gain_points",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot(rows: List[Dict[str, object]], output_path: str) -> None:
    plottable = [row for row in rows if int(row["doc_count"]) > 0 and int(row["processed"]) > 0]
    if not plottable:
        raise ValueError("No plottable rows were found")

    x = [int(row["capacity"]) for row in plottable]
    labels = [f"$2^{{{int(row['capacity_exp'])}}}$" for row in plottable]
    hit_rate = [float(row["hit_rate_percent"]) for row in plottable]
    potential = [float(row["potential_inclusive_hit_rate_percent"]) for row in plottable]
    rejected = [int(row["exclusive_rejected_second_estimate"]) + 1 for row in plottable]

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(x, hit_rate, color="#dc2626", marker="s", linewidth=2.2, label="current exclusive")
    axes[0].plot(x, potential, color="#2563eb", marker="o", linewidth=2.2, label="potential if rejected repeats hit")
    axes[0].set_ylabel("Hit rate (%)")
    axes[0].set_title("UnifiedCache Exclusive Rejection Estimate")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].plot(x, rejected, color="#7c3aed", marker="^", linewidth=2.2, label="rejected repeat estimate + 1")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("Cache capacity")
    axes[1].set_ylabel("Repeat miss count (log scale)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)

    fig.tight_layout()
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    try:
        capacities = expected_capacities(args.start_exp, args.end_exp)
        query = build_query(args, capacities)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    try:
        collection = client[args.db][args.collection]
        rows = fetch_rows(collection, query, capacities)
    finally:
        client.close()

    if not any(int(row["doc_count"]) > 0 for row in rows):
        print("No UnifiedCache documents found for selected filters.", file=sys.stderr)
        return 1

    write_csv(rows, args.csv_output)
    plot(rows, args.output)
    print(f"Saved graph: {args.output}")
    print(f"Saved CSV: {args.csv_output}")
    for row in rows:
        if int(row["doc_count"]) == 0:
            print(f"2^{row['capacity_exp']}: no data")
            continue
        print(
            f"2^{row['capacity_exp']}: hit={float(row['hit_rate_percent']):.6f}%, "
            f"potential={float(row['potential_inclusive_hit_rate_percent']):.6f}%, "
            f"gain={float(row['potential_hit_rate_gain_points']):.6f}pt, "
            f"rejected_repeat={row['exclusive_rejected_second_estimate']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
