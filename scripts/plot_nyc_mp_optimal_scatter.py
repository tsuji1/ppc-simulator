#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.9.2"]
# ///
"""Regenerate the NYC capacity scatter plots, including MP optimal points."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "scripts/reports/nyc-mp-optimal"
OPTIMAL = ROOT / "scripts/reports/nyc-mp-optimal-power/nyc_mp_optimal_power.csv"
CAPACITY_RESULTS = REPORT / "capacity_results_128k.csv"
TRACE = "NYC"

CONDITIONS = {
    "original": "NYC（元匿名トレース）",
}

# Keep all method colors within the simple palette requested for the deck.
VIL_COLORS = {
    "VIL /16": "#a1d99b",
    "VIL /18": "#74c476",
    "VIL /20": "#41ab5d",
    "VIL /22": "#238b45",
    "VIL /24": "#006d2c",
}
MP_COLORS = {
	"MP 2-cache（/24, /18）": "#9ecae1",
	"MP 3-cache（/24, /21, /18）": "#3182bd",
}
MP_LEGEND_LABELS = {
	"MP 2-cache（/24, /18）": "MP2 /24・/18（各cache容量均等）",
	"MP 3-cache（/24, /21, /18）": "MP3 /24・/21・/18（各cache容量均等）",
}

# Fixed-prefix MP series and the miss-rate-optimal prefix sweep are different
# series. Keep that distinction explicit in the figure legend.
OPTIMAL_LABELS = {
    "MP2": "MP2 optimal（prefix全探索・frontier）",
    "MP3": "MP3 optimal（prefix全探索・frontier）",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def metric_value(row: dict[str, str], metric: str) -> float:
    return float(row[metric])


def configure_axes(ax: plt.Axes, ylabel: str) -> None:
    ax.set_xscale("log", base=2)
    ax.set_xlim(900, 145000)
    ticks = (1024, 2048, 4096, 8192, 16384, 32768, 65536, 98304, 131072)
    labels = ("1K", "2K", "4K", "8K", "16K", "32K", "64K", "96K", "128K")
    ax.set_xticks(ticks, labels)
    ax.set_xlabel("合計キャッシュ容量（entries、log2）", fontsize=17)
    ax.set_ylabel(ylabel, fontsize=17)
    ax.grid(axis="y", color="#d9d9d9", linewidth=1.0)
    ax.grid(axis="x", which="major", color="#eeeeee", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=13, labelrotation=20)
    ax.tick_params(axis="y", labelsize=14)


def draw_series(ax: plt.Axes, rows: list[dict[str, str]], metric: str) -> None:
    # Draw VIL first, then MP, so that the legend follows the cache family.
    for series, color in VIL_COLORS.items():
        selected = [row for row in rows if row["series"] == series]
        if not selected:
            continue
        ax.scatter(
            [int(row["total_capacity"]) for row in selected],
            [metric_value(row, metric) for row in selected],
            s=70,
            color=color,
            edgecolor="white",
            linewidth=0.45,
            label=series,
            zorder=3,
        )
    # VIL ideal is intentionally red, distinct from the green VIL prefix series.
    ideal = [row for row in rows if row["series"] == "VIL ideal"]
    if ideal:
        ax.scatter(
            [int(row["total_capacity"]) for row in ideal],
            [metric_value(row, metric) for row in ideal],
            s=76,
            color="#d7191c",
            edgecolor="white",
            linewidth=0.45,
            label="VIL ideal",
            zorder=3,
        )
    for series, color in MP_COLORS.items():
        selected = [row for row in rows if row["series"] == series]
        if not selected:
            continue
        ax.scatter(
            [int(row["total_capacity"]) for row in selected],
            [metric_value(row, metric) for row in selected],
            s=78,
            color=color,
            edgecolor="white",
            linewidth=0.45,
            label=MP_LEGEND_LABELS[series],
            zorder=3,
        )


def metric_frontier_rows(optimal: list[dict[str, str]], metric: str) -> list[dict[str, str]]:
    """Return the per-metric monotone frontier of miss-rate-optimal points."""
    if metric not in {"miss_rate_percent", "power_mw"}:
        raise ValueError(f"unsupported frontier metric: {metric}")
    selected: list[dict[str, str]] = []
    best = {"miss_rate_percent": float("inf"), "power_mw": float("inf")}
    for architecture in ("MP2", "MP3"):
        candidates = sorted(
            (row for row in optimal if row["architecture"] == architecture),
            key=lambda row: int(row["total_capacity"]),
        )
        best_value = float("inf")
        for row in candidates:
            value = float(row[metric])
            if value <= best_value:
                selected.append(row)
                best_value = value
    return sorted(selected, key=lambda row: (int(row["total_capacity"]), row["architecture"]))


def frontier_label(architecture: str, metric: str) -> str:
    suffix = "ミス率frontier" if metric == "miss_rate_percent" else "電力frontier"
    prefix_label = {
        "MP2": "MP2 /24・/18 optimal",
        "MP3": "MP3 /24・/21・/18 optimal",
    }[architecture]
    return f"{prefix_label}（prefix全探索・{suffix}）"


def draw_optimal(ax: plt.Axes, optimal: list[dict[str, str]], metric: str) -> None:
    # The frontier is metric-specific: miss-rate plots use only miss-rate
    # monotonicity, and power plots use only power monotonicity.
    rows_by_architecture = {
        architecture: [row for row in metric_frontier_rows(optimal, metric) if row["architecture"] == architecture]
        for architecture in ("MP2", "MP3")
    }
    for architecture, marker in (("MP2", "D"), ("MP3", "P")):
        selected = rows_by_architecture[architecture]
        if not selected:
            continue
        ax.scatter(
            [int(row["total_capacity"]) for row in selected],
            [metric_value(row, metric) for row in selected],
            s=120,
            color="#111111",
            marker=marker,
            edgecolor="white",
            linewidth=0.8,
            label=frontier_label(architecture, metric),
            zorder=6,
        )


def make_plot(
    rows: list[dict[str, str]],
    optimal: list[dict[str, str]],
    condition: str,
    metric: str,
    ylabel: str,
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(17, 7.2))
    draw_series(ax, rows, metric)
    if condition == "original":
        draw_optimal(ax, optimal, metric)
    configure_axes(ax, ylabel)
    ax.set_title(CONDITIONS[condition], fontsize=26, color="#111111", weight="bold", pad=18)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.015),
        ncol=4,
        frameon=False,
        fontsize=13,
        columnspacing=1.25,
        handletextpad=0.45,
    )
    frontier_text = (
        "frontier: 容量増加でミス率が悪化しない点だけを表示"
        if metric == "miss_rate_percent"
        else "frontier: 容量増加で推定電力が悪化しない点だけを表示"
    )
    fig.text(
        0.085,
        0.035,
        "optimal: 同一合計容量でprefix長を全探索し、ミス率最小の構成を選択　／　"
        + frontier_text,
        ha="left",
        va="bottom",
        fontsize=11,
        color="#333333",
    )
    fig.subplots_adjust(left=0.085, right=0.985, bottom=0.19, top=0.76)
    fig.savefig(output, dpi=220, facecolor="white")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False})
    all_rows = read_csv(CAPACITY_RESULTS)
    optimal = read_csv(OPTIMAL)
    for metric, filename in (("miss_rate_percent", "nyc_mp_miss_frontier.csv"), ("power_mw", "nyc_mp_power_frontier.csv")):
        frontier_rows = metric_frontier_rows(optimal, metric)
        with (REPORT / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(optimal[0]))
            writer.writeheader()
            writer.writerows(frontier_rows)
    for condition in CONDITIONS:
        rows = [row for row in all_rows if row["condition"] == condition and row["trace"] == TRACE]
        make_plot(
            rows,
            optimal,
            condition,
            "miss_rate_percent",
            "ミス率（%）",
            REPORT / ("original_miss_rate_128k.png" if condition == "original" else f"{condition}_miss_rate_128k.png"),
        )
        make_plot(
            rows,
            optimal,
            condition,
            "power_mw",
            "推定消費電力（mW）",
            REPORT / ("original_power_128k.png" if condition == "original" else f"{condition}_power_128k.png"),
        )
    print(f"wrote {len(CONDITIONS) * 2} plots to {REPORT}")


if __name__ == "__main__":
    main()
