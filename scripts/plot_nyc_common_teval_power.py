#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib>=3.9.2"]
# ///
"""Plot NYC power at common offered loads (Issue #5 model).

The existing simulator CSVs report dynamic power at each configuration's
timing-limited throughput.  For a fair comparison, this script converts that
value to the common evaluation load T_eval by keeping the per-packet dynamic
energy fixed and scaling only the packet rate.  A configuration is omitted
when T_eval exceeds its measured capacity.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "scripts/reports/nyc-mp-optimal"
OPTIMAL = ROOT / "scripts/reports/nyc-mp-optimal-power/nyc_mp_optimal_power.csv"
CAPACITY_RESULTS = REPORT / "capacity_results_128k.csv"
TEVALS = (100, 200, 400, 800)
EXTRA_TEVALS = (1000,)
ALL_TEVALS = TEVALS + EXTRA_TEVALS
TRACE = "NYC"

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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def fixed_load_row(row: dict[str, str], teval: int) -> dict[str, str] | None:
    """Return a row with power at T_eval, or None if the load is infeasible."""
    t_cap = float(row["throughput_gbps"])
    if t_cap + 1e-9 < teval:
        return None
    scaled = dict(row)
    # Existing dynamic_power_mw is evaluated at t_cap.  Therefore
    # P_dyn(T_eval) = P_dyn(t_cap) * T_eval / t_cap, which is algebraically
    # equivalent to Issue #5's E_pkt * n_eval formula for the same trace.
    dynamic = float(row["dynamic_power_mw"]) * teval / t_cap
    static = float(row["static_power_mw"])
    scaled["dynamic_power_mw"] = f"{dynamic:.12g}"
    scaled["power_mw"] = f"{dynamic + static:.12g}"
    scaled["teval_gbps"] = str(teval)
    scaled["t_cap_gbps"] = f"{t_cap:.12g}"
    scaled["feasible"] = "1"
    return scaled


def frontier_rows(optimal: list[dict[str, str]], teval: int) -> list[dict[str, str]]:
    """Metric-specific power frontier at a fixed common offered load."""
    candidates: list[dict[str, str]] = []
    for source in optimal:
        row = fixed_load_row(source, teval)
        if row is not None:
            candidates.append(row)
    chosen: list[dict[str, str]] = []
    for architecture in ("MP2", "MP3"):
        series = sorted(
            (r for r in candidates if r["architecture"] == architecture),
            key=lambda r: int(r["total_capacity"]),
        )
        best = float("inf")
        for row in series:
            value = float(row["power_mw"])
            if value <= best + 1e-12:
                chosen.append(row)
                best = value
    return sorted(chosen, key=lambda r: (int(r["total_capacity"]), r["architecture"]))


def configure_axes(ax: plt.Axes) -> None:
    ax.set_xscale("log", base=2)
    ax.set_xlim(900, 145000)
    ax.set_ylim(bottom=0)
    ticks = (1024, 2048, 4096, 8192, 16384, 32768, 65536, 98304, 131072)
    labels = ("1K", "2K", "4K", "8K", "16K", "32K", "64K", "96K", "128K")
    ax.set_xticks(ticks, labels)
    ax.set_xlabel("合計キャッシュ容量（entries、log2）", fontsize=14)
    ax.set_ylabel("推定消費電力（mW）", fontsize=14)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.9)
    ax.grid(axis="x", which="major", color="#eeeeee", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=11, labelrotation=20)
    ax.tick_params(axis="y", labelsize=11)


def draw_series(ax: plt.Axes, rows: list[dict[str, str]]) -> None:
    for series, color in VIL_COLORS.items():
        selected = [r for r in rows if r["series"] == series]
        if selected:
            ax.scatter(
                [int(r["total_capacity"]) for r in selected],
                [float(r["power_mw"]) for r in selected],
                s=44, color=color, edgecolor="white", linewidth=0.35,
                label=series, zorder=3,
            )
    ideal = [r for r in rows if r["series"] == "VIL ideal"]
    if ideal:
        ax.scatter(
            [int(r["total_capacity"]) for r in ideal],
            [float(r["power_mw"]) for r in ideal],
            s=48, color="#d7191c", edgecolor="white", linewidth=0.35,
            label="VIL ideal", zorder=3,
        )
    for series, color in MP_COLORS.items():
        selected = [r for r in rows if r["series"] == series]
        if selected:
            ax.scatter(
                [int(r["total_capacity"]) for r in selected],
                [float(r["power_mw"]) for r in selected],
                s=48, color=color, edgecolor="white", linewidth=0.35,
                label=MP_LEGEND_LABELS[series], zorder=3,
            )


def draw_optimal(ax: plt.Axes, rows: list[dict[str, str]]) -> None:
    colors = {"MP2": "#111111", "MP3": "#111111"}
    markers = {"MP2": "D", "MP3": "P"}
    labels = {
        "MP2": "MP2 /24・/18 optimal（電力frontier）",
        "MP3": "MP3 /24・/21・/18 optimal（電力frontier）",
    }
    for architecture in ("MP2", "MP3"):
        selected = [r for r in rows if r["architecture"] == architecture]
        if selected:
            ax.scatter(
                [int(r["total_capacity"]) for r in selected],
                [float(r["power_mw"]) for r in selected],
                s=90, color=colors[architecture], marker=markers[architecture],
                edgecolor="white", linewidth=0.6, label=labels[architecture],
                zorder=6,
            )


def teval_label(teval: int) -> str:
    return "1 Tbps (1000 Gbps)" if teval == 1000 else f"{teval} Gbps"


def make_single(rows: list[dict[str, str]], optimal: list[dict[str, str]], teval: int, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(17, 7.2))
    draw_series(ax, rows)
    draw_optimal(ax, frontier_rows(optimal, teval))
    configure_axes(ax)
    # Keep the chart title and legend in separate, fixed figure-level bands.
    # The previous axis-level legend sat over the high-power points at 1 Tbps.
    ax.set_title("")
    fig.suptitle(
        f"NYC：共通評価負荷 {teval_label(teval)}",
        fontsize=25, weight="bold", color="#111111", y=0.975,
    )
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.90),
        ncol=3, frameon=False, fontsize=11, columnspacing=1.05,
        handletextpad=0.4,
    )
    fig.text(
        0.085, 0.035,
        "T_eval を全構成で共通化。T_cap < T_eval の構成は処理不能として表示対象外。"
        "　optimal はミス率最小構成のうち、電力が容量増加で悪化しない点。",
        ha="left", va="bottom", fontsize=10, color="#333333",
    )
    fig.subplots_adjust(left=0.085, right=0.985, bottom=0.19, top=0.70)
    fig.savefig(output, dpi=220, facecolor="white")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False})
    all_rows = read_csv(CAPACITY_RESULTS)
    optimal_source = read_csv(OPTIMAL)
    base_rows = [r for r in all_rows if r["condition"] == "original" and r["trace"] == TRACE]
    teval_rows: list[dict[str, str]] = []
    for teval in ALL_TEVALS:
        for row in base_rows:
            scaled = fixed_load_row(row, teval)
            if scaled is not None:
                scaled["series"] = row["series"]
                teval_rows.append(scaled)
        for row in optimal_source:
            scaled = fixed_load_row(row, teval)
            if scaled is not None:
                scaled["series"] = f"{row['architecture']} /prefix-sweep optimal"
                scaled["teval_gbps"] = str(teval)
                teval_rows.append(scaled)

    long_csv = REPORT / "nyc_power_common_teval.csv"
    fields = [
        "teval_gbps", "feasible", "architecture", "series", "total_capacity",
        "capacities", "refbits", "processed", "hitrate_percent", "miss_rate_percent",
        "t_cap_gbps", "dynamic_power_mw", "static_power_mw", "power_mw", "source_id",
    ]
    with long_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(teval_rows)

    frontier_csv = REPORT / "nyc_power_common_teval_frontier.csv"
    frontier_rows_all: list[dict[str, str]] = []
    for teval in ALL_TEVALS:
        frontier_rows_all.extend(frontier_rows(optimal_source, teval))
    with frontier_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(frontier_rows_all)

    single_outputs: list[Path] = []
    for teval in ALL_TEVALS:
        rows = [fixed_load_row(r, teval) for r in base_rows]
        rows = [r for r in rows if r is not None]
        output = REPORT / f"original_power_{teval}gbps.png"
        make_single(rows, optimal_source, teval, output)
        single_outputs.append(output)

    fig, axes = plt.subplots(2, 2, figsize=(19, 13), sharey=False)
    for ax, teval in zip(axes.flat, TEVALS):
        rows = [fixed_load_row(r, teval) for r in base_rows]
        rows = [r for r in rows if r is not None]
        draw_series(ax, rows)
        draw_optimal(ax, frontier_rows(optimal_source, teval))
        configure_axes(ax)
        ax.set_title(f"T_eval = {teval} Gbps", fontsize=18, weight="bold", pad=10)
        ax.legend(loc="upper right", fontsize=8.5, frameon=False, ncol=2, handletextpad=0.3, columnspacing=0.5)
    fig.suptitle("NYC：共通評価負荷での推定消費電力", fontsize=25, weight="bold", color="#111111", y=0.98)
    fig.text(
        0.05, 0.015,
        "同一の T_eval を全構成に適用。T_cap < T_eval は除外。動的電力は既存の1パケット当たりエネルギーを固定して再計算し、静的電力は不変。",
        ha="left", va="bottom", fontsize=11, color="#333333",
    )
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.08, top=0.90, hspace=0.34, wspace=0.18)
    combined = REPORT / "original_power_common_teval.png"
    fig.savefig(combined, dpi=220, facecolor="white")
    plt.close(fig)
    print(f"wrote {combined}")
    for output in single_outputs:
        print(f"wrote {output}")
    print(f"wrote {long_csv}")
    print(f"wrote {frontier_csv}")
    for teval in ALL_TEVALS:
        counts = sum(1 for r in teval_rows if r["teval_gbps"] == str(teval))
        print(f"T_eval={teval}: {counts} feasible rows")


if __name__ == "__main__":
    main()
