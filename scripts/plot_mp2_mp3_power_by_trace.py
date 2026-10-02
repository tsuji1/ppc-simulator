# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.7", "pymongo>=4.10"]
# ///
"""Create one MP3 + MP2 optimized-power heatmap PNG per trace."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle
from pymongo import MongoClient

CAPS = {1024, 2048, 4096, 8192}
MIN_REFBITS = 10
LAYER_RE = re.compile(r"(\d+)@(\d+)w(\d+)")


@dataclass(frozen=True)
class Point:
    layers: int
    refs: tuple[int, ...]
    caps: tuple[int, ...]
    power: float
    throughput: float
    hitrate: float


TRACE_FILES = (
    ("chicago_anon", "Chicago anon", "chicago", 16, 10),
    ("wide_anon_20260327", "WIDE anon 2026-03-27", "wide", 16, 10),
    ("nyc_anon", "NYC anon", "nyc", 16, 10),
)


def arguments() -> argparse.Namespace:
    base = Path(__file__).resolve().parent / "reports" / "mp3_sweep_results"
    output = Path(__file__).resolve().parent / "reports" / "mp2_mp3_power_by_trace"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--power-report-dir", type=Path, default=base)
    parser.add_argument("--output-dir", type=Path, default=output)
    parser.add_argument("--throughput", type=float, default=1024.0)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017/"))
    parser.add_argument("--skip-nonanon", action="store_true")
    parser.add_argument(
        "--min-refbits",
        type=int,
        choices=range(10, 17),
        default=None,
        help="Override the displayed minimum refbits for both 2 Cache and 3 Cache.",
    )
    return parser.parse_args()


def cap_text(values: tuple[int, ...]) -> str:
    return " ".join(f"{value // 1024}K" for value in values)


def accepted(refs: tuple[int, ...], caps: tuple[int, ...], ways: tuple[int, ...]) -> bool:
    if refs[0] != 24 or any(value not in CAPS for value in caps) or any(value != 8 for value in ways):
        return False
    if len(refs) == 2:
        return 23 >= refs[1] >= MIN_REFBITS
    if len(refs) == 3:
        return 23 >= refs[1] > refs[2] >= MIN_REFBITS
    return False


def read_csv_points(path: Path, threshold: float) -> list[Point]:
    result = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["type"] != "MultiLayerCacheExclusive":
                continue
            parsed = tuple(tuple(map(int, item)) for item in LAYER_RE.findall(row["tag_desc"]))
            if len(parsed) not in (2, 3):
                continue
            refs = tuple(item[0] for item in parsed)
            caps = tuple(item[1] for item in parsed)
            ways = tuple(item[2] for item in parsed)
            throughput = float(row["throughput_gbps"])
            if not accepted(refs, caps, ways) or throughput + 1e-9 < threshold:
                continue
            result.append(Point(len(refs), refs, caps, float(row["power_mw"]), throughput,
                                float(row["hitrate"]) * 100))
    return result


def read_nonanon_points(uri: str, threshold: float) -> list[Point]:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        query = {"trace_file_name": "2026-03-27.pcap",
                 "rule_file_name": "rib.20260327.0600.unique.rule",
                 "simulator_result.type": "MultiLayerCacheExclusive",
                 "simulator_result.processed": 10_000_000}
        docs = list(client["db"]["simulator_results"].find(query))
    finally:
        client.close()
    latest = {}
    for doc in sorted(docs, key=lambda item: item.get("timestamp"), reverse=True):
        parameter = doc.get("simulator_result", {}).get("parameter", {})
        latest.setdefault(json.dumps(parameter, sort_keys=True, default=str), doc)
    result = []
    for doc in latest.values():
        sim = doc.get("simulator_result", {})
        layers = sim.get("parameter", {}).get("cachelayers", [])
        if len(layers) not in (2, 3):
            continue
        refs = tuple(int(item.get("refbits", 0)) for item in layers)
        caps = tuple(int(item.get("size", 0)) for item in layers)
        ways = tuple(int(item.get("way", 0)) for item in layers)
        throughput = float(doc.get("throughput_series", 0) or 0)
        power = doc.get("power_series", {}).get("4000", {}).get("total_power")
        if power is None or throughput + 1e-9 < threshold or not accepted(refs, caps, ways):
            continue
        result.append(Point(len(refs), refs, caps, float(power), throughput,
                            float(sim.get("hitrate", 0) or 0) * 100))
    return result


def choose(points: list[Point]) -> tuple[dict[int, Point], dict[tuple[int, int], Point]]:
    mp2, mp3 = {}, {}
    for point in points:
        key = point.refs[1] if point.layers == 2 else (point.refs[1], point.refs[2])
        target = mp2 if point.layers == 2 else mp3
        if key not in target or point.power < target[key].power:
            target[key] = point
    return mp2, mp3


def text_color(value: float, low: float, high: float) -> str:
    shade = (value - low) / max(high - low, 1e-12)
    return "white" if shade > .55 else "#111111"


def plot_trace(
    path: Path,
    label: str,
    points: list[Point],
    threshold: float,
    mp2_min_refbits: int,
    mp3_min_refbits: int,
) -> list[dict[str, object]]:
    mp2, mp3 = choose(points)
    mp2_refs = tuple(range(23, mp2_min_refbits - 1, -1))
    mp3_l2s = tuple(range(23, mp3_min_refbits, -1))
    mp3_l3s = tuple(range(22, mp3_min_refbits - 1, -1))
    mp2 = {ref: point for ref, point in mp2.items() if ref in mp2_refs}
    mp3 = {key: point for key, point in mp3.items() if key[0] in mp3_l2s and key[1] in mp3_l3s}
    values = [point.power for point in mp2.values()] + [point.power for point in mp3.values()]
    low, high = min(values), max(values)
    cmap = plt.colormaps["viridis_r"].copy()
    cmap.set_bad("#eeeeee")
    wide_grid = mp3_min_refbits <= 10
    fig = plt.figure(figsize=(24, 15) if wide_grid else (20, 12), constrained_layout=True)
    grid = GridSpec(1, 3, figure=fig, width_ratios=(7.4, 1.45, .28))
    ax3, ax2, cax = fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1]), fig.add_subplot(grid[0, 2])

    matrix3 = [[mp3[(l2, l3)].power if (l2, l3) in mp3 else math.nan for l2 in mp3_l2s] for l3 in mp3_l3s]
    image = ax3.imshow(matrix3, cmap=cmap, vmin=low, vmax=high, aspect="equal")
    best3 = min(mp3.values(), key=lambda point: point.power) if mp3 else None
    for yi, l3 in enumerate(mp3_l3s):
        for xi, l2 in enumerate(mp3_l2s):
            point = mp3.get((l2, l3))
            if point is None:
                continue
            ax3.text(xi, yi, f"{point.power:.0f} mW\n{cap_text(point.caps)}", ha="center", va="center",
                     fontsize=8.8 if wide_grid else 14.0, color=text_color(point.power, low, high),
                     weight="bold", linespacing=1.08)
            if point == best3:
                ax3.add_patch(Rectangle((xi-.48, yi-.48), .96, .96, fill=False,
                                        edgecolor="#ff2d2d", linewidth=2.4))
    ax3.set_xticks(range(len(mp3_l2s)), [f"/{value}" for value in mp3_l2s], fontsize=11)
    ax3.set_yticks(range(len(mp3_l3s)), [f"/{value}" for value in mp3_l3s], fontsize=11)
    ax3.set_xlabel("3 Cache: Layer 2 refbits")
    ax3.set_ylabel("3 Cache: Layer 3 refbits")
    ax3.set_title("3 Cache — capacity-optimized per refbits pair", weight="bold")

    matrix2 = [[mp2[ref].power] if ref in mp2 else [math.nan] for ref in mp2_refs]
    ax2.imshow(matrix2, cmap=cmap, vmin=low, vmax=high, aspect="auto")
    best2 = min(mp2.values(), key=lambda point: point.power) if mp2 else None
    for yi, ref in enumerate(mp2_refs):
        point = mp2.get(ref)
        if point is None:
            ax2.text(0, yi, "—", ha="center", va="center", color="#777777")
            continue
        ax2.text(0, yi, f"{point.power:.0f} mW\n{cap_text(point.caps)}", ha="center", va="center",
                 fontsize=14.0, color=text_color(point.power, low, high), weight="bold", linespacing=1.08)
        if point == best2:
            ax2.add_patch(Rectangle((-.48, yi-.48), .96, .96, fill=False,
                                    edgecolor="#ff2d2d", linewidth=2.4))
    ax2.set_xticks([0], ["L1 / L2 capacity"])
    ax2.set_yticks(range(len(mp2_refs)), [f"/{value}" for value in mp2_refs], fontsize=11)
    ax2.set_ylabel("2 Cache: Layer 2 refbits")
    ax2.set_title("2 Cache\nL1=/24", weight="bold")
    fig.colorbar(image, cax=cax, label="Minimum power (mW)")
    fig.suptitle(f"{label}: optimized power at throughput ≥ {threshold:g} Gbps\n"
                 "Cell = minimum power and selected capacity; red outline = each cache-count minimum",
                 fontsize=16, weight="bold")
    fig.savefig(path, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    rows = []
    for ref, point in sorted(mp2.items(), reverse=True):
        rows.append({"cache_count": 2, "l2_refbits": ref, "l3_refbits": "", "power_mw": point.power,
                     "capacities": cap_text(point.caps), "hitrate_percent": point.hitrate})
    for (l2, l3), point in sorted(mp3.items(), reverse=True):
        rows.append({"cache_count": 3, "l2_refbits": l2, "l3_refbits": l3, "power_mw": point.power,
                     "capacities": cap_text(point.caps), "hitrate_percent": point.hitrate})
    expected_mp2 = len(mp2_refs)
    expected_mp3 = len(mp3_l2s) * (len(mp3_l2s) + 1) // 2
    print(f"{label}: MP2 cells={len(mp2)}/{expected_mp2} MP3 cells={len(mp3)}/{expected_mp3} "
          f"best2={best2.power if best2 else float('nan'):.3f} best3={best3.power if best3 else float('nan'):.3f}")
    return rows


def main() -> None:
    a = arguments()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for slug, label, source, mp2_min_refbits, mp3_min_refbits in TRACE_FILES:
        if a.min_refbits is not None:
            mp2_min_refbits = mp3_min_refbits = a.min_refbits
        points = read_csv_points(a.power_report_dir / "power_raw" / source / "comparison_detail.csv", a.throughput)
        rows = plot_trace(a.output_dir / f"{slug}_power_heatmaps.png", label, points, a.throughput,
                          mp2_min_refbits, mp3_min_refbits)
        all_rows.extend({"trace": slug, **row} for row in rows)
    if not a.skip_nonanon:
        label, slug = "WIDE non-anon 2026-03-27", "wide_nonanon_20260327"
        nonanon_min_refbits = a.min_refbits if a.min_refbits is not None else 16
        rows = plot_trace(a.output_dir / f"{slug}_power_heatmaps.png", label,
                          read_nonanon_points(a.mongo_uri, a.throughput), a.throughput,
                          nonanon_min_refbits, nonanon_min_refbits)
        all_rows.extend({"trace": slug, **row} for row in rows)
    with (a.output_dir / "selected_power_cells.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    print(a.output_dir)


if __name__ == "__main__":
    main()
