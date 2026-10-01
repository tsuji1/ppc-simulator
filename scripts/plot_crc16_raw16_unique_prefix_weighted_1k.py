#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
"""Plot distinct-/16 and packet-weighted set loads for CRC and raw indexing."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


METHODS = ("crc16", "raw16")
METHOD_LABELS = {
    "crc16": "CRC32（先頭16 bit）",
    "raw16": "/16 raw（第10〜16 bit）",
}
COLORS = {"crc16": "#2F6FB0", "raw16": "#E6862D"}
POPULATIONS = {
    "cache": {
        "title": "cache対象prefix（/9〜/24）のset分布",
        "unique_label": "ユニークcache prefix数",
        "weighted_label": "cache対象packet数（頻度重み付き）",
        "unique_columns": {
            "crc16": "static_crc16_unique_cache_prefixes",
            "raw16": "static_raw16_unique_cache_prefixes",
        },
        "weighted_columns": {
            "crc16": "cacheable_crc16_packets",
            "raw16": "cacheable_raw16_packets",
        },
        "footer": (
            "上段は同一setに現れたcache entry key（network, prefix長）を1回だけ数える。"
            "下段は各keyへのpacket数で重み付けする。"
        ),
        "ranked_footer": (
            "prefix種類数が近くても、少数の人気prefixにpacketが集中すると下段だけ大きく偏る。"
        ),
        "unique_definition": (
            "each distinct cache entry key (network, prefix length) observed in a set "
            "contributes one count; exclusive /9../24 semantics are applied"
        ),
        "weighted_definition": (
            "every packet with a cacheable routing prefix (/9../24) contributes one count"
        ),
    },
    "index16": {
        "title": "/16 index入力prefixのset分布",
        "unique_label": "ユニーク /16 prefix数",
        "weighted_label": "packet数（/16頻度で重み付き）",
        "unique_columns": {
            "crc16": "static_crc16_unique_prefix16s",
            "raw16": "static_raw16_unique_prefix16s",
        },
        "weighted_columns": {
            "crc16": "dynamic_crc16_packets",
            "raw16": "dynamic_raw16_packets",
        },
        "footer": (
            "上段は観測された各/16を1回だけ数える。"
            "下段はその/16宛てのpacket数で重み付けする。"
        ),
        "ranked_footer": (
            "ユニーク/16数が近くても、少数の人気prefixにpacketが集中すると下段だけ大きく偏る。"
        ),
        "unique_definition": "each observed destination /16 contributes one count",
        "weighted_definition": (
            "every packet contributes one count to its destination /16's set"
        ),
    },
}
METRICS: dict[str, dict[str, object]] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot per-set distinct-/16 and packet-weighted loads."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-label", default="WIDE非匿名 2025-09-27")
    parser.add_argument("--trace", default="2025-09-27.pcap")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--capacity", type=int, default=1024)
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument(
        "--prefix-population",
        choices=sorted(POPULATIONS),
        default="cache",
        help="count actual cache-entry prefixes or /16 index-input prefixes",
    )
    return parser.parse_args()


def configure_population(name: str) -> None:
    global METRICS
    population = POPULATIONS[name]
    METRICS = {
        "unique_prefix": {
            "label": population["unique_label"],
            "columns": population["unique_columns"],
        },
        "packet_weighted": {
            "label": population["weighted_label"],
            "columns": population["weighted_columns"],
        },
    }


def configure_japanese_font() -> None:
    candidates = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic", "IPAexGothic"]
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def read_values(path: Path) -> tuple[list[int], dict[str, dict[str, list[int]]]]:
    set_ids: list[int] = []
    values = {
        metric: {method: [] for method in METHODS}
        for metric in METRICS
    }
    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        fieldnames = set(reader.fieldnames or [])
        required = {
            column
            for config in METRICS.values()
            for column in config["columns"].values()
        } | {"set_id"}
        missing = sorted(required - fieldnames)
        if missing:
            raise ValueError(f"missing CSV columns: {', '.join(missing)}")
        for row in reader:
            set_ids.append(int(row["set_id"]))
            for metric, config in METRICS.items():
                for method, column in config["columns"].items():
                    values[metric][method].append(int(row[column]))
    if set_ids != list(range(len(set_ids))):
        raise ValueError("set_id must be consecutive from zero")
    return set_ids, values


def gini(values: list[int]) -> float:
    ordered = sorted(max(0, int(value)) for value in values)
    total = sum(ordered)
    count = len(ordered)
    if count == 0 or total == 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (count * total) - (count + 1) / count


def summary(values: list[int]) -> dict[str, float | int]:
    total = sum(values)
    top_count = max(1, math.ceil(len(values) * 0.125))
    return {
        "total": total,
        "max": max(values, default=0),
        "max_share": max(values, default=0) / total * 100 if total else 0.0,
        "gini": gini(values),
        "top16_share": (
            sum(sorted(values, reverse=True)[:top_count]) / total * 100
            if total
            else 0.0
        ),
    }


def pearson(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
    )
    left_square = sum((x - left_mean) ** 2 for x in left)
    right_square = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_square * right_square)
    return numerator / denominator if denominator else 0.0


def annotate_axis(axis: plt.Axes, values: list[int]) -> None:
    stat = summary(values)
    axis.text(
        0.995,
        0.94,
        f"Gini {stat['gini']:.3f}｜最大 {stat['max_share']:.2f}%｜上位16 set {stat['top16_share']:.2f}%",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=9.7,
        color="#34495E",
    )


def plot_by_set(
    path: Path,
    set_ids: list[int],
    values: dict[str, dict[str, list[int]]],
    args: argparse.Namespace,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(15.2, 8.3), sharex=True)
    for row, metric in enumerate(METRICS):
        row_max = max(max(values[metric][method]) for method in METHODS)
        for col, method in enumerate(METHODS):
            axis = axes[row][col]
            series = values[metric][method]
            axis.bar(
                set_ids,
                series,
                width=0.88,
                color=COLORS[method],
                edgecolor="none",
            )
            axis.set_ylim(0, row_max * 1.08)
            axis.grid(True, axis="y", alpha=0.22)
            axis.yaxis.set_major_formatter(
                FuncFormatter(lambda value, _pos: f"{int(value):,}")
            )
            annotate_axis(axis, series)
            if row == 0:
                axis.set_title(METHOD_LABELS[method], fontsize=13, fontweight="bold")
            if col == 0:
                axis.set_ylabel(str(METRICS[metric]["label"]))
            if row == 1:
                axis.set_xlabel("set番号（0〜127）")
                ticks = list(range(0, len(set_ids), 16)) + [len(set_ids) - 1]
                axis.set_xticks(sorted(set(ticks)))

    unique_crc = summary(values["unique_prefix"]["crc16"])
    unique_raw = summary(values["unique_prefix"]["raw16"])
    packet_crc = summary(values["packet_weighted"]["crc16"])
    packet_raw = summary(values["packet_weighted"]["raw16"])
    fig.suptitle(
        f"{args.dataset_label}・Unified 1K・8-way（128 sets）｜"
        f"{POPULATIONS[args.prefix_population]['title']}\n"
        f"ユニークprefixのGini: CRC {unique_crc['gini']:.3f} / raw {unique_raw['gini']:.3f}　"
        f"packet重み付き: CRC {packet_crc['gini']:.3f} / raw {packet_raw['gini']:.3f}",
        fontsize=16,
        fontweight="bold",
        y=0.995,
    )
    fig.text(
        0.5,
        0.012,
        f"{POPULATIONS[args.prefix_population]['footer']} "
        "対象は先頭1,000万valid packet。",
        ha="center",
        fontsize=10.5,
        color="#465A65",
    )
    fig.tight_layout(rect=(0.025, 0.05, 0.995, 0.91))
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def plot_ranked(
    path: Path,
    values: dict[str, dict[str, list[int]]],
    args: argparse.Namespace,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(14.2, 7.8))
    for axis, metric in zip(axes, METRICS):
        for method in METHODS:
            ordered = sorted(values[metric][method], reverse=True)
            ranks = list(range(1, len(ordered) + 1))
            axis.plot(
                ranks,
                ordered,
                color=COLORS[method],
                linewidth=2.2,
                label=METHOD_LABELS[method],
            )
        axis.set_ylabel(str(METRICS[metric]["label"]))
        axis.set_xlim(1, len(ranks))
        axis.set_xticks([1, 16, 32, 48, 64, 80, 96, 112, 128])
        axis.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _pos: f"{int(value):,}")
        )
        axis.grid(True, alpha=0.22)
        axis.legend(frameon=False, fontsize=10.5)
    axes[-1].set_xlabel("負荷の大きい順のset順位（1＝最多）")
    fig.suptitle(
        f"{args.dataset_label}：set番号を外した分布形状の比較",
        fontsize=16.5,
        fontweight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.012,
        str(POPULATIONS[args.prefix_population]["ranked_footer"]),
        ha="center",
        fontsize=10.5,
        color="#465A65",
    )
    fig.tight_layout(rect=(0.025, 0.05, 0.995, 0.94))
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def write_summary(
    path: Path,
    values: dict[str, dict[str, list[int]]],
    args: argparse.Namespace,
) -> None:
    lines = [
        f"# {args.dataset_label}: unique prefix and packet-weighted set load",
        "",
        f"- trace: `{args.trace}`",
        f"- population: first {args.processed:,} simulator-valid packets in trace order",
        "- simulator-valid: IPv4 TCP/UDP packets stored in the simulator MinPacket GOB",
        f"- capacity / way / sets: {args.capacity:,} / {args.way} / {args.capacity // args.way}",
        f"- unique prefix: {POPULATIONS[args.prefix_population]['unique_definition']}",
        f"- packet-weighted: {POPULATIONS[args.prefix_population]['weighted_definition']}",
        "",
        "| measure | method | total | max-set share | Gini | top 16-set share |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for metric in METRICS:
        for method in METHODS:
            stat = summary(values[metric][method])
            lines.append(
                f"| {METRICS[metric]['label']} | {METHOD_LABELS[method]} | "
                f"{stat['total']:,} | {stat['max_share']:.6f}% | "
                f"{stat['gini']:.6f} | {stat['top16_share']:.6f}% |"
            )
    lines.extend(["", "## Within-method association", ""])
    for method in METHODS:
        correlation = pearson(
            values["unique_prefix"][method],
            values["packet_weighted"][method],
        )
        lines.append(
            f"- {METHOD_LABELS[method]}: Pearson correlation between per-set "
            f"unique-prefix count and packet count = {correlation:.6f}"
        )
    lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    configure_population(args.prefix_population)
    if args.capacity <= 0 or args.way <= 0 or args.capacity % args.way:
        raise ValueError("capacity must be a positive multiple of way")
    set_ids, values = read_values(Path(args.input))
    expected_sets = args.capacity // args.way
    if len(set_ids) != expected_sets:
        raise ValueError(f"got {len(set_ids)} sets; expected {expected_sets}")
    if (
        sum(values["packet_weighted"]["crc16"])
        != sum(values["packet_weighted"]["raw16"])
    ):
        raise ValueError("packet-weighted CRC and raw totals differ")
    if args.prefix_population == "index16" and (
        sum(values["unique_prefix"]["crc16"])
        != sum(values["unique_prefix"]["raw16"])
    ):
        raise ValueError("index-/16 CRC and raw unique totals differ")
    weighted_total = sum(values["packet_weighted"]["crc16"])
    if args.prefix_population == "index16" and weighted_total != args.processed:
        raise ValueError("packet total does not match --processed")
    if args.prefix_population == "cache" and weighted_total > args.processed:
        raise ValueError("cacheable packet total exceeds --processed")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_japanese_font()
    plot_by_set(
        output_dir / "unique_prefix_and_packet_weighted_by_set.png",
        set_ids,
        values,
        args,
    )
    plot_ranked(
        output_dir / "unique_prefix_and_packet_weighted_ranked.png",
        values,
        args,
    )
    write_summary(output_dir / "PREFIX_METRICS.md", values, args)
    print(output_dir / "PREFIX_METRICS.md")
    print(output_dir / "unique_prefix_and_packet_weighted_by_set.png")
    print(output_dir / "unique_prefix_and_packet_weighted_ranked.png")


if __name__ == "__main__":
    main()
