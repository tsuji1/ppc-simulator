#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Plot histograms of routing-prefix node counts in WIDE /16 subtrees."""

from __future__ import annotations

import argparse
import csv
import ipaddress
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "scripts/reports/wide_prefix16_child_histogram"
RULES = (
    ("2025-09", ROOT.parent / "rules/rib.20250927.0600.unique.rule"),
    ("2025-12", ROOT.parent / "rules/rib.20251227.0600.unique.rule"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_prefix16_counts(path: Path) -> tuple[list[int], list[bool], int]:
    """Return route-node counts, non-default coverage, and /16-only subtree count."""
    nodes = [0] * 65536
    covered = [False] * 65536
    has_explicit_16 = [False] * 65536
    with path.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            network = int(ipaddress.IPv4Address(parts[0]))
            prefix_len = int(parts[1])
            if prefix_len == 0:
                continue
            if prefix_len < 16:
                first = network >> 16
                span = 1 << (16 - prefix_len)
                for prefix16 in range(first, first + span):
                    covered[prefix16] = True
            else:
                prefix16 = network >> 16
                covered[prefix16] = True
                # Count the /16 route itself as well as its more-specific routes.
                nodes[prefix16] += 1
                if prefix_len == 16:
                    has_explicit_16[prefix16] = True
    explicit_16_only = sum(has_prefix16 and count == 1 for has_prefix16, count in zip(has_explicit_16, nodes))
    return nodes, covered, explicit_16_only


def histogram(values: list[int], max_value: int) -> tuple[list[str], list[int]]:
    # Omit zero-node subtrees; keep 1–10 exact, then use 10-wide bins.
    exact_max = 10
    ranges = [(value, value) for value in range(1, min(max_value, exact_max) + 1)]
    start = exact_max + 1
    while start <= max_value:
        ranges.append((start, start + 9))
        start += 10
    counts = [0] * len(ranges)
    for value in values:
        if value == 0:
            continue
        index = value - 1 if value <= exact_max else exact_max + (value - exact_max - 1) // 10
        counts[index] += 1
    labels = [str(start) if start == end else f"{start}–{end}" for start, end in ranges]
    return labels, counts


def style_axis(ax, title: str) -> None:
    ax.set_title(title, fontsize=17, pad=14)
    ax.set_xlabel("/16サブツリーのノード数（/16自身と明示的なmore-specific prefix）")
    ax.set_ylabel("該当する /16 の数")
    ax.grid(axis="y", alpha=0.24)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)


def plot_single(
    path: Path,
    title: str,
    labels: list[str],
    counts: list[int],
    note: str,
    *,
    log_scale: bool = False,
) -> None:
    fig, ax = plt.subplots(figsize=(18, 7.5))
    x = list(range(len(labels)))
    bars = ax.bar(x, counts, color="#377eb8", width=0.82)
    ax.set_xticks(x, labels, rotation=60, ha="right", fontsize=9)
    style_axis(ax, title)
    if log_scale:
        ax.set_yscale("log")
    ax.text(
        bars[0].get_x() + bars[0].get_width() / 2,
        bars[0].get_height() * 1.12 if log_scale else bars[0].get_height() + max(counts) * 0.015,
        f"{counts[0]:,}",
        ha="center",
        fontsize=11,
    )
    if log_scale:
        ax.set_ylim(0.8, max(counts) * 1.5)
    else:
        ax.set_ylim(0, max(counts) * 1.10)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    fig.text(0.01, 0.015, note, ha="left", va="bottom", fontsize=9)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_descending_cumulative(
    path: Path,
    labels: list[str],
    counts: list[int],
    note: str,
) -> tuple[list[str], list[int]]:
    """Plot reverse cumulative /16 counts, starting from the largest node bins."""
    descending_labels = list(reversed(labels))
    descending_bin_counts = list(reversed(counts))
    cumulative_counts: list[int] = []
    running_total = 0
    for count in descending_bin_counts:
        running_total += count
        cumulative_counts.append(running_total)

    fig, ax = plt.subplots(figsize=(18, 7.5))
    x = list(range(len(descending_labels)))
    ax.plot(x, cumulative_counts, color="#377eb8", marker="o", markersize=3.5, linewidth=2)
    ax.set_xticks(x, descending_labels, rotation=60, ha="right", fontsize=9)
    ax.set_title(
        "WIDE 2025-12：/16サブツリーノード数の大きい順からの累積（線形軸）",
        fontsize=17,
        pad=14,
    )
    ax.set_xlabel("/16サブツリーのノード数の階級（大きい順→小さい順）")
    ax.set_ylabel("その階級以上を持つ累積 /16 区画数")
    ax.set_ylim(0, cumulative_counts[-1] * 1.08)
    ax.grid(axis="y", alpha=0.24)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    fig.text(0.01, 0.015, note, ha="left", va="bottom", fontsize=9)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return descending_labels, cumulative_counts


def plot_descending_cumulative_percent(
    path: Path,
    labels: list[str],
    cumulative_counts: list[int],
    total: int,
    note: str,
) -> list[float]:
    """Plot reverse cumulative counts as a percentage of the node-present subtrees."""
    percentages = [count / total * 100 for count in cumulative_counts]
    fig, ax = plt.subplots(figsize=(18, 7.5))
    x = list(range(len(labels)))
    ax.plot(x, percentages, color="#377eb8", marker="o", markersize=3.5, linewidth=2)
    ax.set_xticks(x, labels, rotation=60, ha="right", fontsize=9)
    ax.set_title(
        "WIDE 2025-12：/16サブツリーノード数の大きい順からの累積割合（0–100%、線形軸）",
        fontsize=17,
        pad=14,
    )
    ax.set_xlabel("/16サブツリーのノード数の階級（大きい順→小さい順）")
    ax.set_ylabel("その階級以上を持つ /16 区画の累積割合")
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10), [f"{value}%" for value in range(0, 101, 10)])
    ax.grid(axis="y", alpha=0.24)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(rect=(0, 0.16, 1, 1))
    fig.text(0.01, 0.015, note, ha="left", va="bottom", fontsize=9)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return percentages


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "Noto Sans CJK JP",
        "font.size": 12,
        "axes.unicode_minus": False,
    })

    datasets: list[dict[str, object]] = []
    maximum = 0
    for label, rule in RULES:
        nodes, covered, explicit_16_only = load_prefix16_counts(rule)
        covered_values = [count for count, is_covered in zip(nodes, covered) if is_covered]
        values = [count for count in covered_values if count > 0]
        maximum = max(maximum, max(values))
        datasets.append({
            "label": label,
            "rule": rule.name,
            "values": values,
            "covered": len(covered_values),
            "zero": sum(value == 0 for value in covered_values),
            "with_nodes": len(values),
            "explicit_16_only": explicit_16_only,
            "uncovered": len(covered) - len(covered_values),
            "max": max(values),
        })

    labels, _ = histogram([], maximum)
    csv_rows: list[dict[str, object]] = []
    for dataset in datasets:
        _, counts = histogram(dataset["values"], maximum)
        dataset["counts"] = counts
        note = (
            f"注: /16ルートのみ（ノード数1に含む）={dataset['explicit_16_only']:,}、"
            f"/1–/15集約のみ（ノード数0のため図外）={dataset['zero']:,}、"
            f"非デフォルト経路なし（図外）={dataset['uncovered']:,}"
        )
        for bin_name, count in zip(labels, counts):
            csv_rows.append({
                "routing_table": dataset["label"],
                "rule_file": dataset["rule"],
                "node_count_bin": bin_name,
                "prefix16_count": count,
                "node_present_prefix16_total": dataset["with_nodes"],
            })
        plot_single(
            args.output_dir / f"wide_{dataset['label']}_prefix16_child_histogram.png",
            f"WIDE {dataset['label']} ルーティング表：/16サブツリーのノード数分布（ノード数≥1のみ、n={dataset['with_nodes']:,}）",
            labels,
            counts,
            note,
        )
        plot_single(
            args.output_dir / f"wide_{dataset['label']}_prefix16_child_histogram_log.png",
            f"WIDE {dataset['label']} ルーティング表：/16サブツリーのノード数分布（ノード数≥1のみ、対数軸、n={dataset['with_nodes']:,}）",
            labels,
            counts,
            note,
            log_scale=True,
        )
        if dataset["label"] == "2025-12":
            plot_single(
                args.output_dir / "wide_2025-12_prefix16_child_histogram_linear.png",
                f"WIDE 2025-12 ルーティング表：/16サブツリーのノード数分布（線形軸、ノード数≥1のみ、n={dataset['with_nodes']:,}）",
                labels,
                counts,
                note,
            )
            cumulative_labels, cumulative_counts = plot_descending_cumulative(
                args.output_dir / "wide_2025-12_prefix16_child_histogram_descending_cumulative.png",
                labels,
                counts,
                note,
            )
            cumulative_percentages = plot_descending_cumulative_percent(
                args.output_dir / "wide_2025-12_prefix16_child_histogram_descending_cumulative_percent.png",
                cumulative_labels,
                cumulative_counts,
                dataset["with_nodes"],
                note,
            )
            with (args.output_dir / "wide_2025-12_prefix16_child_histogram_descending_cumulative.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["node_count_bin_descending", "prefix16_count", "cumulative_prefix16_count"],
                )
                writer.writeheader()
                for bin_name, bin_count, cumulative_count in zip(
                    cumulative_labels,
                    reversed(counts),
                    cumulative_counts,
                ):
                    writer.writerow({
                        "node_count_bin_descending": bin_name,
                        "prefix16_count": bin_count,
                        "cumulative_prefix16_count": cumulative_count,
                    })
            with (args.output_dir / "wide_2025-12_prefix16_child_histogram_descending_cumulative_percent.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "node_count_bin_descending",
                        "prefix16_count",
                        "cumulative_prefix16_count",
                        "cumulative_prefix16_percent",
                    ],
                )
                writer.writeheader()
                for bin_name, bin_count, cumulative_count, cumulative_percent in zip(
                    cumulative_labels,
                    reversed(counts),
                    cumulative_counts,
                    cumulative_percentages,
                ):
                    writer.writerow({
                        "node_count_bin_descending": bin_name,
                        "prefix16_count": bin_count,
                        "cumulative_prefix16_count": cumulative_count,
                        "cumulative_prefix16_percent": f"{cumulative_percent:.6f}",
                    })

    fig, ax = plt.subplots(figsize=(19, 8))
    x = list(range(len(labels)))
    width = 0.39
    colors = ("#777777", "#377eb8")
    for offset, dataset, color in zip((-width / 2, width / 2), datasets, colors):
        ax.bar(
            [value + offset for value in x],
            dataset["counts"],
            width,
            color=color,
            label=f"WIDE {dataset['label']} (n={dataset['with_nodes']:,})",
        )
    ax.set_xticks(x, labels, rotation=60, ha="right", fontsize=9)
    style_axis(ax, "WIDEルーティング表：/16サブツリーのノード数分布（/16自身を含む、ノード数≥1のみ）")
    ax.legend(frameon=False)
    comparison_note = (
        f"注（2025-09 / 2025-12）: /16ルートのみ（ノード数1に含む）="
        f"{datasets[0]['explicit_16_only']:,} / {datasets[1]['explicit_16_only']:,}; "
        f"/1–/15集約のみ（ノード数0、図外）={datasets[0]['zero']:,} / {datasets[1]['zero']:,}; "
        f"非デフォルト経路なし（図外）={datasets[0]['uncovered']:,} / {datasets[1]['uncovered']:,}"
    )
    fig.tight_layout(rect=(0, 0.14, 1, 1))
    fig.text(0.01, 0.015, comparison_note, ha="left", va="bottom", fontsize=9)
    fig.savefig(args.output_dir / "wide_prefix16_child_histogram_comparison.png", dpi=200, bbox_inches="tight")
    ax.set_yscale("log")
    ax.set_ylim(0.8, max(max(dataset["counts"]) for dataset in datasets) * 1.5)
    ax.set_title("WIDEルーティング表：/16サブツリーのノード数分布（/16自身を含む、ノード数≥1のみ、対数軸）", fontsize=17, pad=14)
    fig.savefig(args.output_dir / "wide_prefix16_child_histogram_comparison_log.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    with (args.output_dir / "wide_prefix16_child_histogram.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)

    with (args.output_dir / "summary.csv").open("w", newline="") as handle:
        fields = ["routing_table", "rule_file", "covered_prefix16", "zero_nodes", "with_nodes", "explicit_16_only", "uncovered_prefix16", "max_nodes"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for dataset in datasets:
            writer.writerow({
                "routing_table": dataset["label"],
                "rule_file": dataset["rule"],
                "covered_prefix16": dataset["covered"],
                "zero_nodes": dataset["zero"],
                "with_nodes": dataset["with_nodes"],
                "explicit_16_only": dataset["explicit_16_only"],
                "uncovered_prefix16": dataset["uncovered"],
                "max_nodes": dataset["max"],
            })


if __name__ == "__main__":
    main()
