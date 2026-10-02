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
EPOCH_LENGTHS = (256, 1024, 4096)


def parse_args():
    parser = argparse.ArgumentParser(description="Compare epoch adaptive UnifiedCache index policies.")
    parser.add_argument("--mongo-uri", default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--rule", default="rib.20260327.0600.unique.rule")
    parser.add_argument("--trace", default="202603271400.pcap")
    parser.add_argument("--processed", type=int, default=100000)
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--capacities", default="1024,4096,16384")
    parser.add_argument("--output-dir", default="scripts/reports/unified_epoch_adaptive_smoke")
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser.parse_args()


def policy_key(parameter):
    policy = parameter.get("indexpolicy", "fixed")
    epoch_length = int(parameter.get("adaptiveepochlength", 0))
    return policy, int(parameter.get("cacheindextype", 0)), int(parameter["size"]), epoch_length


def latest_documents(collection, query, projection):
    latest = {}
    counts = {}
    for doc in collection.find(query, projection):
        key = policy_key(doc["simulator_result"]["parameter"])
        counts[key] = counts.get(key, 0) + 1
        if key not in latest or doc.get("timestamp") > latest[key].get("timestamp"):
            latest[key] = doc
    return latest, counts


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def padded_counts(value):
    counts = [int(v) for v in (value or [])]
    return (counts + [0] * 32)[:32]


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
            {"simulator_result.parameter.indexpolicy": "epoch-most-frequent-prefix",
             "simulator_result.parameter.adaptiveepochlength": {"$in": list(EPOCH_LENGTHS)}},
            {"simulator_result.parameter.indexpolicy": "last-inserted-prefix"},
            {"simulator_result.parameter.indexpolicy": {"$exists": False},
             "simulator_result.parameter.cacheindextype": {"$in": list(FIXED_INDEXES)}},
            {"simulator_result.parameter.indexpolicy": "fixed",
             "simulator_result.parameter.cacheindextype": {"$in": list(FIXED_INDEXES)}},
        ],
    }
    projection = {
        "timestamp": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter": 1,
        "simulator_result.statdetail.adaptiveswitchcount": 1,
        "simulator_result.statdetail.adaptivefinalindexlength": 1,
        "simulator_result.statdetail.adaptiveepochaccesscount": 1,
        "simulator_result.statdetail.adaptiveepochdecisioncount": 1,
        "simulator_result.statdetail.adaptivecompletedepochs": 1,
    }
    latest, doc_counts = latest_documents(collection, query, projection)

    definitions = [("fixed", length, 0, f"fixed /{length}") for length in FIXED_INDEXES]
    definitions.append(("last-inserted-prefix", 18, 0, "immediate"))
    definitions.extend(("epoch-most-frequent-prefix", 18, epoch, f"epoch {epoch}") for epoch in EPOCH_LENGTHS)

    comparison_rows = []
    series = {label: [] for _, _, _, label in definitions}
    for capacity in capacities:
        for policy, index_type, epoch_length, label in definitions:
            key = (policy, index_type, capacity, epoch_length)
            doc = latest.get(key)
            hitrate = None if doc is None else float(doc["simulator_result"]["hitrate"]) * 100.0
            series[label].append(hitrate)
            comparison_rows.append({
                "capacity": capacity,
                "capacity_exp": capacity.bit_length() - 1,
                "policy": policy,
                "epoch_length": epoch_length,
                "label": label,
                "hitrate_percent": "" if hitrate is None else f"{hitrate:.6f}",
                "doc_count": doc_counts.get(key, 0),
                "timestamp": "" if doc is None else doc.get("timestamp", ""),
            })
    write_csv(output_dir / "hitrate_comparison.csv", comparison_rows,
              ["capacity", "capacity_exp", "policy", "epoch_length", "label", "hitrate_percent", "doc_count", "timestamp"])

    xlabels = [f"2^{capacity.bit_length() - 1}" for capacity in capacities]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for label, values in series.items():
        points = [(i, v) for i, v in enumerate(values) if v is not None]
        if points:
            is_adaptive = label.startswith("epoch") or label == "immediate"
            ax.plot([p[0] for p in points], [p[1] for p in points], marker="o",
                    linewidth=2.5 if is_adaptive else 1.1, label=label)
    ax.set_xticks(range(len(capacities)), xlabels)
    ax.set_xlabel("cache capacity")
    ax.set_ylabel("hitrate (%)")
    ax.set_title("UnifiedCache epoch adaptive index comparison")
    ax.grid(alpha=0.25)
    ax.legend(ncol=3)
    fig.tight_layout()
    fig.savefig(output_dir / "hitrate_comparison.png", dpi=180)
    plt.close(fig)

    behavior_rows = []
    for capacity in capacities:
        for epoch_length in EPOCH_LENGTHS:
            key = ("epoch-most-frequent-prefix", 18, capacity, epoch_length)
            doc = latest.get(key)
            if doc is None:
                continue
            stat = doc["simulator_result"].get("statdetail", {})
            decisions = padded_counts(stat.get("adaptiveepochdecisioncount"))
            for length in range(6, 25):
                behavior_rows.append({
                    "capacity": capacity,
                    "capacity_exp": capacity.bit_length() - 1,
                    "epoch_length": epoch_length,
                    "selected_index_length": length,
                    "decision_count": decisions[length],
                    "switch_count": int(stat.get("adaptiveswitchcount", 0)),
                    "completed_epochs": int(stat.get("adaptivecompletedepochs", 0)),
                    "current_epoch_accesses": int(stat.get("adaptiveepochaccesscount", 0)),
                    "final_index_length": int(stat.get("adaptivefinalindexlength", 0)),
                })
    write_csv(output_dir / "epoch_behavior.csv", behavior_rows,
              ["capacity", "capacity_exp", "epoch_length", "selected_index_length", "decision_count",
               "switch_count", "completed_epochs", "current_epoch_accesses", "final_index_length"])

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for capacity in capacities:
        rows = [r for r in behavior_rows if r["capacity"] == capacity]
        switches = []
        dominant = []
        for epoch_length in EPOCH_LENGTHS:
            group = [r for r in rows if r["epoch_length"] == epoch_length]
            switches.append(group[0]["switch_count"] if group else 0)
            dominant.append(max(group, key=lambda r: r["decision_count"])["selected_index_length"] if group else 0)
        label = f"2^{capacity.bit_length() - 1}"
        axes[0].plot(EPOCH_LENGTHS, switches, marker="o", label=label)
        axes[1].plot(EPOCH_LENGTHS, dominant, marker="o", label=label)
    axes[0].set_ylabel("index switches")
    axes[1].set_ylabel("most selected index length")
    for ax in axes:
        ax.set_xscale("log", base=2)
        ax.set_xticks(EPOCH_LENGTHS, [str(v) for v in EPOCH_LENGTHS])
        ax.set_xlabel("epoch length (accesses)")
        ax.grid(alpha=0.25)
        ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "epoch_behavior.png", dpi=180)
    plt.close(fig)

    missing = [f"{r['label']}@2^{r['capacity_exp']}" for r in comparison_rows if not r["doc_count"]]
    for name in ("hitrate_comparison.csv", "hitrate_comparison.png", "epoch_behavior.csv", "epoch_behavior.png"):
        print(f"wrote {output_dir / name}")
    if missing:
        print("missing: " + ", ".join(missing))


if __name__ == "__main__":
    main()
