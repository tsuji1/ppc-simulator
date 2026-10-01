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
from typing import Dict, Iterable, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot latest UnifiedCache exclusive/inclusive results from MongoDB."
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI (default: DATABASE_URL env or mongodb://localhost:27017/)",
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--rule-file-name", required=True)
    parser.add_argument("--trace-file-name", required=True)
    parser.add_argument("--processed", type=int, required=True)
    parser.add_argument("--way", type=int, required=True)
    parser.add_argument("--cache-index-type", type=int, required=True)
    parser.add_argument("--start-exp", type=int, default=6)
    parser.add_argument("--end-exp", type=int, default=14)
    parser.add_argument(
        "--policies",
        default="exclusive,inclusive",
        help="Comma-separated insertion policies to compare.",
    )
    parser.add_argument(
        "--output",
        default="scripts/unified_latest_policy_comparison.png",
        help="Output PNG path.",
    )
    parser.add_argument(
        "--csv-output",
        default="scripts/unified_latest_policy_comparison.csv",
        help="Output CSV path.",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser.parse_args()


def nested_get(doc: Dict[str, object], path: Iterable[str]) -> object:
    cur: object = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def sum_counter_vector(values: object) -> Optional[int]:
    if values is None:
        return None
    if isinstance(values, dict):
        iterable = values.values()
    else:
        iterable = values
    return sum(int(value) for value in iterable)


def expected_capacities(start_exp: int, end_exp: int) -> List[int]:
    if start_exp > end_exp:
        raise ValueError("--start-exp must be <= --end-exp")
    return [1 << exp for exp in range(start_exp, end_exp + 1)]


def latest_doc_for_capacity(collection, base_query: Dict[str, object], capacity: int):
    query = dict(base_query)
    query["simulator_result.parameter.size"] = capacity
    return collection.find_one(
        query,
        sort=[("timestamp", -1), ("_id", -1)],
        projection={
            "_id": 1,
            "timestamp": 1,
            "simulator_result.processed": 1,
            "simulator_result.hit": 1,
            "simulator_result.parameter": 1,
            "simulator_result.statdetail.wholecachefirstmisscount": 1,
            "simulator_result.statdetail.wholecachesecondmisscount": 1,
        },
    )


def build_rows(collection, args: argparse.Namespace) -> List[Dict[str, object]]:
    capacities = expected_capacities(args.start_exp, args.end_exp)
    policies = [part.strip() for part in args.policies.split(",") if part.strip()]
    rows: List[Dict[str, object]] = []
    for policy in policies:
        base_query: Dict[str, object] = {
            "simulator_result.type": "UnifiedCache",
            "simulator_result.processed": args.processed,
            "simulator_result.parameter.way": args.way,
            "simulator_result.parameter.cacheindextype": args.cache_index_type,
            "simulator_result.parameter.insertionpolicy": policy,
            "rule_file_name": args.rule_file_name,
            "trace_file_name": args.trace_file_name,
        }
        for capacity in capacities:
            doc = latest_doc_for_capacity(collection, base_query, capacity)
            if doc is None:
                rows.append(
                    {
                        "policy": policy,
                        "capacity_exp": capacity.bit_length() - 1,
                        "capacity": capacity,
                        "doc_found": 0,
                        "timestamp": "",
                        "object_id": "",
                        "processed": "",
                        "hit": "",
                        "miss": "",
                        "hit_rate_percent": "",
                        "miss_rate_percent": "",
                        "whole_cache_first_miss": "",
                        "whole_cache_second_miss": "",
                    }
                )
                continue

            processed = int(nested_get(doc, ("simulator_result", "processed")))
            hit = int(nested_get(doc, ("simulator_result", "hit")))
            miss = processed - hit
            statdetail = nested_get(doc, ("simulator_result", "statdetail"))
            first_miss = None
            second_miss = None
            if isinstance(statdetail, dict):
                first_miss = sum_counter_vector(statdetail.get("wholecachefirstmisscount"))
                second_miss = sum_counter_vector(statdetail.get("wholecachesecondmisscount"))

            rows.append(
                {
                    "policy": policy,
                    "capacity_exp": capacity.bit_length() - 1,
                    "capacity": capacity,
                    "doc_found": 1,
                    "timestamp": doc.get("timestamp", ""),
                    "object_id": str(doc.get("_id", "")),
                    "processed": processed,
                    "hit": hit,
                    "miss": miss,
                    "hit_rate_percent": hit / processed * 100.0 if processed else 0.0,
                    "miss_rate_percent": miss / processed * 100.0 if processed else 0.0,
                    "whole_cache_first_miss": "" if first_miss is None else first_miss,
                    "whole_cache_second_miss": "" if second_miss is None else second_miss,
                }
            )
    return rows


def write_csv(rows: List[Dict[str, object]], output_path: str) -> None:
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fieldnames = [
        "policy",
        "capacity_exp",
        "capacity",
        "doc_found",
        "timestamp",
        "object_id",
        "processed",
        "hit",
        "miss",
        "hit_rate_percent",
        "miss_rate_percent",
        "whole_cache_first_miss",
        "whole_cache_second_miss",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot(rows: List[Dict[str, object]], output_path: str) -> None:
    plottable = [row for row in rows if int(row["doc_found"]) == 1]
    if not plottable:
        raise ValueError("No plottable rows found")

    policies = []
    for row in plottable:
        if row["policy"] not in policies:
            policies.append(str(row["policy"]))

    colors = {
        "exclusive": "#2563eb",
        "inclusive": "#dc2626",
    }
    markers = {
        "exclusive": "o",
        "inclusive": "s",
    }

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    fig.suptitle("UnifiedCache Latest Results by Insertion Policy")

    xticks = sorted({int(row["capacity"]) for row in plottable})
    for policy in policies:
        policy_rows = [row for row in plottable if row["policy"] == policy]
        policy_rows.sort(key=lambda row: int(row["capacity"]))
        x = [int(row["capacity"]) for row in policy_rows]
        hit_rate = [float(row["hit_rate_percent"]) for row in policy_rows]
        miss = [int(row["miss"]) for row in policy_rows]
        axes[0].plot(
            x,
            hit_rate,
            color=colors.get(policy, None),
            marker=markers.get(policy, "o"),
            linewidth=2.2,
            label=policy,
        )
        axes[1].plot(
            x,
            miss,
            color=colors.get(policy, None),
            marker=markers.get(policy, "o"),
            linewidth=2.2,
            label=policy,
        )

    axes[0].set_ylabel("Hit rate (%)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="best")

    axes[1].set_xlabel("Cache Capacity")
    axes[1].set_ylabel("Miss count")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")
    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(xticks)
    axes[1].set_xticklabels([f"$2^{{{capacity.bit_length() - 1}}}$" for capacity in xticks])

    fig.tight_layout()
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    try:
        collection = client[args.db][args.collection]
        rows = build_rows(collection, args)
    finally:
        client.close()

    write_csv(rows, args.csv_output)
    try:
        plot(rows, args.output)
    except ValueError as err:
        print(err, file=sys.stderr)
        print(f"Saved CSV: {args.csv_output}")
        return 1

    print(f"Saved graph: {args.output}")
    print(f"Saved CSV: {args.csv_output}")
    for row in rows:
        if int(row["doc_found"]) == 0:
            print(f"{row['policy']} 2^{row['capacity_exp']}: no data")
            continue
        print(
            f"{row['policy']} 2^{row['capacity_exp']}: "
            f"hit_rate={float(row['hit_rate_percent']):.4f}%, "
            f"miss={row['miss']}, timestamp={row['timestamp']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
