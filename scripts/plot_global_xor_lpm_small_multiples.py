#!/usr/bin/env python3
"""Plot post-XOR LPM distributions against each non-anonymous target."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"],
    "axes.unicode_minus": False,
})


TRACE_DIRS = [
    ("jpix-sinet", "JPIX-SINET\n2018-05"),
    ("sinet-jpix", "SINET-JPIX\n2018-05"),
    ("wide-2025-09", "WIDE\n2025-09"),
    ("wide-2025-12", "WIDE\n2025-12"),
    ("wide-2026-03", "WIDE\n2026-03"),
    ("sanjose", "San Jose\n2014-03"),
    ("chicago", "Chicago\n2014-03"),
    ("nyc", "New York\n2019-01"),
]


def read_column(path: Path, column: str) -> list[float]:
    values = [0.0] * 33
    with path.open(newline="", encoding="utf-8") as fp:
        for row in csv.DictReader(fp):
            prefix = int(row["lpm_prefix_length"])
            if 0 <= prefix <= 32:
                values[prefix] = float(row[column])
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=["2025-09-27", "2025-12-27", "2026-03-27"])
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path(__file__).resolve().parent / "reports" / "global-xor-lpm-tv-exhaustive24",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "reports" / "global-xor-cap8192-cross-trace",
    )
    args = parser.parse_args()

    series = []
    ymax = 0.0
    for trace_dir, label in TRACE_DIRS:
        base = args.input_root / trace_dir / args.target
        before = read_column(base / "lpm_distribution.csv", "before_percent")
        after = read_column(base / "lpm_distribution.csv", "after_percent")
        target = read_column(base / "reference_lpm_distribution.csv", "percent")
        ymax = max(ymax, max(before), max(after), max(target))
        series.append((label, before, after, target))

    # A shared scale makes differences comparable across all eight traces.
    ymax = max(5.0, (int(ymax / 5.0) + 2) * 5.0)
    x = list(range(33))
    fig, axes = plt.subplots(2, 4, figsize=(16.0, 7.1), sharex=True, sharey=True)

    for ax, (label, before, after, target) in zip(axes.flat, series):
        ax.plot(x, before, color="#7F7F7F", linewidth=1.8, marker="o",
                markersize=2.7, label="変換前", zorder=3)
        ax.plot(x, after, color="#C00000", linewidth=2.0, marker="o",
                markersize=2.7, label="変換後", zorder=4)
        ax.plot(x, target, color="#2F75B5", linewidth=2.0, marker="o",
                markersize=2.7, label="非匿名目標", zorder=5)
        ax.set_title(label, fontsize=13, fontweight="bold", pad=6)
        ax.set_xlim(0, 32)
        ax.set_ylim(0, ymax)
        ax.set_xticks(range(0, 33, 2), [f"/{i}" for i in range(0, 33, 2)])
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
        ax.grid(axis="both", color="#D9E1F2", linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="x", labelsize=8, rotation=55)
        ax.tick_params(axis="y", labelsize=9)

    for ax in axes[:, 0]:
        ax.set_ylabel("割合（%）", fontsize=11)
    for ax in axes[-1, :]:
        ax.set_xlabel("LPM一致長", fontsize=10)

    handles = [
        plt.Line2D([0], [0], color="#7F7F7F", linewidth=2.2, marker="o", markersize=4, label="変換前"),
        plt.Line2D([0], [0], color="#C00000", linewidth=2.2, marker="o", markersize=4, label="変換後"),
        plt.Line2D([0], [0], color="#2F75B5", linewidth=2.2, marker="o", markersize=4, label="非匿名目標"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=3, frameon=False, fontsize=12, bbox_to_anchor=(0.5, 0.995))
    fig.tight_layout(rect=(0.015, 0.01, 0.995, 0.94), h_pad=1.35, w_pad=0.9)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{args.target}_lpm_distribution_after_xor.png"
    fig.savefig(out, dpi=220, facecolor="white")
    print(out)


if __name__ == "__main__":
    main()
