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
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


PREFIX_HASH_DIRECT = [16, 18, 20, 24, 116, 118, 120, 124]
WINDOW_INDEXES = [20816, 21212, 21608, 30816, 31212, 31608, 40816, 41212, 41608]
ALL_INDEXES = PREFIX_HASH_DIRECT + WINDOW_INDEXES

DATASETS = {
    "wide-20260327": {
        "rule": "rib.20260327.0600.unique.rule",
        "trace": "2026-03-27.pcap",
        "start_exp": 6,
        "end_exp": 14,
    },
    "chicago": {
        "rule": "route-views.chicago.rib.20160628.1400.unique.rule",
        "trace": "equinix-chicago.dirB.20140320-140100.UTC.anon.pcap",
        "start_exp": 10,
        "end_exp": 15,
    },
    "sanjose": {
        "rule": "route-views.isc.rib.20140320.1400.unique.rule",
        "trace": "equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap",
        "start_exp": 10,
        "end_exp": 15,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot UnifiedCache index hitrate comparisons from MongoDB."
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI (default: DATABASE_URL or mongodb://localhost:27017/)",
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/unified_index_graphs",
        help="Output directory.",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser.parse_args()


def index_label(index_type: int) -> str:
    if 16 <= index_type <= 24:
        return f"hash /{index_type}"
    if 100 <= index_type <= 124:
        return f"direct /{index_type - 100}"
    if 20000 <= index_type < 30000:
        start, width = divmod(index_type - 20000, 100)
        return f"direct b{start}-{start + width - 1}"
    if 30000 <= index_type < 40000:
        start, width = divmod(index_type - 30000, 100)
        return f"xor b{start}-{start + width - 1}"
    if 40000 <= index_type < 50000:
        start, width = divmod(index_type - 40000, 100)
        return f"crc b{start}-{start + width - 1}"
    return str(index_type)


def expected_capacities(start_exp: int, end_exp: int) -> List[int]:
    return [1 << exp for exp in range(start_exp, end_exp + 1)]


def fetch_latest(
    collection,
    rule: str,
    trace: str,
    way: int,
    index_types: List[int],
    capacities: List[int],
) -> Tuple[Dict[Tuple[int, int], float], Dict[Tuple[int, int], int]]:
    query = {
        "simulator_result.type": "UnifiedCache",
        "simulator_result.parameter.way": way,
        "simulator_result.parameter.cacheindextype": {"$in": index_types},
        "simulator_result.parameter.size": {"$in": capacities},
        "rule_file_name": rule,
        "trace_file_name": trace,
    }
    projection = {
        "_id": 0,
        "timestamp": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.size": 1,
        "simulator_result.parameter.cacheindextype": 1,
    }

    latest_docs: Dict[Tuple[int, int], Dict[str, object]] = {}
    doc_counts: Dict[Tuple[int, int], int] = {}
    for doc in collection.find(query, projection):
        sim = doc["simulator_result"]
        param = sim["parameter"]
        key = (int(param["cacheindextype"]), int(param["size"]))
        doc_counts[key] = doc_counts.get(key, 0) + 1
        if key not in latest_docs or doc["timestamp"] > latest_docs[key]["timestamp"]:
            latest_docs[key] = doc

    values = {
        key: float(doc["simulator_result"]["hitrate"]) * 100.0
        for key, doc in latest_docs.items()
        if doc["simulator_result"].get("hitrate") is not None
    }
    return values, doc_counts


def write_wide_csv(
    path: Path,
    values: Dict[Tuple[int, int], float],
    index_types: List[int],
    capacities: List[int],
) -> None:
    fields = ["cache_index_type", "index_label"] + [f"2^{capacity.bit_length() - 1}" for capacity in capacities]
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for index_type in index_types:
            row = {"cache_index_type": index_type, "index_label": index_label(index_type)}
            for capacity in capacities:
                value = values.get((index_type, capacity))
                row[f"2^{capacity.bit_length() - 1}"] = "" if value is None else f"{value:.6f}"
            writer.writerow(row)


def line_style(index_type: int) -> Dict[str, object]:
    if 16 <= index_type <= 24:
        return {"linestyle": "-", "marker": "o"}
    if 100 <= index_type <= 124:
        return {"linestyle": "--", "marker": "s"}
    if 20000 <= index_type < 30000:
        return {"linestyle": "-", "marker": "^"}
    if 30000 <= index_type < 40000:
        return {"linestyle": "--", "marker": "D"}
    return {"linestyle": ":", "marker": "x"}


def plot_lines(
    path: Path,
    title: str,
    values: Dict[Tuple[int, int], float],
    index_types: List[int],
    capacities: List[int],
) -> None:
    fig, ax = plt.subplots(figsize=(11, 6.5))
    x = [capacity.bit_length() - 1 for capacity in capacities]
    for index_type in index_types:
        y = [values.get((index_type, capacity)) for capacity in capacities]
        if all(value is None for value in y):
            continue
        ax.plot(
            x,
            y,
            linewidth=2,
            label=index_label(index_type),
            **line_style(index_type),
        )
    ax.set_title(title)
    ax.set_xlabel("capacity")
    ax.set_ylabel("hitrate (%)")
    ax.set_ylim(bottom=50)
    ax.set_xticks(x, [f"2^{value}" for value in x])
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_best_across_datasets(path: Path, best_rows: List[Dict[str, object]]) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    by_dataset: Dict[str, List[Dict[str, object]]] = {}
    for row in best_rows:
        by_dataset.setdefault(str(row["dataset"]), []).append(row)
    for dataset, rows in by_dataset.items():
        rows.sort(key=lambda row: int(row["capacity_exp"]))
        ax.plot(
            [int(row["capacity_exp"]) for row in rows],
            [float(row["hitrate_percent"]) for row in rows],
            marker="o",
            linewidth=2,
            label=dataset,
        )
    ax.set_title("Best hitrate by capacity")
    ax.set_xlabel("capacity")
    ax.set_ylabel("best hitrate (%)")
    all_exps = sorted({int(row["capacity_exp"]) for row in best_rows})
    ax.set_xticks(all_exps, [f"2^{exp}" for exp in all_exps])
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    collection = client[args.db][args.collection]

    best_rows: List[Dict[str, object]] = []
    for dataset, config in DATASETS.items():
        capacities = expected_capacities(config["start_exp"], config["end_exp"])
        index_types = PREFIX_HASH_DIRECT
        values, doc_counts = fetch_latest(
            collection,
            config["rule"],
            config["trace"],
            args.way,
            index_types,
            capacities,
        )
        write_wide_csv(outdir / f"{dataset}_hash_direct_hitrate.csv", values, index_types, capacities)
        plot_lines(
            outdir / f"{dataset}_hash_direct_hitrate.png",
            f"{dataset}: hash vs direct prefix index",
            values,
            index_types,
            capacities,
        )
        with (outdir / f"{dataset}_duplicates.csv").open("w", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(["cache_index_type", "capacity", "doc_count"])
            for (index_type, capacity), count in sorted(doc_counts.items()):
                if count > 1:
                    writer.writerow([index_type, capacity, count])
        all_values, _ = fetch_latest(
            collection,
            config["rule"],
            config["trace"],
            args.way,
            ALL_INDEXES,
            capacities,
        )
        write_wide_csv(outdir / f"{dataset}_all_index_hitrate.csv", all_values, ALL_INDEXES, capacities)
        window_values, _ = fetch_latest(
            collection,
            config["rule"],
            config["trace"],
            args.way,
            WINDOW_INDEXES,
            capacities,
        )
        write_wide_csv(outdir / f"{dataset}_window_hitrate.csv", window_values, WINDOW_INDEXES, capacities)
        plot_lines(
            outdir / f"{dataset}_window_hitrate.png",
            f"{dataset}: direct/xor/crc window index",
            window_values,
            WINDOW_INDEXES,
            capacities,
        )

        for capacity in capacities:
            best = None
            for index_type in ALL_INDEXES:
                value = all_values.get((index_type, capacity))
                if value is None:
                    continue
                if best is None or value > best[1]:
                    best = (index_type, value)
            if best is not None:
                best_rows.append(
                    {
                        "dataset": dataset,
                        "capacity": capacity,
                        "capacity_exp": capacity.bit_length() - 1,
                        "best_cache_index_type": best[0],
                        "best_index_label": index_label(best[0]),
                        "hitrate_percent": f"{best[1]:.6f}",
                    }
                )

    best_csv = outdir / "best_hitrate_by_dataset.csv"
    with best_csv.open("w", newline="") as fp:
        fields = [
            "dataset",
            "capacity",
            "capacity_exp",
            "best_cache_index_type",
            "best_index_label",
            "hitrate_percent",
        ]
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(best_rows)
    plot_best_across_datasets(outdir / "best_hitrate_by_dataset.png", best_rows)

    print(f"wrote {outdir}")


if __name__ == "__main__":
    main()
