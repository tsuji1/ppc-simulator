#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
import argparse
import csv
import os
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot UnifiedCache resident entry Length distribution from a -loglength CSV."
    )
    parser.add_argument("--input", required=True, help="Input cache_length_*.csv from -loglength")
    parser.add_argument(
        "--output",
        default="scripts/reports/unified_cache_length_fixed18_cap4096_log/cache_length_distribution_log.png",
        help="Output PNG path",
    )
    parser.add_argument("--start-length", type=int, default=9, help="Start Length, inclusive")
    parser.add_argument("--end-length", type=int, default=24, help="End Length, inclusive")
    parser.add_argument(
        "--title",
        default="Prefix-Shared-Cache resident Length distribution",
        help="Plot title",
    )
    return parser.parse_args()


def read_summary_rows(input_path: str, start_length: int, end_length: int) -> List[Dict[str, int]]:
    by_length: Dict[int, Dict[str, int]] = {}
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("scope") != "summary":
                continue
            length = int(row["length"])
            if start_length <= length <= end_length:
                by_length[length] = {
                    "length": length,
                    "entry_count": int(row["entry_count"]),
                    "refered_sum": int(row["refered_sum"]),
                }

    rows: List[Dict[str, int]] = []
    for length in range(start_length, end_length + 1):
        rows.append(
            by_length.get(
                length,
                {
                    "length": length,
                    "entry_count": 0,
                    "refered_sum": 0,
                },
            )
        )
    return rows


def positive_or_none(values: List[int]) -> List[float]:
    return [float(value) if value > 0 else float("nan") for value in values]


def plot(rows: List[Dict[str, int]], output_path: str, title: str) -> None:
    lengths = [row["length"] for row in rows]
    labels = [f"/{length}" for length in lengths]
    entry_counts = [row["entry_count"] for row in rows]
    refered_sums = [row["refered_sum"] for row in rows]

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    fig.suptitle(title)

    axes[0].bar(lengths, positive_or_none(entry_counts), color="#3b6ea8", width=0.72)
    axes[0].set_ylabel("Resident entries")
    axes[0].set_yscale("log")
    axes[0].grid(True, which="both", axis="y", linestyle=":", linewidth=0.7)

    axes[1].bar(lengths, positive_or_none(refered_sums), color="#c97a2b", width=0.72)
    axes[1].set_ylabel("Refered sum")
    axes[1].set_yscale("log")
    axes[1].grid(True, which="both", axis="y", linestyle=":", linewidth=0.7)
    axes[1].set_xlabel("Length")
    axes[1].set_xticks(lengths)
    axes[1].set_xticklabels(labels)

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    fig.tight_layout()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    if args.start_length > args.end_length:
        raise ValueError("--start-length must be less than or equal to --end-length")

    rows = read_summary_rows(args.input, args.start_length, args.end_length)
    plot(rows, args.output, args.title)

    total_entries = sum(row["entry_count"] for row in rows)
    total_refered = sum(row["refered_sum"] for row in rows)
    print(f"Saved graph: {args.output}")
    print(f"length_range: /{args.start_length}../{args.end_length}")
    print(f"total_entries: {total_entries}")
    print(f"total_refered_sum: {total_refered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
