#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
"""Plot LPM hit/miss counts from analyze_hitrace_lpm.py output."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot record-cache-hit LPM distribution with a logarithmic y-axis."
    )
    parser.add_argument("--input-csv", required=True, help="*_lpm_by_hit_state.csv")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--title", default="Cache hits by LPM prefix length")
    parser.add_argument(
        "--annotate",
        type=int,
        nargs="*",
        default=[12, 15, 16],
        help="Prefix lengths to annotate on the hit bars",
    )
    return parser.parse_args()


def read_rows(path: Path) -> dict[int, dict[str, float]]:
    rows: dict[int, dict[str, float]] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            prefix_len = int(row["lpm_prefix_len"])
            rows[prefix_len] = {
                "packets": float(row["packets"]),
                "hits": float(row["hits"]),
                "misses": float(row["misses"]),
                "hit_rate": float(row["hit_rate"]),
            }
    return rows


def fmt_count(value: float) -> str:
    return f"{int(value):,}"


def main() -> int:
    args = parse_args()
    input_csv = Path(args.input_csv)
    output = Path(args.output)
    rows = read_rows(input_csv)

    x = list(range(33))
    hits = [rows.get(i, {}).get("hits", 0.0) for i in x]
    misses = [rows.get(i, {}).get("misses", 0.0) for i in x]

    fig, ax = plt.subplots(figsize=(12, 6.5))
    width = 0.42
    hit_bars = ax.bar(
        [i - width / 2 for i in x],
        [v if v > 0 else 0 for v in hits],
        width=width,
        label="hits",
        color="#2563eb",
    )
    ax.bar(
        [i + width / 2 for i in x],
        [v if v > 0 else 0 for v in misses],
        width=width,
        label="misses",
        color="#f97316",
        alpha=0.72,
    )

    ax.set_yscale("log")
    ax.set_xlim(-0.8, 32.8)
    ax.set_xticks(x)
    ax.set_xlabel("Routing-rule LPM prefix length")
    ax.set_ylabel("Packet count (log scale)")
    ax.set_title(args.title, loc="left")
    ax.grid(True, axis="y", which="both", linestyle=":", alpha=0.35)
    ax.legend()

    for prefix_len in args.annotate:
        if prefix_len < 0 or prefix_len > 32:
            continue
        value = hits[prefix_len]
        if value <= 0:
            continue
        bar = hit_bars[prefix_len]
        ax.annotate(
            f"/{prefix_len}\n{fmt_count(value)}",
            xy=(bar.get_x() + bar.get_width() / 2, value),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#1e3a8a",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
