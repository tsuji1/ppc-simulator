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
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


CapacityStats = Dict[int, Dict[str, int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plot UnifiedCache first/second cache miss counts from MongoDB "
            "for capacities 2^start-exp..2^end-exp."
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
        "--miss-scope",
        choices=("cacheline", "whole-cache"),
        default="cacheline",
        help=(
            "cacheline uses the original per-set/cacheline first/second counters; "
            "whole-cache uses counters tracked once across the whole UnifiedCache."
        ),
    )
    parser.add_argument(
        "--plot-unit",
        choices=("absolute", "percent"),
        default="absolute",
        help="Plot absolute miss counts or percentages within first+second misses.",
    )
    parser.add_argument(
        "--y-focus",
        choices=("none", "first"),
        default="none",
        help="For absolute plots, optionally zoom the y-axis around first reference misses.",
    )
    parser.add_argument(
        "--ymin",
        type=float,
        default=None,
        help="Optional y-axis minimum override.",
    )
    parser.add_argument(
        "--ymax",
        type=float,
        default=None,
        help="Optional y-axis maximum override.",
    )
    parser.add_argument(
        "--tail-start-exp",
        type=int,
        default=None,
        help=(
            "Optional exponent where large-capacity trend points begin. "
            "Points at and after this capacity are drawn as a lighter dashed tail."
        ),
    )
    parser.add_argument(
        "--output",
        default="scripts/unified_first_second_miss_counts_2p6_2p14.png",
        help="Output PNG path",
    )
    parser.add_argument(
        "--csv-output",
        default="scripts/unified_first_second_miss_counts_2p6_2p14.csv",
        help="Output CSV path",
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


def sum_compressed_counter_rows(blob: object, rows: Optional[int], field_name: str) -> int:
    if blob is None:
        return 0
    raw = gzip.decompress(bytes(blob))
    if len(raw) % 4 != 0:
        raise ValueError(f"{field_name} decompressed byte length is not divisible by 4")
    if rows is not None:
        expected_bytes = rows * 32 * 4
        if len(raw) != expected_bytes:
            raise ValueError(
                f"{field_name} has {len(raw)} bytes after decompression; "
                f"expected {expected_bytes} bytes from unified_stat_rows={rows}"
            )
    return sum(value for (value,) in struct.iter_unpack("<I", raw))


def sum_legacy_counter_rows(rows: object) -> int:
    if not rows:
        return 0
    total = 0
    for row in rows:
        total += sum(int(value) for value in row)
    return total


def sum_counter_vector(values: object) -> int:
    if values is None:
        return 0
    if isinstance(values, dict):
        iterable = values.values()
    else:
        iterable = values
    return sum(int(value) for value in iterable)


def cacheline_miss_counts_from_doc(doc: Dict[str, object]) -> Tuple[int, int]:
    rows_value = doc.get("unified_stat_rows")
    rows = int(rows_value) if rows_value is not None else None

    first_blob = doc.get("first_miss_count_compressed")
    second_blob = doc.get("second_miss_count_compressed")
    if first_blob is not None or second_blob is not None:
        first = sum_compressed_counter_rows(first_blob, rows, "first_miss_count_compressed")
        second = sum_compressed_counter_rows(second_blob, rows, "second_miss_count_compressed")
        return first, second

    statdetail = nested_get(doc, ("simulator_result", "statdetail"))
    first_rows = None
    second_rows = None
    if isinstance(statdetail, dict):
        first_rows = statdetail.get("cachelinefirstmisscount") or statdetail.get("CachelineFirstMissCount")
        second_rows = statdetail.get("cachelinesecondmisscount") or statdetail.get("CachelineSecondMissCount")
    return sum_legacy_counter_rows(first_rows), sum_legacy_counter_rows(second_rows)


def whole_cache_miss_counts_from_doc(doc: Dict[str, object]) -> Optional[Tuple[int, int]]:
    statdetail = nested_get(doc, ("simulator_result", "statdetail"))
    if not isinstance(statdetail, dict):
        return None

    first_counts = statdetail.get("wholecachefirstmisscount") or statdetail.get(
        "WholeCacheFirstMissCount"
    )
    second_counts = statdetail.get("wholecachesecondmisscount") or statdetail.get(
        "WholeCacheSecondMissCount"
    )
    if first_counts is None or second_counts is None:
        return None
    return sum_counter_vector(first_counts), sum_counter_vector(second_counts)


def miss_counts_from_doc(doc: Dict[str, object], miss_scope: str) -> Optional[Tuple[int, int]]:
    if miss_scope == "whole-cache":
        return whole_cache_miss_counts_from_doc(doc)
    return cacheline_miss_counts_from_doc(doc)


def fetch_capacity_stats(collection, query: Dict[str, object], miss_scope: str) -> CapacityStats:
    projection = {
        "_id": 0,
        "simulator_result.parameter.size": 1,
        "simulator_result.statdetail.cachelinefirstmisscount": 1,
        "simulator_result.statdetail.cachelinesecondmisscount": 1,
        "simulator_result.statdetail.CachelineFirstMissCount": 1,
        "simulator_result.statdetail.CachelineSecondMissCount": 1,
        "simulator_result.statdetail.wholecachefirstmisscount": 1,
        "simulator_result.statdetail.wholecachesecondmisscount": 1,
        "simulator_result.statdetail.WholeCacheFirstMissCount": 1,
        "simulator_result.statdetail.WholeCacheSecondMissCount": 1,
        "unified_stat_rows": 1,
        "first_miss_count_compressed": 1,
        "second_miss_count_compressed": 1,
    }
    stats: CapacityStats = defaultdict(lambda: {"first": 0, "second": 0, "docs": 0, "missing_docs": 0})
    for doc in collection.find(query, projection):
        size = nested_get(doc, ("simulator_result", "parameter", "size"))
        if size is None:
            continue
        capacity = int(size)
        counts = miss_counts_from_doc(doc, miss_scope)
        if counts is None:
            stats[capacity]["missing_docs"] += 1
            continue
        first, second = counts
        stats[capacity]["first"] += first
        stats[capacity]["second"] += second
        stats[capacity]["docs"] += 1
    return stats


def ratio_rows(capacities: List[int], stats: CapacityStats, miss_scope: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for capacity in capacities:
        first = stats[capacity]["first"]
        second = stats[capacity]["second"]
        total = first + second
        first_ratio = (first / total * 100.0) if total else 0.0
        second_ratio = (second / total * 100.0) if total else 0.0
        rows.append(
            {
                "capacity": capacity,
                "capacity_exp": capacity.bit_length() - 1,
                "miss_scope": miss_scope,
                "first_miss": first,
                "second_miss": second,
                "total_miss": total,
                "first_miss_ratio_percent": first_ratio,
                "second_miss_ratio_percent": second_ratio,
                "doc_count": stats[capacity]["docs"],
                "missing_doc_count": stats[capacity]["missing_docs"],
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
        "miss_scope",
        "first_miss",
        "second_miss",
        "total_miss",
        "first_miss_ratio_percent",
        "second_miss_ratio_percent",
        "doc_count",
        "missing_doc_count",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def y_limits_for_absolute(
    first_y: List[int],
    second_y: List[int],
    y_focus: str,
    ymin: Optional[float],
    ymax: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    if ymin is not None or ymax is not None:
        return ymin, ymax
    if y_focus != "first" or not first_y:
        return None, None

    max_first = max(first_y)
    min_first = min(first_y)
    span = max(max_first - min_first, max_first * 0.1, 1)
    lower = max(0.0, min_first - span * 0.35)
    upper = max_first + span * 0.35
    return lower, upper


def split_tail_points(
    x: List[int],
    y: List[float],
    tail_start_capacity: Optional[int],
) -> Tuple[Tuple[List[int], List[float]], Tuple[List[int], List[float]]]:
    if tail_start_capacity is None:
        return (x, y), ([], [])

    prev_point: Optional[Tuple[int, float]] = None
    main_x: List[int] = []
    main_y: List[float] = []
    tail_x: List[int] = []
    tail_y: List[float] = []
    for xi, yi in zip(x, y):
        if xi >= tail_start_capacity:
            if not tail_x and prev_point is not None and prev_point[0] < tail_start_capacity:
                tail_x.append(prev_point[0])
                tail_y.append(prev_point[1])
            tail_x.append(xi)
            tail_y.append(yi)
        else:
            main_x.append(xi)
            main_y.append(yi)
            prev_point = (xi, yi)
    return (main_x, main_y), (tail_x, tail_y)


def plot_series(
    x: List[int],
    y: List[float],
    color: str,
    marker: str,
    label: str,
    tail_start_capacity: Optional[int],
) -> None:
    (main_x, main_y), (tail_x, tail_y) = split_tail_points(x, y, tail_start_capacity)
    if main_x:
        plt.plot(
            main_x,
            main_y,
            color=color,
            marker=marker,
            linewidth=2.2,
            label=label,
        )
    if tail_x:
        plt.plot(
            tail_x,
            tail_y,
            color=color,
            marker=marker,
            linewidth=2.0,
            linestyle="--",
            alpha=0.45,
            label=f"{label} (large-capacity trend)",
        )


def plot(
    rows: List[Dict[str, object]],
    output_path: str,
    plot_unit: str,
    miss_scope: str,
    y_focus: str,
    ymin: Optional[float],
    ymax: Optional[float],
    tail_start_exp: Optional[int],
) -> None:
    plottable = [row for row in rows if int(row["doc_count"]) > 0 and int(row["total_miss"]) > 0]
    if not plottable:
        raise ValueError("No plottable rows with miss counters were found")

    x = [int(row["capacity"]) for row in plottable]
    if plot_unit == "percent":
        first_y = [float(row["first_miss_ratio_percent"]) for row in plottable]
        second_y = [float(row["second_miss_ratio_percent"]) for row in plottable]
        ylabel = "Ratio in First+Second Misses (%)"
    else:
        first_y = [int(row["first_miss"]) for row in plottable]
        second_y = [int(row["second_miss"]) for row in plottable]
        ylabel = "Miss count"

    scope_label = "Whole-cache" if miss_scope == "whole-cache" else "Cacheline"
    tail_start_capacity = (1 << tail_start_exp) if tail_start_exp is not None else None

    plt.figure(figsize=(11, 6))
    plot_series(x, first_y, "#2563eb", "o", "First reference miss", tail_start_capacity)
    plot_series(x, second_y, "#dc2626", "s", "Second-or-later miss", tail_start_capacity)

    plt.title(f"UnifiedCache {scope_label} First/Second Miss")
    plt.xlabel("Cache Capacity")
    plt.ylabel(ylabel)
    plt.xscale("log", base=2)
    plt.xticks(x, [f"$2^{{{int(row['capacity_exp'])}}}$" for row in plottable])
    if plot_unit == "percent":
        plt.ylim(0, 100)
    else:
        computed_ymin, computed_ymax = y_limits_for_absolute(first_y, second_y, y_focus, ymin, ymax)
        if computed_ymin is not None or computed_ymax is not None:
            plt.ylim(computed_ymin, computed_ymax)
    plt.grid(True, alpha=0.3)
    plt.legend(loc="best")
    plt.tight_layout()

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_path, dpi=170)
    plt.close()


def main() -> int:
    args = parse_args()
    try:
        capacities = expected_capacities(args.start_exp, args.end_exp)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    try:
        collection = client[args.db][args.collection]
        query = build_query(args, capacities)
        stats = fetch_capacity_stats(collection, query, args.miss_scope)
    finally:
        client.close()

    rows = ratio_rows(capacities, stats, args.miss_scope)
    if not any(int(row["doc_count"]) > 0 for row in rows):
        if any(int(row["missing_doc_count"]) > 0 for row in rows):
            print(
                "Matching UnifiedCache documents do not contain whole-cache first/second counters. "
                "Re-run the simulations with the updated code and DB insert enabled, then retry "
                "--miss-scope whole-cache.",
                file=sys.stderr,
            )
            return 1
        print("No UnifiedCache documents found for the selected capacity range and filters.", file=sys.stderr)
        return 1

    write_csv(rows, args.csv_output)
    try:
        plot(
            rows,
            args.output,
            args.plot_unit,
            args.miss_scope,
            args.y_focus,
            args.ymin,
            args.ymax,
            args.tail_start_exp,
        )
    except ValueError as err:
        print(err, file=sys.stderr)
        print(f"Saved CSV: {args.csv_output}")
        return 1

    print(f"Saved graph: {args.output}")
    print(f"Saved CSV: {args.csv_output}")
    for row in rows:
        if int(row["doc_count"]) == 0:
            print(f"2^{row['capacity_exp']}: no data")
            continue
        print(
            f"2^{row['capacity_exp']}: docs={row['doc_count']}, "
            f"missing_docs={row['missing_doc_count']}, "
            f"first={row['first_miss']}, "
            f"second={row['second_miss']}, "
            f"first_ratio={row['first_miss_ratio_percent']:.4f}%, "
            f"second_ratio={row['second_miss_ratio_percent']:.4f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
