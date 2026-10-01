# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.7", "pymongo>=4.10"]
# ///
"""Plot the power delta of 3 Cache against the best 2 Cache at each L2 prefix."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from pymongo import MongoClient

CAPS = (1024, 2048, 4096, 8192)
L2S = tuple(range(23, 10, -1))
L3S = tuple(range(22, 9, -1))


def cap(values: tuple[int, ...]) -> str:
    return " ".join(f"{value // 1024}K" for value in values)


def args() -> argparse.Namespace:
    default = Path(__file__).resolve().parent / "reports" / "mp2_vs_mp3_power_nonanon_wide_20260327"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017/"))
    parser.add_argument("--trace-file-name", default="2026-03-27.pcap")
    parser.add_argument("--rule-file-name", default="rib.20260327.0600.unique.rule")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--throughput", type=float, default=1024.0)
    parser.add_argument("--dram-pj", type=int, default=4000)
    parser.add_argument("--output-dir", type=Path, default=default)
    return parser.parse_args()


def load(a: argparse.Namespace) -> list[dict]:
    client = MongoClient(a.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        query = {"trace_file_name": a.trace_file_name, "rule_file_name": a.rule_file_name,
                 "simulator_result.type": "MultiLayerCacheExclusive",
                 "simulator_result.processed": a.processed}
        docs = list(client["db"]["simulator_results"].find(query))
    finally:
        client.close()
    latest = {}
    for doc in sorted(docs, key=lambda item: item.get("timestamp"), reverse=True):
        parameter = doc.get("simulator_result", {}).get("parameter", {})
        latest.setdefault(json.dumps(parameter, sort_keys=True, default=str), doc)
    return list(latest.values())


def candidate(doc: dict, layers_count: int, a: argparse.Namespace):
    sim = doc.get("simulator_result", {})
    layers = sim.get("parameter", {}).get("cachelayers", [])
    if len(layers) != layers_count:
        return None
    refs = tuple(int(x.get("refbits", 0)) for x in layers)
    sizes = tuple(int(x.get("size", 0)) for x in layers)
    ways = tuple(int(x.get("way", 0)) for x in layers)
    if refs[0] != 24 or any(x not in CAPS for x in sizes) or any(x != 8 for x in ways):
        return None
    if layers_count == 2 and not 23 >= refs[1] >= 10:
        return None
    if layers_count == 3 and not 23 >= refs[1] > refs[2] >= 10:
        return None
    throughput = float(doc.get("throughput_series", 0) or 0)
    power = doc.get("power_series", {}).get(str(a.dram_pj), {}).get("total_power")
    if power is None or throughput + 1e-9 < a.throughput:
        return None
    return refs, sizes, float(power)


def main() -> None:
    a = args()
    docs = load(a)
    best2, best3 = {}, {}
    count2 = count3 = 0
    for doc in docs:
        point = candidate(doc, 2, a)
        if point:
            count2 += 1
            refs, sizes, power = point
            if refs[1] not in best2 or power < best2[refs[1]][0]:
                best2[refs[1]] = (power, sizes)
        point = candidate(doc, 3, a)
        if point:
            count3 += 1
            refs, sizes, power = point
            key = (refs[1], refs[2])
            if key not in best3 or power < best3[key][0]:
                best3[key] = (power, sizes)

    matrix = []
    deltas = []
    for l3 in L3S:
        row = []
        for l2 in L2S:
            if l3 >= l2 or l2 not in best2 or (l2, l3) not in best3:
                row.append(math.nan)
            else:
                delta = best3[(l2, l3)][0] - best2[l2][0]
                row.append(delta)
                deltas.append(delta)
        matrix.append(row)

    limit = max(abs(min(deltas)), abs(max(deltas)))
    fig, ax = plt.subplots(figsize=(18, 10), constrained_layout=True)
    cmap = plt.colormaps["RdBu_r"].copy()
    cmap.set_bad("#eeeeee")
    image = ax.imshow(matrix, aspect="equal", cmap=cmap, norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit))
    for yi, l3 in enumerate(L3S):
        for xi, l2 in enumerate(L2S):
            value = matrix[yi][xi]
            if math.isnan(value):
                continue
            p3, caps3 = best3[(l2, l3)]
            color = "white" if abs(value) > limit * .52 else "#111111"
            ax.text(xi, yi, f"{value:+.0f} mW\n3C {cap(caps3)}", ha="center", va="center",
                    fontsize=6.2, color=color, linespacing=1.08)
    xlabels = []
    for l2 in L2S:
        if l2 in best2:
            power, sizes = best2[l2]
            xlabels.append(f"/{l2}\n2C {power:.0f}mW\n{cap(sizes)}")
        else:
            xlabels.append(f"/{l2}\n2C —")
    ax.set_xticks(range(len(L2S)), xlabels, fontsize=8)
    ax.set_yticks(range(len(L3S)), [f"/{value}" for value in L3S])
    ax.set_xlabel("Layer 2 refbits and best 2 Cache baseline")
    ax.set_ylabel("Layer 3 refbits")
    ax.set_title(f"WIDE non-anon: 3 Cache power minus best 2 Cache power (≥ {a.throughput:g} Gbps)\n"
                 "Blue = 3 Cache lower power; red = 2 Cache lower power; cell shows 3 Cache capacity",
                 fontsize=15, weight="bold")
    fig.colorbar(image, ax=ax, shrink=.8, label="3 Cache − 2 Cache power (mW)")
    a.output_dir.mkdir(parents=True, exist_ok=True)
    path = a.output_dir / "power_delta_heatmap.png"
    fig.savefig(path, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"2cache eligible points={count2} prefixes={len(best2)}")
    print(f"3cache eligible points={count3} refbit_pairs={len(best3)}")
    print(f"comparison cells={len(deltas)} delta_min={min(deltas):.3f} delta_max={max(deltas):.3f}")
    print(path)


if __name__ == "__main__":
    main()
