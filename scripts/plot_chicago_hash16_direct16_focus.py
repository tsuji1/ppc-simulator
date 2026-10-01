#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
"""Create a focused Chicago CRC32(/16) vs direct-/16 capacity plot."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="scripts/reports/unified_index_graphs/chicago_hash_direct_hitrate.csv",
    )
    parser.add_argument(
        "--output",
        default=(
            "scripts/reports/chicago_hash16_vs_direct16/"
            "chicago_hash16_direct16_capacity.png"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: dict[int, dict[str, str]] = {}
    with input_path.open(newline="") as fp:
        for row in csv.DictReader(fp):
            rows[int(row["cache_index_type"])] = row

    hash_row = rows[16]
    direct_row = rows[116]
    capacity_labels = [
        column for column in hash_row if column.startswith("2^")
    ]
    exponents = [int(label[2:]) for label in capacity_labels]
    hash_rates = [float(hash_row[label]) for label in capacity_labels]
    direct_rates = [float(direct_row[label]) for label in capacity_labels]
    deltas = [
        hash_rate - direct_rate
        for hash_rate, direct_rate in zip(hash_rates, direct_rates)
    ]

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Noto Sans CJK JP",
                "Yu Gothic",
                "Meiryo",
                "DejaVu Sans",
            ],
            "font.size": 12,
            "axes.titlesize": 15,
            "axes.labelsize": 12,
        }
    )

    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(10.4, 5.7),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.25], "hspace": 0.12},
    )
    blue = "#2f6fb0"
    orange = "#d97a2b"
    top.plot(
        exponents,
        hash_rates,
        marker="o",
        markersize=7,
        linewidth=2.5,
        color=blue,
        label="先頭16 bitをCRC32で変換",
    )
    top.plot(
        exponents,
        direct_rates,
        marker="s",
        markersize=6,
        linewidth=2.3,
        linestyle="--",
        color=orange,
        label="先頭16 bitの下位k bitをそのまま使用",
    )
    top.set_ylabel("ヒット率（%）")
    top.set_title("Chicago：2方式のヒット率はほぼ重なる")
    top.grid(True, alpha=0.25)
    top.legend(loc="lower right", frameon=False)
    for exponent, hash_rate, direct_rate in zip(
        exponents, hash_rates, direct_rates
    ):
        if exponent not in {10, 12}:
            continue
        top.annotate(
            f"{hash_rate:.3f}% / {direct_rate:.3f}%",
            (exponent, max(hash_rate, direct_rate)),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=10.5,
            color="#333333",
        )

    bottom.bar(exponents, deltas, width=0.58, color=blue)
    bottom.axhline(0, color="#333333", linewidth=0.8)
    bottom.set_ylabel("差\n（point）", rotation=0, labelpad=24, va="center")
    bottom.set_xlabel("総エントリ数（8-way）")
    bottom.grid(True, axis="y", alpha=0.25)
    bottom.set_xticks(exponents, [f"2^{value}" for value in exponents])
    for exponent, delta in zip(exponents, deltas):
        bottom.text(
            exponent,
            delta + (0.004 if delta >= 0 else -0.004),
            f"{delta:+.3f}",
            ha="center",
            va="bottom" if delta >= 0 else "top",
            fontsize=10,
        )
    bottom.set_ylim(
        min(-0.025, min(deltas) - 0.015),
        max(0.11, max(deltas) + 0.02),
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    print(output_path)


if __name__ == "__main__":
    main()
