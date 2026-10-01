#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
"""Create a one-page overview of the MP3 cache sweep from its exported CSV."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle


TRACE_ORDER = ["chicago-anon", "wide-anon-20260327", "nyc-anon"]
TRACE_LABELS = {
    "chicago-anon": "Chicago anon",
    "wide-anon-20260327": "WIDE anon 2026-03",
    "nyc-anon": "NYC anon",
}
TRACE_COLORS = {
    "chicago-anon": "#2878B5",
    "wide-anon-20260327": "#2A9D64",
    "nyc-anon": "#D1495B",
}
MP_MIN_REFBITS = 10
EXPECTED_REFBITS_PAIRS = math.comb(24 - MP_MIN_REFBITS, 2)
EXPECTED_POINTS = 4**3 * EXPECTED_REFBITS_PAIRS
EXPECTED_VIL_POINTS = 60


@dataclass(frozen=True)
class Point:
    trace_key: str
    missrate: float
    total_capacity: int
    capacities: str
    l2_refbits: int
    l3_refbits: int


@dataclass(frozen=True)
class VILPoint:
    trace_key: str
    missrate: float
    capacity: int
    index_type: int
    index_label: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="scripts/reports/mp3_sweep_results/all_points.csv",
        help="CSV produced by plot_mp3_sweep_results.py",
    )
    parser.add_argument(
        "--output",
        default="scripts/reports/mp3_sweep_results/overview.png",
        help="Output PNG path",
    )
    parser.add_argument(
        "--vil-input",
        default="scripts/reports/mp3_sweep_results/vil_points.csv",
        help="VIL/UnifiedCache CSV produced by plot_mp3_sweep_results.py",
    )
    return parser.parse_args()


def load_points(path: Path) -> list[Point]:
    points: list[Point] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            refbits = [int(value) for value in row["refbits"].split("-")]
            if len(refbits) != 3 or refbits[0] != 24:
                continue
            points.append(
                Point(
                    trace_key=row["trace_key"],
                    missrate=float(row["missrate_percent"]),
                    total_capacity=int(row["total_capacity"]),
                    capacities=row["capacity_signature"],
                    l2_refbits=refbits[1],
                    l3_refbits=refbits[2],
                )
            )
    return points


def load_vil_points(path: Path | None) -> list[VILPoint]:
    if path is None or not path.exists():
        return []
    points: list[VILPoint] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            points.append(
                VILPoint(
                    trace_key=row["trace_key"],
                    missrate=float(row["missrate_percent"]),
                    capacity=int(row["capacity"]),
                    index_type=int(row["cache_index_type"]),
                    index_label=row["cache_index_label"],
                )
            )
    return points


def best_by_capacity(points: list[Point]) -> list[Point]:
    best: dict[int, Point] = {}
    for point in points:
        previous = best.get(point.total_capacity)
        if previous is None or point.missrate < previous.missrate:
            best[point.total_capacity] = point
    return [best[key] for key in sorted(best)]


def pareto(points: list[Point]) -> list[Point]:
    frontier: list[Point] = []
    current_best = math.inf
    for point in best_by_capacity(points):
        if point.missrate < current_best:
            frontier.append(point)
            current_best = point.missrate
    return frontier


def best_vil_by_capacity(points: list[VILPoint]) -> list[VILPoint]:
    best: dict[int, VILPoint] = {}
    for point in points:
        previous = best.get(point.capacity)
        if previous is None or point.missrate < previous.missrate:
            best[point.capacity] = point
    return [best[key] for key in sorted(best)]


def pareto_vil(points: list[VILPoint]) -> list[VILPoint]:
    frontier: list[VILPoint] = []
    current_best = math.inf
    for point in best_vil_by_capacity(points):
        if point.missrate < current_best:
            frontier.append(point)
            current_best = point.missrate
    return frontier


def set_capacity_ticks(ax: plt.Axes, points: list[Point]) -> None:
    totals = [point.total_capacity for point in points]
    if not totals:
        return
    lo, hi = min(totals), max(totals)
    ticks = [value for value in range(4096, hi + 4096, 4096) if value >= lo]
    ax.set_xlim(lo * 0.96, hi * 1.04)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{value // 1024}K" for value in ticks])


def set_comparison_capacity_ticks(ax: plt.Axes, mp_points: list[Point], vil_points: list[VILPoint]) -> None:
    values = [point.total_capacity for point in mp_points] + [point.capacity for point in vil_points]
    if not values:
        return
    lo, hi = min(values), max(values)
    ticks = [1024] + list(range(4096, hi + 4096, 4096))
    ticks = [value for value in ticks if lo <= value <= hi]
    ax.set_xlim(lo * 0.94, hi * 1.04)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{value // 1024}K" for value in ticks])


def incomplete_note(ax: plt.Axes, count: int) -> None:
    if count < EXPECTED_POINTS:
        ax.text(
            0.98,
            0.95,
            f"INCOMPLETE  {count}/{EXPECTED_POINTS}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            fontweight="bold",
            color="#A33A46",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "#FFF1F2", "edgecolor": "#DCA0A8"},
        )


def draw_best_curve(ax: plt.Axes, points: list[Point], vil_points: list[VILPoint], color: str) -> None:
    best = best_by_capacity(points)
    ax.plot(
        [point.total_capacity for point in best],
        [point.missrate for point in best],
        color=color,
        marker="o",
        markersize=4.5,
        linewidth=2.1,
        label="MP3 best",
    )
    if best:
        winner = min(best, key=lambda point: point.missrate)
        ax.scatter([winner.total_capacity], [winner.missrate], marker="*", s=120, color="#E6A700", edgecolor="#6A5200", zorder=5)
        ax.annotate(
            f"{winner.missrate:.4f}%\n{winner.capacities}",
            (winner.total_capacity, winner.missrate),
            xytext=(-8, 28),
            textcoords="offset points",
            fontsize=8,
            ha="right",
            va="bottom",
        )
    vil_best = best_vil_by_capacity(vil_points)
    if vil_best:
        ax.plot(
            [point.capacity for point in vil_best],
            [point.missrate for point in vil_best],
            color="#333333",
            marker="D",
            markersize=4.2,
            linewidth=1.9,
            linestyle="--",
            label="VIL best",
        )
        winner = min(vil_best, key=lambda point: point.missrate)
        ax.annotate(
            f"VIL {winner.missrate:.4f}%\n{winner.index_label} {winner.capacity // 1024}K",
            (winner.capacity, winner.missrate),
            xytext=(-8, 7),
            textcoords="offset points",
            fontsize=8,
            ha="right",
            va="bottom",
        )
    set_comparison_capacity_ticks(ax, points, vil_points)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.24)
    ax.set_xlabel("Total entries")
    ax.legend(loc="best", fontsize=8)


def draw_pareto(ax: plt.Axes, points: list[Point], vil_points: list[VILPoint], color: str) -> None:
    ax.scatter(
        [point.total_capacity for point in points],
        [point.missrate for point in points],
        s=8,
        alpha=0.14,
        color=color,
        linewidths=0,
        rasterized=True,
        label="MP3 all",
    )
    front = pareto(points)
    ax.plot(
        [point.total_capacity for point in front],
        [point.missrate for point in front],
        color=color,
        marker="o",
        markersize=4,
        linewidth=2.1,
        label="MP3 frontier",
    )
    if vil_points:
        ax.scatter(
            [point.capacity for point in vil_points],
            [point.missrate for point in vil_points],
            s=15,
            alpha=0.18,
            color="#333333",
            marker="D",
            linewidths=0,
            label="VIL all",
        )
        front_vil = pareto_vil(vil_points)
        ax.plot(
            [point.capacity for point in front_vil],
            [point.missrate for point in front_vil],
            color="#333333",
            marker="D",
            markersize=3.8,
            linewidth=1.9,
            linestyle="--",
            label="VIL frontier",
        )
    set_comparison_capacity_ticks(ax, points, vil_points)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.22)
    ax.set_xlabel("Total entries")
    ax.legend(loc="best", fontsize=7, ncols=2)


def draw_refbits_heatmap(ax: plt.Axes, points: list[Point]) -> None:
    l2_values = list(range(23, MP_MIN_REFBITS, -1))
    l3_values = list(range(22, MP_MIN_REFBITS - 1, -1))
    best: dict[tuple[int, int], Point] = {}
    for point in points:
        key = (point.l2_refbits, point.l3_refbits)
        previous = best.get(key)
        if previous is None or point.missrate < previous.missrate:
            best[key] = point

    finite = [point.missrate for point in best.values()]
    if not finite:
        ax.set_axis_off()
        return
    vmin, vmax = min(finite), max(finite)
    if math.isclose(vmin, vmax):
        vmax = vmin + max(0.01, abs(vmin) * 0.01)
    cmap = plt.get_cmap("viridis_r").copy()
    cmap.set_bad("#E8E8E8")
    matrix = []
    for l3 in l3_values:
        matrix.append([best.get((l2, l3), Point("", math.nan, 0, "", 0, 0)).missrate for l2 in l2_values])
    image = ax.imshow(matrix, aspect="equal", cmap=cmap, norm=Normalize(vmin=vmin, vmax=vmax))

    winner_key = min(best, key=lambda key: best[key].missrate)
    for row, l3 in enumerate(l3_values):
        for col, l2 in enumerate(l2_values):
            point = best.get((l2, l3))
            if point is None:
                continue
            if len(best) <= 3:
                label = f"{point.missrate:.3f}%"
            else:
                label = f"{point.missrate:.2f}"
            rgba = image.cmap(image.norm(point.missrate))
            luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            ax.text(col, row, label, ha="center", va="center", fontsize=5.8, color="black" if luminance > 0.56 else "white")
            if (l2, l3) == winner_key:
                ax.add_patch(Rectangle((col - 0.48, row - 0.48), 0.96, 0.96, fill=False, edgecolor="black", linewidth=2.2))

    ax.set_xticks(range(len(l2_values)))
    ax.set_xticklabels([f"/{value}" for value in l2_values])
    ax.set_yticks(range(len(l3_values)))
    ax.set_yticklabels([f"/{value}" for value in l3_values])
    ax.set_xlabel("L2 prefix (L1 is always /24)")
    ax.set_ylabel("L3 prefix")
    ax.set_xticks([value - 0.5 for value in range(1, len(l2_values))], minor=True)
    ax.set_yticks([value - 0.5 for value in range(1, len(l3_values))], minor=True)
    ax.grid(which="minor", color="white", linewidth=0.8, alpha=0.7)
    ax.tick_params(which="minor", bottom=False, left=False)
    cbar = ax.figure.colorbar(image, ax=ax, fraction=0.045, pad=0.025)
    cbar.set_label("Best miss rate (%)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)


def draw_vil_heatmap(ax: plt.Axes, points: list[VILPoint]) -> None:
    index_order = [(2, "IDEAL")] + [(value, f"/{value}") for value in range(16, 25)]
    capacities = sorted({point.capacity for point in points})
    point_map = {(point.index_type, point.capacity): point for point in points}
    finite = [point.missrate for point in points]
    if not finite or not capacities:
        ax.set_axis_off()
        return
    vmin, vmax = min(finite), max(finite)
    if math.isclose(vmin, vmax):
        vmax = vmin + max(0.01, abs(vmin) * 0.01)
    cmap = plt.get_cmap("viridis_r").copy()
    cmap.set_bad("#E8E8E8")
    matrix = [
        [point_map.get((index_type, capacity), VILPoint("", math.nan, 0, 0, "")).missrate for capacity in capacities]
        for index_type, _ in index_order
    ]
    image = ax.imshow(matrix, aspect="auto", cmap=cmap, norm=Normalize(vmin=vmin, vmax=vmax))
    winner = min(points, key=lambda point: point.missrate)
    for row, (index_type, _) in enumerate(index_order):
        for col, capacity in enumerate(capacities):
            point = point_map.get((index_type, capacity))
            if point is None:
                continue
            rgba = image.cmap(image.norm(point.missrate))
            luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            label = f"{point.missrate:.2f}"
            ax.text(col, row, label, ha="center", va="center", fontsize=6.7, color="black" if luminance > 0.56 else "white")
            if point == winner:
                ax.add_patch(Rectangle((col - 0.48, row - 0.48), 0.96, 0.96, fill=False, edgecolor="black", linewidth=2.2))
    ax.set_xticks(range(len(capacities)))
    ax.set_xticklabels([f"{capacity // 1024}K" for capacity in capacities])
    ax.set_yticks(range(len(index_order)))
    ax.set_yticklabels([label for _, label in index_order])
    ax.set_xlabel("VIL capacity (entries)")
    ax.set_ylabel("VIL index")
    ax.set_xticks([value - 0.5 for value in range(1, len(capacities))], minor=True)
    ax.set_yticks([value - 0.5 for value in range(1, len(index_order))], minor=True)
    ax.grid(which="minor", color="white", linewidth=0.8, alpha=0.7)
    ax.tick_params(which="minor", bottom=False, left=False)
    cbar = ax.figure.colorbar(image, ax=ax, fraction=0.045, pad=0.025)
    cbar.set_label("Miss rate (%)", fontsize=8)
    cbar.ax.tick_params(labelsize=7)


def create_overview(
    input_path: Path,
    output_path: Path,
    vil_input_path: Path | None = None,
) -> dict[str, tuple[int, int]]:
    points = load_points(input_path)
    vil_points = load_vil_points(vil_input_path)
    by_trace: dict[str, list[Point]] = defaultdict(list)
    vil_by_trace: dict[str, list[VILPoint]] = defaultdict(list)
    for point in points:
        by_trace[point.trace_key].append(point)
    for point in vil_points:
        vil_by_trace[point.trace_key].append(point)

    trace_keys = [key for key in TRACE_ORDER if by_trace.get(key)]
    if not trace_keys:
        raise SystemExit(f"No usable rows in {input_path}")

    has_vil = bool(vil_points)
    row_count = 4 if has_vil else 3
    figure_height = 18.0 if has_vil else 14.2
    fig, axes = plt.subplots(row_count, len(trace_keys), figsize=(6.2 * len(trace_keys), figure_height), squeeze=False)
    fig.suptitle("MP3 vs proposed VIL cache sweep overview", fontsize=18, fontweight="bold", y=0.995)
    fig.text(
        0.5,
        0.977,
        f"MP3: L1 /24 + all {EXPECTED_REFBITS_PAIRS} descending L2/L3 pairs through /{MP_MIN_REFBITS}; VIL: way 8, exclusive, IDEAL + PREFIX16..24; entry-count comparison (not equal bitsum)",
        ha="center",
        fontsize=10,
    )

    for col, trace_key in enumerate(trace_keys):
        trace_points = by_trace[trace_key]
        trace_vil_points = vil_by_trace[trace_key]
        color = TRACE_COLORS[trace_key]
        count = len(trace_points)
        vil_count = len(trace_vil_points)

        title = f"{TRACE_LABELS[trace_key]}  (MP {count}/{EXPECTED_POINTS}; VIL {vil_count}/{EXPECTED_VIL_POINTS})"
        axes[0][col].set_title(title, fontsize=12, fontweight="bold")
        draw_best_curve(axes[0][col], trace_points, trace_vil_points, color)
        incomplete_note(axes[0][col], count)

        draw_pareto(axes[1][col], trace_points, trace_vil_points, color)
        incomplete_note(axes[1][col], count)

        draw_refbits_heatmap(axes[2][col], trace_points)
        incomplete_note(axes[2][col], count)

        if has_vil:
            draw_vil_heatmap(axes[3][col], trace_vil_points)
            if vil_count < EXPECTED_VIL_POINTS:
                axes[3][col].text(
                    0.98,
                    0.97,
                    f"INCOMPLETE {vil_count}/{EXPECTED_VIL_POINTS}",
                    transform=axes[3][col].transAxes,
                    ha="right",
                    va="top",
                    fontsize=8,
                    color="#A33A46",
                )

    axes[0][0].set_ylabel("Best miss rate (%)")
    axes[1][0].set_ylabel("Miss rate (%)")
    if has_vil:
        fig.text(0.008, 0.87, "BEST BY CAPACITY", rotation=90, va="center", fontsize=10, fontweight="bold")
        fig.text(0.008, 0.635, "ALL POINTS + PARETO", rotation=90, va="center", fontsize=10, fontweight="bold")
        fig.text(0.008, 0.39, "MP3 REFBITS", rotation=90, va="center", fontsize=10, fontweight="bold")
        fig.text(0.008, 0.145, "VIL INDEX", rotation=90, va="center", fontsize=10, fontweight="bold")
    else:
        fig.text(0.008, 0.82, "BEST BY TOTAL CAPACITY", rotation=90, va="center", fontsize=10, fontweight="bold")
        fig.text(0.008, 0.50, "ALL POINTS + PARETO", rotation=90, va="center", fontsize=10, fontweight="bold")
        fig.text(0.008, 0.18, "REFBITS HEATMAP", rotation=90, va="center", fontsize=10, fontweight="bold")
    fig.text(0.5, 0.007, "Heatmap values are miss rate (%); outlined cell is best in each method and trace.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0.025, 0.025, 1, 0.965), h_pad=3.0, w_pad=2.4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    summary: dict[str, tuple[int, int]] = {}
    for trace_key in trace_keys:
        pairs = {(point.l2_refbits, point.l3_refbits) for point in by_trace[trace_key]}
        summary[trace_key] = (len(by_trace[trace_key]), len(pairs))
    return summary


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    vil_input_path = Path(args.vil_input) if args.vil_input else None
    summary = create_overview(input_path, output_path, vil_input_path)
    print(f"Saved {output_path}")
    for trace_key, (point_count, pair_count) in summary.items():
        print(
            f"{trace_key}: {point_count}/{EXPECTED_POINTS} points, "
            f"{pair_count}/{EXPECTED_REFBITS_PAIRS} refbits pairs"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
