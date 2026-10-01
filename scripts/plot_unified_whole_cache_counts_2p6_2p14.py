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
from typing import Dict, Iterable, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


CapacityStats = Dict[int, Dict[str, float]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plot UnifiedCache whole-cache hit/miss absolute counts from MongoDB "
            "for capacities 2^start-exp..2^end-exp. This uses simulator_result.hit "
            "and simulator_result.processed, not per-cacheline first/second counters."
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
        "--aggregate",
        choices=("mean", "sum"),
        default="mean",
        help=(
            "How to combine multiple documents at the same capacity. "
            "mean is usually best for an absolute-count capacity graph."
        ),
    )
    parser.add_argument(
        "--output",
        default="scripts/unified_whole_cache_hit_miss_counts_2p6_2p14.png",
        help="Output PNG path",
    )
    parser.add_argument(
        "--csv-output",
        default="scripts/unified_whole_cache_hit_miss_counts_2p6_2p14.csv",
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


def fetch_capacity_stats(collection, query: Dict[str, object]) -> CapacityStats:
    projection = {
        "_id": 0,
        "simulator_result.processed": 1,
        "simulator_result.hit": 1,
        "simulator_result.parameter.size": 1,
    }
    stats: CapacityStats = defaultdict(
        lambda: {"processed_sum": 0.0, "hit_sum": 0.0, "miss_sum": 0.0, "docs": 0.0}
    )
    for doc in collection.find(query, projection):
        size = nested_get(doc, ("simulator_result", "parameter", "size"))
        processed = nested_get(doc, ("simulator_result", "processed"))
        hit = nested_get(doc, ("simulator_result", "hit"))
        if size is None or processed is None or hit is None:
            continue

        processed_f = float(processed)
        hit_f = float(hit)
        miss_f = processed_f - hit_f
        if miss_f < 0:
            raise ValueError(f"hit count exceeds processed count for capacity={size}")

        capacity = int(size)
        stats[capacity]["processed_sum"] += processed_f
        stats[capacity]["hit_sum"] += hit_f
        stats[capacity]["miss_sum"] += miss_f
        stats[capacity]["docs"] += 1
    return stats


def result_rows(capacities: List[int], stats: CapacityStats, aggregate: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for capacity in capacities:
        stat = stats[capacity]
        doc_count = int(stat["docs"])
        divisor = doc_count if aggregate == "mean" and doc_count else 1
        processed_value = stat["processed_sum"] / divisor
        hit_value = stat["hit_sum"] / divisor
        miss_value = stat["miss_sum"] / divisor

        rows.append(
            {
                "capacity_exp": capacity.bit_length() - 1,
                "capacity": capacity,
                "aggregate": aggregate,
                "processed_count": processed_value,
                "hit_count": hit_value,
                "miss_count": miss_value,
                "processed_sum": stat["processed_sum"],
                "hit_sum": stat["hit_sum"],
                "miss_sum": stat["miss_sum"],
                "doc_count": doc_count,
            }
        )
    return rows


def format_number(value: object) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}"


def write_csv(rows: List[Dict[str, object]], output_path: str) -> None:
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fieldnames = [
        "capacity_exp",
        "capacity",
        "aggregate",
        "processed_count",
        "hit_count",
        "miss_count",
        "processed_sum",
        "hit_sum",
        "miss_sum",
        "doc_count",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            formatted = dict(row)
            for key in (
                "processed_count",
                "hit_count",
                "miss_count",
                "processed_sum",
                "hit_sum",
                "miss_sum",
            ):
                formatted[key] = format_number(row[key])
            writer.writerow(formatted)


def configure_capacity_axis(ax, rows: List[Dict[str, object]]) -> None:
    x = [int(row["capacity"]) for row in rows]
    ax.set_xscale("log", base=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"$2^{{{int(row['capacity_exp'])}}}$" for row in rows])
    ax.set_xlim(x[0], x[-1])


def plot(rows: List[Dict[str, object]], output_path: str, aggregate: str) -> None:
    plottable = [row for row in rows if int(row["doc_count"]) > 0]
    if not plottable:
        raise ValueError("No plottable rows were found")

    x = [int(row["capacity"]) for row in plottable]
    miss_y = [float(row["miss_count"]) for row in plottable]
    hit_y = [float(row["hit_count"]) for row in plottable]

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    fig.suptitle(f"UnifiedCache Whole-Cache Hit/Miss Counts ({aggregate})")

    axes[0].plot(
        x,
        miss_y,
        color="#dc2626",
        marker="s",
        linewidth=2.2,
        label="Miss count",
    )
    axes[0].set_ylabel("Miss count")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].plot(
        x,
        hit_y,
        color="#2563eb",
        marker="o",
        linewidth=2.2,
        label="Hit count",
    )
    axes[1].set_xlabel("Cache Capacity")
    axes[1].set_ylabel("Hit count")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")
    configure_capacity_axis(axes[1], plottable)

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
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    try:
        collection = client[args.db][args.collection]
        query = build_query(args, capacities)
        stats = fetch_capacity_stats(collection, query)
    finally:
        client.close()

    rows = result_rows(capacities, stats, args.aggregate)
    if not any(int(row["doc_count"]) > 0 for row in rows):
        print("No UnifiedCache documents found for the selected capacity range and filters.", file=sys.stderr)
        return 1

    write_csv(rows, args.csv_output)
    try:
        plot(rows, args.output, args.aggregate)
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
            f"hit={format_number(row['hit_count'])}, "
            f"miss={format_number(row['miss_count'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
