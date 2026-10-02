#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
"""Plot non-anonymized, anonymized, and remapped LPM distributions."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the target, original anonymized, and remapped LPM distributions."
    )
    parser.add_argument("--input-csv", required=True, help="lpm_distribution_comparison.csv")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--method", default="adaptive-lpm", help="Remapping method to plot")
    parser.add_argument("--title", default="LPM prefix-length distribution")
    return parser.parse_args()


def read_distributions(path: Path) -> tuple[dict[int, float], dict[str, dict[int, float]]]:
    target: dict[int, float] = {}
    methods: dict[str, dict[int, float]] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            prefix_length = int(row["lpm_prefix_length"])
            target[prefix_length] = float(row["target_ratio"])
            methods.setdefault(row["method"], {})[prefix_length] = float(row["ratio"])
    return target, methods


def main() -> int:
    args = parse_args()
    input_csv = Path(args.input_csv)
    output = Path(args.output)
    target, methods = read_distributions(input_csv)

    baseline_name = "baseline-anonymized"
    if baseline_name not in methods:
        raise SystemExit(f"missing method in {input_csv}: {baseline_name}")
    if args.method not in methods:
        raise SystemExit(f"missing method in {input_csv}: {args.method}")

    x = list(range(33))
    fig, ax = plt.subplots(figsize=(12, 6.6))
    ax.plot(
        x,
        [target.get(prefix, 0.0) * 100 for prefix in x],
        color="#111827",
        linewidth=2.8,
        marker="o",
        markersize=4,
        label="Non-anonymized target",
        zorder=3,
    )
    ax.plot(
        x,
        [methods[baseline_name].get(prefix, 0.0) * 100 for prefix in x],
        color="#ef4444",
        linewidth=2.0,
        linestyle="--",
        marker="x",
        markersize=5,
        label="Original anonymized",
    )
    ax.plot(
        x,
        [methods[args.method].get(prefix, 0.0) * 100 for prefix in x],
        color="#2563eb",
        linewidth=2.3,
        marker="s",
        markersize=4,
        label=f"Remapped ({args.method})",
        zorder=2,
    )

    ax.set_xlim(-0.5, 32.5)
    ax.set_xticks(x)
    ax.set_xticklabels([f"/{prefix}" for prefix in x], rotation=60, ha="right")
    ax.set_xlabel("Longest matching routing prefix")
    ax.set_ylabel("Packet share (%)")
    ax.set_title(args.title, loc="left")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    ax.legend(frameon=False)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
