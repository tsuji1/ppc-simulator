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


POLICIES = ("exclusive", "inclusive")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare UnifiedCache exclusive/inclusive insertion policies from MongoDB. "
            "The exclusive-rejected counters are available only for results generated "
            "after the insertion-policy instrumentation was added."
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
        "--include-legacy-exclusive",
        action="store_true",
        help="Treat older documents without insertionpolicy as exclusive. Off by default.",
    )
    parser.add_argument(
        "--output",
        default="scripts/reports/unified_insertion_policy_comparison/unified_insertion_policy_comparison.png",
        help="Output PNG path",
    )
    parser.add_argument(
        "--csv-output",
        default="scripts/reports/unified_insertion_policy_comparison/unified_insertion_policy_comparison.csv",
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
    if not args.include_legacy_exclusive:
        query["simulator_result.parameter.insertionpolicy"] = {"$in": list(POLICIES)}
    return query


def nested_get(doc: Dict[str, object], path: Iterable[str]) -> object:
    cur: object = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def sum_counter_vector(values: object) -> int:
    if values is None:
        return 0
    if isinstance(values, dict):
        iterable = values.values()
    else:
        iterable = values
    return sum(int(value) for value in iterable)


def insertion_policy(doc: Dict[str, object]) -> str:
    policy = nested_get(doc, ("simulator_result", "parameter", "insertionpolicy"))
    if policy in POLICIES:
        return str(policy)
    return "exclusive"


def fetch_rows(collection, query: Dict[str, object], capacities: List[int]) -> List[Dict[str, object]]:
    projection = {
        "_id": 0,
        "simulator_result.parameter.size": 1,
        "simulator_result.parameter.insertionpolicy": 1,
        "simulator_result.processed": 1,
        "simulator_result.hit": 1,
        "simulator_result.statdetail.exclusiverejectedfirstmisscount": 1,
        "simulator_result.statdetail.exclusiverejectedsecondmisscount": 1,
        "simulator_result.statdetail.inclusivenonleafinsertedcount": 1,
        "simulator_result.statdetail.ExclusiveRejectedFirstMissCount": 1,
        "simulator_result.statdetail.ExclusiveRejectedSecondMissCount": 1,
        "simulator_result.statdetail.InclusiveNonLeafInsertedCount": 1,
    }
    stats = defaultdict(
        lambda: {
            "doc_count": 0,
            "processed": 0,
            "hit": 0,
            "exclusive_rejected_first": 0,
            "exclusive_rejected_second": 0,
            "inclusive_non_leaf_inserted": 0,
        }
    )

    for doc in collection.find(query, projection):
        capacity = nested_get(doc, ("simulator_result", "parameter", "size"))
        processed = nested_get(doc, ("simulator_result", "processed"))
        hit = nested_get(doc, ("simulator_result", "hit"))
        if capacity is None or processed is None or hit is None:
            continue

        policy = insertion_policy(doc)
        statdetail = nested_get(doc, ("simulator_result", "statdetail"))
        if not isinstance(statdetail, dict):
            statdetail = {}

        key = (int(capacity), policy)
        stats[key]["doc_count"] += 1
        stats[key]["processed"] += int(processed)
        stats[key]["hit"] += int(hit)
        stats[key]["exclusive_rejected_first"] += sum_counter_vector(
            statdetail.get("exclusiverejectedfirstmisscount")
            or statdetail.get("ExclusiveRejectedFirstMissCount")
        )
        stats[key]["exclusive_rejected_second"] += sum_counter_vector(
            statdetail.get("exclusiverejectedsecondmisscount")
            or statdetail.get("ExclusiveRejectedSecondMissCount")
        )
        stats[key]["inclusive_non_leaf_inserted"] += sum_counter_vector(
            statdetail.get("inclusivenonleafinsertedcount")
            or statdetail.get("InclusiveNonLeafInsertedCount")
        )

    rows: List[Dict[str, object]] = []
    for capacity in capacities:
        for policy in POLICIES:
            values = stats[(capacity, policy)]
            processed = values["processed"]
            hit = values["hit"]
            miss = processed - hit if processed else 0
            rejected_total = values["exclusive_rejected_first"] + values["exclusive_rejected_second"]
            rows.append(
                {
                    "capacity_exp": capacity.bit_length() - 1,
                    "capacity": capacity,
                    "insertion_policy": policy,
                    "doc_count": values["doc_count"],
                    "processed": processed,
                    "hit": hit,
                    "miss": miss,
                    "hit_rate_percent": (hit / processed * 100.0) if processed else 0.0,
                    "exclusive_rejected_first": values["exclusive_rejected_first"],
                    "exclusive_rejected_second": values["exclusive_rejected_second"],
                    "exclusive_rejected_total": rejected_total,
                    "exclusive_rejected_second_per_miss_percent": (
                        values["exclusive_rejected_second"] / miss * 100.0
                    )
                    if miss
                    else 0.0,
                    "inclusive_non_leaf_inserted": values["inclusive_non_leaf_inserted"],
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
        "insertion_policy",
        "doc_count",
        "processed",
        "hit",
        "miss",
        "hit_rate_percent",
        "exclusive_rejected_first",
        "exclusive_rejected_second",
        "exclusive_rejected_total",
        "exclusive_rejected_second_per_miss_percent",
        "inclusive_non_leaf_inserted",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def rows_by_policy(rows: List[Dict[str, object]], policy: str) -> List[Dict[str, object]]:
    return [row for row in rows if row["insertion_policy"] == policy and int(row["doc_count"]) > 0]


def configure_capacity_axis(ax, rows: List[Dict[str, object]]) -> None:
    x = [int(row["capacity"]) for row in rows]
    ax.set_xscale("log", base=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"$2^{{{int(row['capacity_exp'])}}}$" for row in rows])


def plot(rows: List[Dict[str, object]], output_path: str) -> None:
    exclusive_rows = rows_by_policy(rows, "exclusive")
    inclusive_rows = rows_by_policy(rows, "inclusive")
    if not exclusive_rows and not inclusive_rows:
        raise ValueError("No plottable UnifiedCache rows were found")

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=False)
    axes[0].set_title("UnifiedCache Hit Rate by Insertion Policy")
    for policy, policy_rows, color, marker in (
        ("exclusive", exclusive_rows, "#dc2626", "s"),
        ("inclusive", inclusive_rows, "#2563eb", "o"),
    ):
        if not policy_rows:
            continue
        x = [int(row["capacity"]) for row in policy_rows]
        y = [float(row["hit_rate_percent"]) for row in policy_rows]
        axes[0].plot(x, y, color=color, marker=marker, linewidth=2.2, label=policy)
    axis_rows = inclusive_rows or exclusive_rows
    configure_capacity_axis(axes[0], axis_rows)
    axes[0].set_xlabel("Cache capacity")
    axes[0].set_ylabel("Hit rate (%)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].set_title("Exclusive Rejected Repeat Misses / Inclusive Non-Leaf Inserts")
    if exclusive_rows:
        x = [int(row["capacity"]) for row in exclusive_rows]
        y = [int(row["exclusive_rejected_second"]) for row in exclusive_rows]
        axes[1].plot(x, [value + 1 for value in y], color="#dc2626", marker="s", linewidth=2.2, label="exclusive rejected repeat + 1")
        configure_capacity_axis(axes[1], exclusive_rows)
    if inclusive_rows:
        x = [int(row["capacity"]) for row in inclusive_rows]
        y = [int(row["inclusive_non_leaf_inserted"]) for row in inclusive_rows]
        axes[1].plot(x, [value + 1 for value in y], color="#2563eb", marker="o", linewidth=2.2, label="inclusive non-leaf inserts + 1")
        configure_capacity_axis(axes[1], inclusive_rows)
    axes[1].set_yscale("log")
    axes[1].set_xlabel("Cache capacity")
    axes[1].set_ylabel("Count (log scale)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")

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
            print(f"2^{row['capacity_exp']} {row['insertion_policy']}: no data")
            continue
        print(
            f"2^{row['capacity_exp']} {row['insertion_policy']}: "
            f"hit_rate={float(row['hit_rate_percent']):.6f}%, "
            f"rejected_repeat={row['exclusive_rejected_second']}, "
            f"inclusive_non_leaf_inserted={row['inclusive_non_leaf_inserted']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
