# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Compare packet LPM rates with distinct selected-prefix coverage."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


COLORS = {
    "target": "#2F69BF",
    "original": "#777777",
    "global": "#D7191C",
    "top": "#E66101",
    "bottom": "#A50026",
    "other": "#6A3D9A",
}


def series_color(label: str, index: int) -> str:
    value = label.lower()
    if "target" in value or "non-anon" in value or "nonanon" in value or "非匿名" in value:
        return COLORS["target"]
    if "original" in value or "baseline" in value or "変換前" in value:
        return COLORS["original"]
    if "top" in value or "上から" in value:
        return COLORS["top"]
    if "bottom" in value or "下から" in value:
        return COLORS["bottom"]
    if "xor" in value:
        return COLORS["global"]
    fallback = [COLORS["other"], "#1B9E77", "#7570B3"]
    return fallback[index % len(fallback)]


def parse_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--input must be LABEL=CSV")
    label, path = value.split("=", 1)
    if not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("--input must be LABEL=CSV")
    return label.strip(), Path(path)


def read_coverage(path: Path) -> dict[int, dict[int, dict[str, float]]]:
    result: dict[int, dict[int, dict[str, float]]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            checkpoint = int(row["checkpoint_packets"])
            length = int(row["lpm_prefix_length"])
            result[checkpoint][length] = {
                "packet_count": float(row["packet_count"]),
                "packet_share": float(row["packet_share"]),
                "distinct": float(row["distinct_lpm_prefixes"]),
                "distinct_share": float(row["distinct_share"]),
                "rib": float(row["rib_prefixes"]),
                "coverage": float(row["rib_coverage"]),
            }
    return dict(result)


def tv(left: dict[int, dict[str, float]], right: dict[int, dict[str, float]], field: str) -> float:
    return 0.5 * sum(abs(left[length][field] - right[length][field]) for length in range(33))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True, type=parse_input, help="LABEL=lpm_prefix_coverage.csv")
    parser.add_argument("--target", required=True, help="label of the non-anonymized target series")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--title", default="LPM prefix coverage")
    args = parser.parse_args()

    labels = [label for label, _ in args.input]
    if len(labels) != len(set(labels)):
        raise SystemExit("duplicate input label")
    if args.target not in labels:
        raise SystemExit(f"target label {args.target!r} is not an input label")
    data = {label: read_coverage(path) for label, path in args.input}
    common = set.intersection(*(set(item) for item in data.values()))
    if not common:
        raise SystemExit("inputs have no common checkpoint; run them with the same --max")
    checkpoint = max(common)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    colors = {label: series_color(label, index) for index, label in enumerate(labels)}

    active_lengths = [
        length for length in range(33)
        if any(data[label][checkpoint][length]["distinct"] > 0 for label in labels)
    ]
    width = min(0.8 / len(labels), 0.22)
    x = list(range(len(active_lengths)))
    fig, ax = plt.subplots(figsize=(15, 6.8))
    for index, label in enumerate(labels):
        offset = (index - (len(labels) - 1) / 2) * width
        values = [data[label][checkpoint][length]["distinct"] for length in active_lengths]
        ax.bar([value + offset for value in x], values, width=width, label=label, color=colors[label])
    ax.set_yscale("log")
    ax.set_xticks(x, [f"/{length}" for length in active_lengths])
    ax.set_xlabel("LPM prefix length")
    ax.set_ylabel("Distinct selected routing prefixes (log scale)")
    ax.set_title(f"{args.title}: distinct prefixes at {checkpoint:,} packets")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=min(3, len(labels)))
    fig.tight_layout()
    fig.savefig(args.output_dir / "distinct_lpm_prefixes_by_length.png", dpi=180)
    plt.close(fig)

    coverage_lengths = [
        length for length in range(33)
        if any(data[label][checkpoint][length]["rib"] > 0 for label in labels)
    ]
    x = list(range(len(coverage_lengths)))
    fig, ax = plt.subplots(figsize=(15, 6.8))
    for index, label in enumerate(labels):
        offset = (index - (len(labels) - 1) / 2) * width
        values = [data[label][checkpoint][length]["coverage"] for length in coverage_lengths]
        ax.bar([value + offset for value in x], values, width=width, label=label, color=colors[label])
    ax.set_xticks(x, [f"/{length}" for length in coverage_lengths])
    ax.set_xlabel("LPM prefix length")
    ax.set_ylabel("Selected prefixes / RIB prefixes")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title(f"{args.title}: RIB prefix coverage at {checkpoint:,} packets")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=min(3, len(labels)))
    fig.tight_layout()
    fig.savefig(args.output_dir / "rib_prefix_coverage_by_length.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    for label in labels:
        checkpoints = sorted(data[label])
        totals = [sum(data[label][cp][length]["distinct"] for length in range(33)) for cp in checkpoints]
        ax.plot(checkpoints, totals, marker="o", linewidth=2.0, label=label, color=colors[label])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Valid IPv4 TCP/UDP packets processed (log scale)")
    ax.set_ylabel("Total distinct selected routing prefixes (log scale)")
    ax.set_title(f"{args.title}: prefix discovery curve")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(args.output_dir / "distinct_prefix_accumulation.png", dpi=180)
    plt.close(fig)

    target = data[args.target][checkpoint]
    target_total = sum(target[length]["distinct"] for length in range(33))
    with (args.output_dir / "prefix_coverage_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "condition", "checkpoint_packets", "distinct_shape_tv", "packet_lpm_tv",
            "distinct_prefixes_total", "target_distinct_prefixes_total", "distinct_total_ratio",
            "rib_coverage_mean_absolute_difference",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for label in labels:
            actual = data[label][checkpoint]
            total = sum(actual[length]["distinct"] for length in range(33))
            covered_lengths = [length for length in range(33) if actual[length]["rib"] > 0 or target[length]["rib"] > 0]
            coverage_mae = sum(abs(actual[length]["coverage"] - target[length]["coverage"]) for length in covered_lengths) / len(covered_lengths)
            writer.writerow({
                "condition": label,
                "checkpoint_packets": checkpoint,
                "distinct_shape_tv": f"{tv(actual, target, 'distinct_share'):.12g}",
                "packet_lpm_tv": f"{tv(actual, target, 'packet_share'):.12g}",
                "distinct_prefixes_total": int(total),
                "target_distinct_prefixes_total": int(target_total),
                "distinct_total_ratio": f"{total / target_total:.12g}" if target_total else "",
                "rib_coverage_mean_absolute_difference": f"{coverage_mae:.12g}",
            })

    print(f"common checkpoint: {checkpoint:,}")
    print(f"wrote: {args.output_dir}")


if __name__ == "__main__":
    main()
