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
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


FIXED_INDEXES = (16, 18, 20, 22, 24)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare last-inserted-prefix UnifiedCache against fixed prefix indexes."
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--rule", default="rib.20260327.0600.unique.rule")
    parser.add_argument("--trace", default="202603271400.pcap")
    parser.add_argument("--processed", type=int, default=100000)
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--capacities", default="1024,4096,16384")
    parser.add_argument(
        "--output-dir", default="scripts/reports/unified_adaptive_index_smoke"
    )
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser.parse_args()


def latest_documents(collection, query, projection):
    latest = {}
    counts = {}
    for doc in collection.find(query, projection):
        parameter = doc["simulator_result"]["parameter"]
        policy = parameter.get("indexpolicy", "fixed")
        index_type = int(parameter.get("cacheindextype", 0))
        capacity = int(parameter["size"])
        key = (policy, index_type, capacity)
        counts[key] = counts.get(key, 0) + 1
        if key not in latest or doc.get("timestamp") > latest[key].get("timestamp"):
            latest[key] = doc
    return latest, counts


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def as_counts(value):
    values = list(value or [])
    values.extend([0] * (32 - len(values)))
    return [int(v) for v in values[:32]]


def main():
    args = parse_args()
    capacities = [int(v.strip()) for v in args.capacities.split(",") if v.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    collection = client[args.db][args.collection]
    query = {
        "simulator_result.type": "UnifiedCache",
        "simulator_result.processed": args.processed,
        "simulator_result.parameter.way": args.way,
        "simulator_result.parameter.size": {"$in": capacities},
        "rule_file_name": args.rule,
        "trace_file_name": args.trace,
        "$or": [
            {
                "simulator_result.parameter.indexpolicy": "last-inserted-prefix",
                "simulator_result.parameter.cacheindextype": 18,
            },
            {
                "simulator_result.parameter.indexpolicy": {"$exists": False},
                "simulator_result.parameter.cacheindextype": {"$in": list(FIXED_INDEXES)},
            },
            {
                "simulator_result.parameter.indexpolicy": "fixed",
                "simulator_result.parameter.cacheindextype": {"$in": list(FIXED_INDEXES)},
            },
        ],
    }
    projection = {
        "timestamp": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter": 1,
        "simulator_result.statdetail.adaptivelookupcount": 1,
        "simulator_result.statdetail.adaptiveselectioncount": 1,
        "simulator_result.statdetail.adaptiveswitchcount": 1,
        "simulator_result.statdetail.adaptivefinalindexlength": 1,
    }
    latest, doc_counts = latest_documents(collection, query, projection)

    comparison_rows = []
    series = {f"fixed /{length}": [] for length in FIXED_INDEXES}
    series["adaptive"] = []
    for capacity in capacities:
        for policy, index_type, label in [
            *(('fixed', length, f"fixed /{length}") for length in FIXED_INDEXES),
            ("last-inserted-prefix", 18, "adaptive"),
        ]:
            key = (policy, index_type, capacity)
            doc = latest.get(key)
            hitrate = None
            if doc is not None:
                hitrate = float(doc["simulator_result"]["hitrate"]) * 100.0
            series[label].append(hitrate)
            comparison_rows.append(
                {
                    "capacity": capacity,
                    "capacity_exp": capacity.bit_length() - 1,
                    "policy": policy,
                    "index_type": index_type,
                    "label": label,
                    "hitrate_percent": "" if hitrate is None else f"{hitrate:.6f}",
                    "doc_count": doc_counts.get(key, 0),
                    "timestamp": "" if doc is None else doc.get("timestamp", ""),
                }
            )
    write_csv(
        output_dir / "hitrate_comparison.csv",
        comparison_rows,
        [
            "capacity",
            "capacity_exp",
            "policy",
            "index_type",
            "label",
            "hitrate_percent",
            "doc_count",
            "timestamp",
        ],
    )

    fig, ax = plt.subplots(figsize=(9, 5))
    xlabels = [f"2^{capacity.bit_length() - 1}" for capacity in capacities]
    for label, values in series.items():
        points = [(i, value) for i, value in enumerate(values) if value is not None]
        if points:
            ax.plot(
                [p[0] for p in points],
                [p[1] for p in points],
                marker="o",
                linewidth=2.5 if label == "adaptive" else 1.2,
                label=label,
            )
    ax.set_xticks(range(len(capacities)), xlabels)
    ax.set_xlabel("cache capacity")
    ax.set_ylabel("hitrate (%)")
    ax.set_title("UnifiedCache adaptive index smoke comparison")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(output_dir / "hitrate_comparison.png", dpi=180)
    plt.close(fig)

    adaptive_rows = []
    distribution_by_capacity = {}
    for capacity in capacities:
        key = ("last-inserted-prefix", 18, capacity)
        doc = latest.get(key)
        if doc is None:
            continue
        stat = doc["simulator_result"].get("statdetail", {})
        lookups = as_counts(stat.get("adaptivelookupcount"))
        selections = as_counts(stat.get("adaptiveselectioncount"))
        lookup_total = sum(lookups)
        selection_total = sum(selections)
        distribution_by_capacity[capacity] = (lookups, selections)
        for length in range(6, 25):
            adaptive_rows.append(
                {
                    "capacity": capacity,
                    "capacity_exp": capacity.bit_length() - 1,
                    "index_length": length,
                    "lookup_count": lookups[length],
                    "lookup_ratio_percent": f"{lookups[length] / lookup_total * 100:.6f}" if lookup_total else "0.000000",
                    "selection_count": selections[length],
                    "selection_ratio_percent": f"{selections[length] / selection_total * 100:.6f}" if selection_total else "0.000000",
                    "switch_count": int(stat.get("adaptiveswitchcount", 0)),
                    "final_index_length": int(stat.get("adaptivefinalindexlength", 0)),
                }
            )
    write_csv(
        output_dir / "adaptive_index_distribution.csv",
        adaptive_rows,
        [
            "capacity",
            "capacity_exp",
            "index_length",
            "lookup_count",
            "lookup_ratio_percent",
            "selection_count",
            "selection_ratio_percent",
            "switch_count",
            "final_index_length",
        ],
    )

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    lengths = list(range(6, 25))
    for capacity, (lookups, selections) in distribution_by_capacity.items():
        label = f"2^{capacity.bit_length() - 1}"
        lookup_total = sum(lookups)
        selection_total = sum(selections)
        axes[0].plot(lengths, [lookups[v] / lookup_total * 100 if lookup_total else 0 for v in lengths], marker="o", label=label)
        axes[1].plot(lengths, [selections[v] / selection_total * 100 if selection_total else 0 for v in lengths], marker="o", label=label)
    axes[0].set_ylabel("lookup share (%)")
    axes[0].set_title("Adaptive index length distribution")
    axes[1].set_ylabel("selection share (%)")
    axes[1].set_xlabel("index prefix length")
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.legend()
    axes[1].set_xticks(lengths)
    fig.tight_layout()
    fig.savefig(output_dir / "adaptive_index_distribution.png", dpi=180)
    plt.close(fig)

    missing = [row["label"] + "@2^" + str(row["capacity_exp"]) for row in comparison_rows if not row["doc_count"]]
    print(f"wrote {output_dir / 'hitrate_comparison.csv'}")
    print(f"wrote {output_dir / 'hitrate_comparison.png'}")
    print(f"wrote {output_dir / 'adaptive_index_distribution.csv'}")
    print(f"wrote {output_dir / 'adaptive_index_distribution.png'}")
    if missing:
        print("missing: " + ", ".join(missing))


if __name__ == "__main__":
    main()
