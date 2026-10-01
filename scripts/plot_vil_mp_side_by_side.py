#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
# ]
# ///
"""Plot VIL and MP results side by side for each anonymous trace."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent / "reports/global-xor-anon-vil-mp-capacity32k"
INPUT = ROOT / "capacity_results.csv"
OUTPUT = ROOT / "side-by-side"

CONDITIONS = (
    "original",
    "target-2025-09",
    "target-2025-12",
    "target-2026-03",
)
TRACES = ("San Jose", "Chicago", "NYC")
VIL_SERIES = (
    ("VIL /16", "#d9d9d9", ""),
    ("VIL /18", "#bdbdbd", "//"),
    ("VIL /20", "#969696", ""),
    ("VIL /22", "#636363", "//"),
    ("VIL /24", "#111111", ""),
    ("VIL ideal", "#c71920", ""),
)
MP_SERIES = (
    ("MP 2-cache（/24, /18）", "MP 2-cache", "#111111"),
    ("MP 3-cache（/24, /21, /18）", "MP 3-cache", "#3267a8"),
)
VIL_CAPS = (1024, 2048, 4096, 8192, 16384, 32768)
MP2_CAPS = (1024, 2048, 4096, 8192, 16384, 32768)
MP3_CAPS = (1536, 3072, 6144, 12288, 24576)


def cap_label(value: int) -> str:
    if value % 1024 == 0:
        return f"{value // 1024}K"
    return f"{value / 1024:g}K"


def read_rows() -> list[dict[str, str]]:
    with INPUT.open(newline="") as stream:
        return list(csv.DictReader(stream))


def value_map(
    rows: list[dict[str, str]], condition: str, trace: str, architecture: str,
    series: str, metric: str,
) -> dict[int, float]:
    result: dict[int, float] = {}
    for row in rows:
        if (
            row["condition"] == condition
            and row["trace"] == trace
            and row["architecture"] == architecture
            and row["series"] == series
        ):
            result[int(row["total_capacity"])] = float(row[metric])
    return result


def draw_vil(ax, rows, condition: str, trace: str, metric: str) -> list[float]:
    x = list(range(len(VIL_CAPS)))
    width = 0.125
    all_values: list[float] = []
    for index, (series, color, hatch) in enumerate(VIL_SERIES):
        values = value_map(rows, condition, trace, "VIL", series, metric)
        ys = [values[c] for c in VIL_CAPS]
        all_values.extend(ys)
        offset = (index - (len(VIL_SERIES) - 1) / 2) * width
        ax.bar(
            [v + offset for v in x], ys, width=width, label=series,
            color=color, edgecolor="#111111", linewidth=0.35, hatch=hatch,
        )
    ax.set_xticks(x, [cap_label(c) for c in VIL_CAPS])
    return all_values


def draw_mp(ax, rows, condition: str, trace: str, metric: str) -> list[float]:
    x = list(range(len(MP2_CAPS)))
    width = 0.34
    all_values: list[float] = []
    for series, label, color in MP_SERIES:
        architecture = "MP2" if "2-cache" in series else "MP3"
        caps = MP2_CAPS if architecture == "MP2" else MP3_CAPS
        values = value_map(rows, condition, trace, architecture, series, metric)
        ys = [values[c] for c in caps]
        all_values.extend(ys)
        offset = -width / 2 if architecture == "MP2" else width / 2
        ax.bar(
            [v + offset for v in x[: len(caps)]], ys, width=width,
            label=label, color=color, edgecolor="#111111", linewidth=0.4,
        )
    labels = [
        f"{cap_label(a)} / {cap_label(b)}" if i < len(MP3_CAPS) else f"{cap_label(a)} / —"
        for i, (a, b) in enumerate(zip(MP2_CAPS, MP3_CAPS + (0,)))
    ]
    ax.set_xticks(x, labels)
    return all_values


def plot(rows: list[dict[str, str]], condition: str, metric: str, output: Path) -> None:
    ylabel = "Miss rate [%]" if metric == "miss_rate_percent" else "Estimated power [mW]"
    fig, axes = plt.subplots(3, 2, figsize=(16, 9), constrained_layout=False)
    fig.patch.set_facecolor("white")
    for row_index, trace in enumerate(TRACES):
        left, right = axes[row_index]
        vil_values = draw_vil(left, rows, condition, trace, metric)
        mp_values = draw_mp(right, rows, condition, trace, metric)
        upper = max(vil_values + mp_values) * 1.12
        for ax in (left, right):
            ax.set_ylim(0, upper)
            ax.grid(axis="y", color="#d9d9d9", linewidth=0.7)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
            ax.spines[["left", "bottom"]].set_color("#111111")
            ax.tick_params(axis="both", labelsize=8, colors="#111111")
        left.set_ylabel(f"{trace}\n{ylabel}", fontsize=10, color="#111111")
        right.tick_params(axis="y", labelleft=False)
        if row_index == 0:
            left.set_title("VIL cache", fontsize=14, weight="bold", color="#111111", pad=28)
            right.set_title("MP cache", fontsize=14, weight="bold", color="#111111", pad=28)
            left.legend(
                loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3,
                frameon=False, fontsize=8, handlelength=1.4, columnspacing=1.0,
            )
            right.legend(
                loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2,
                frameon=False, fontsize=9,
            )
        if row_index == 2:
            left.set_xlabel("Total cache entries", fontsize=9)
            right.set_xlabel("Total entries: MP2 / MP3", fontsize=9)
    fig.subplots_adjust(left=0.095, right=0.985, top=0.90, bottom=0.075, hspace=0.38, wspace=0.08)
    fig.savefig(output, dpi=220, facecolor="white")
    plt.close(fig)


def main() -> None:
    rows = read_rows()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for condition in CONDITIONS:
        plot(rows, condition, "miss_rate_percent", OUTPUT / f"{condition}_miss_rate.png")
        plot(rows, condition, "power_mw", OUTPUT / f"{condition}_power.png")
    print(f"wrote 8 graphs to {OUTPUT}")


if __name__ == "__main__":
    main()
