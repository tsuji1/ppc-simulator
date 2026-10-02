# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.7", "pymongo>=4.10"]
# ///
"""Plot the WIDE non-anon two-cache power heatmap from computed DB fields."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pymongo import MongoClient

CAPACITIES = (1024, 2048, 4096, 8192)
L2_REFBITS = tuple(range(23, 9, -1))


def arguments() -> argparse.Namespace:
    default_out = Path(__file__).resolve().parent / "reports" / "mp2_power_nonanon_wide_20260327"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017/"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--trace-file-name", default="2026-03-27.pcap")
    parser.add_argument("--rule-file-name", default="rib.20260327.0600.unique.rule")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--throughput", type=float, default=1024.0)
    parser.add_argument("--dram-pj", type=int, default=4000)
    parser.add_argument("--output-dir", type=Path, default=default_out)
    return parser.parse_args()


def cap(value: int) -> str:
    return f"{value // 1024}K"


def latest_target_docs(collection, args: argparse.Namespace) -> dict[tuple[int, int, int], dict]:
    query = {
        "trace_file_name": args.trace_file_name,
        "rule_file_name": args.rule_file_name,
        "simulator_result.type": "MultiLayerCacheExclusive",
        "simulator_result.processed": args.processed,
    }
    docs = list(collection.find(query))
    latest: dict[str, dict] = {}
    for doc in sorted(docs, key=lambda item: item.get("timestamp"), reverse=True):
        parameter = doc.get("simulator_result", {}).get("parameter", {})
        latest.setdefault(json.dumps(parameter, sort_keys=True, default=str), doc)

    result = {}
    for doc in latest.values():
        layers = doc.get("simulator_result", {}).get("parameter", {}).get("cachelayers", [])
        if len(layers) != 2:
            continue
        refs = tuple(int(layer.get("refbits", 0)) for layer in layers)
        sizes = tuple(int(layer.get("size", 0)) for layer in layers)
        ways = tuple(int(layer.get("way", 0)) for layer in layers)
        if not (
            refs[0] == 24
            and refs[1] in L2_REFBITS
            and all(size in CAPACITIES for size in sizes)
            and ways == (8, 8)
        ):
            continue
        result[(refs[1], sizes[0], sizes[1])] = doc
    return result


def extract(doc: dict | None, args: argparse.Namespace) -> tuple[str, float, float, float]:
    if doc is None:
        return "missing", math.nan, math.nan, math.nan
    throughput = float(doc.get("throughput_series", 0) or 0)
    hitrate = float(doc.get("simulator_result", {}).get("hitrate", 0) or 0) * 100
    power = doc.get("power_series", {}).get(str(args.dram_pj), {}).get("total_power")
    if power is None:
        return "power_missing", math.nan, throughput, hitrate
    if throughput + 1e-9 < args.throughput:
        return "below_threshold", float(power), throughput, hitrate
    return "eligible", float(power), throughput, hitrate


def main() -> None:
    args = arguments()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        docs = latest_target_docs(client[args.db][args.collection], args)
    finally:
        client.close()

    columns = [(left, right) for left in CAPACITIES for right in CAPACITIES]
    matrix, csv_rows, eligible = [], [], []
    for refbits in L2_REFBITS:
        row = []
        for l1, l2 in columns:
            status, power, throughput, hitrate = extract(docs.get((refbits, l1, l2)), args)
            row.append(power if status == "eligible" else math.nan)
            csv_rows.append({"l1_refbits": 24, "l2_refbits": refbits, "l1_capacity": l1,
                             "l2_capacity": l2, "status": status, "power_mw": "" if math.isnan(power) else power,
                             "throughput_gbps": "" if math.isnan(throughput) else throughput,
                             "hitrate_percent": "" if math.isnan(hitrate) else hitrate})
            if status == "eligible":
                eligible.append((power, refbits, l1, l2, hitrate))
        matrix.append(row)

    csv_path = args.output_dir / "power_heatmap_points.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)

    fig, ax = plt.subplots(figsize=(17, 9), constrained_layout=True)
    cmap = plt.colormaps["viridis_r"].copy()
    cmap.set_bad("#eeeeee")
    values = [item[0] for item in eligible]
    image = ax.imshow(matrix, aspect="auto", cmap=cmap, vmin=min(values), vmax=max(values))
    winner = min(eligible)
    for yi, refbits in enumerate(L2_REFBITS):
        for xi, (l1, l2) in enumerate(columns):
            status, power, _, _ = extract(docs.get((refbits, l1, l2)), args)
            if status != "eligible":
                continue
            shade = (power - min(values)) / max(max(values) - min(values), 1e-12)
            ax.text(xi, yi, f"{power:.0f}", ha="center", va="center", fontsize=7,
                    color="white" if shade > 0.55 else "#111111")
            if (power, refbits, l1, l2) == winner[:4]:
                ax.add_patch(Rectangle((xi - .48, yi - .48), .96, .96, fill=False,
                                       edgecolor="#ff2d2d", linewidth=2.4))
    ax.set_xticks(range(len(columns)), [f"{cap(a)} {cap(b)}" for a, b in columns], rotation=45, ha="right")
    ax.set_yticks(range(len(L2_REFBITS)), [f"/{value}" for value in L2_REFBITS])
    ax.set_xlabel("L1 / L2 capacity")
    ax.set_ylabel("L2 refbits")
    ax.set_title(
        f"WIDE non-anon 2026-03-27: 2 Cache power at throughput ≥ {args.throughput:g} Gbps\n"
        f"Cell = mW; red outline = best; available {len(docs)}/{len(L2_REFBITS) * len(columns)} configurations",
        fontsize=15,
        weight="bold",
    )
    fig.colorbar(image, ax=ax, label="Power (mW)", shrink=.82)
    png_path = args.output_dir / "power_heatmap.png"
    fig.savefig(png_path, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"available={len(docs)}/{len(L2_REFBITS) * len(columns)} eligible={len(eligible)}")
    print(f"best={winner[0]:.3f}mW /24 /{winner[1]} {cap(winner[2])} {cap(winner[3])} hitrate={winner[4]:.4f}%")
    print(png_path)
    print(csv_path)


if __name__ == "__main__":
    main()
