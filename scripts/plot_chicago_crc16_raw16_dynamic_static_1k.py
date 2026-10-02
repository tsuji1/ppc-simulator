#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
# ]
# ///
"""Plot packet-weighted and unique-IP set distributions for a trace.

The input CSV is produced by cmd/export_crc16_raw16_set_distribution from the
same MinPacket GOB used by the simulator.  Dynamic counts every packet;
static counts every distinct destination IP once.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path
from typing import Any

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
MODES = {
    "dynamic": {
        "short": "Dynamic（packet重み付き）",
        "unit": "packet数",
        "columns": {
            "crc16": "dynamic_crc16_packets",
            "raw16": "dynamic_raw16_packets",
        },
    },
    "static": {
        "short": "Static（unique IP・重みなし）",
        "unit": "unique宛先IP数",
        "columns": {
            "crc16": "static_crc16_unique_ips",
            "raw16": "static_raw16_unique_ips",
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot CRC32(/16) vs raw-/16 set distributions."
    )
    parser.add_argument(
        "--input",
        default=(
            "scripts/reports/chicago_crc16_raw16_dynamic_static_1k/"
            "set_distribution.csv"
        ),
    )
    parser.add_argument(
        "--hit-csv",
        default=(
            "scripts/reports/chicago_crc16_raw16_set_hits_1k/"
            "set_hit_counts.csv"
        ),
        help="optional DB-derived CSV used to verify dynamic access counts",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/chicago_crc16_raw16_dynamic_static_1k",
    )
    parser.add_argument("--capacity", type=int, default=1024)
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--processed", type=int, default=6_338_755)
    parser.add_argument(
        "--trace",
        default="equinix-chicago.dirB.20140320-140100.UTC.anon.pcap",
    )
    parser.add_argument("--dataset-label", default="Chicago匿名")
    return parser.parse_args()


def configure_japanese_font() -> None:
    candidates = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic", "IPAexGothic"]
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def read_distribution(path: Path) -> tuple[list[int], dict[str, dict[str, list[int]]]]:
    set_ids: list[int] = []
    values = {
        mode: {method: [] for method in METHODS}
        for mode in MODES
    }
    with path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            set_ids.append(int(row["set_id"]))
            for mode, config in MODES.items():
                columns = config["columns"]
                assert isinstance(columns, dict)
                for method in METHODS:
                    values[mode][method].append(int(row[columns[method]]))
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


def metrics(values: list[int]) -> dict[str, float | int]:
    total = sum(values)
    mean = statistics.fmean(values) if values else 0.0
    stddev = statistics.pstdev(values) if values else 0.0
    top_count = max(1, math.ceil(len(values) * 0.125))
    return {
        "total": total,
        "active_sets": sum(value > 0 for value in values),
        "max": max(values, default=0),
        "max_share_percent": max(values, default=0) / total * 100.0 if total else 0.0,
        "gini": gini(values),
        "cv": stddev / mean if mean else 0.0,
        "top_12_5_share_percent": (
            sum(sorted(values, reverse=True)[:top_count]) / total * 100.0
            if total
            else 0.0
        ),
    }


def conclusion(mode: str, mode_values: dict[str, list[int]]) -> str:
    stats = {method: metrics(mode_values[method]) for method in METHODS}
    if mode == "dynamic":
        return (
            "上位16 setの合計はほぼ同じ"
            f"（{stats['crc16']['top_12_5_share_percent']:.2f}% 対 "
            f"{stats['raw16']['top_12_5_share_percent']:.2f}%）。"
            f"最大set占有率はCRC {stats['crc16']['max_share_percent']:.2f}% 対 "
            f"{stats['raw16']['max_share_percent']:.2f}%）"
        )
    return (
        "分散度はほぼ同じ："
        f"Gini {stats['crc16']['gini']:.3f} 対 {stats['raw16']['gini']:.3f}、"
        f"最大set {stats['crc16']['max_share_percent']:.2f}% 対 "
        f"{stats['raw16']['max_share_percent']:.2f}%"
    )


def plot_by_set(
    path: Path,
    mode: str,
    set_ids: list[int],
    mode_values: dict[str, list[int]],
    dataset_label: str,
) -> None:
    config = MODES[mode]
    unit = str(config["unit"])
    max_value = max(max(mode_values[method]) for method in METHODS)
    fig, axes = plt.subplots(2, 1, figsize=(14.2, 7.6), sharex=True, sharey=True)
    for axis, method in zip(axes, METHODS):
        values = mode_values[method]
        stat = metrics(values)
        axis.bar(set_ids, values, width=0.88, color=COLORS[method], edgecolor="none")
        axis.set_ylim(0, max_value * 1.06)
        axis.set_ylabel(unit)
        axis.grid(True, axis="y", alpha=0.22)
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{int(value):,}"))
        axis.set_title(
            f"{METHOD_LABELS[method]}：Gini {stat['gini']:.3f}｜"
            f"最大set占有率 {stat['max_share_percent']:.2f}%｜"
            f"上位16 set {stat['top_12_5_share_percent']:.2f}%",
            loc="left",
            fontsize=12,
            fontweight="bold",
        )
    axes[-1].set_xlabel("set番号（0〜127）")
    ticks = list(range(0, len(set_ids), 8)) + [len(set_ids) - 1]
    axes[-1].set_xticks(sorted(set(ticks)))
    fig.suptitle(
        f"{dataset_label}・Unified 1K・8-way｜{config['short']}\n"
        f"{conclusion(mode, mode_values)}",
        fontsize=16.5,
        fontweight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.012,
        "注：同じset番号でも、CRCとrawが収容する/16 prefixは一致しない。set番号別の局所的な偏りを見る図。",
        ha="center",
        fontsize=10.5,
        color="#465A65",
    )
    fig.tight_layout(rect=(0.025, 0.05, 0.995, 0.91))
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def plot_dynamic_static_by_set(
    path: Path,
    set_ids: list[int],
    distributions: dict[str, dict[str, list[int]]],
    dataset_label: str,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(15.2, 8.4), sharex=True)
    for row, mode in enumerate(MODES):
        row_max = max(max(distributions[mode][method]) for method in METHODS)
        for col, method in enumerate(METHODS):
            axis = axes[row][col]
            values = distributions[mode][method]
            stat = metrics(values)
            axis.bar(
                set_ids,
                values,
                width=0.88,
                color=COLORS[method],
                edgecolor="none",
            )
            axis.set_ylim(0, row_max * 1.08)
            axis.grid(True, axis="y", alpha=0.22)
            axis.yaxis.set_major_formatter(
                FuncFormatter(lambda value, _pos: f"{int(value):,}")
            )
            axis.text(
                0.995,
                0.94,
                f"Gini {stat['gini']:.3f}｜最大 {stat['max_share_percent']:.2f}%｜"
                f"上位16 set {stat['top_12_5_share_percent']:.2f}%",
                transform=axis.transAxes,
                ha="right",
                va="top",
                fontsize=9.7,
                color="#34495E",
            )
            if row == 0:
                axis.set_title(METHOD_LABELS[method], fontsize=13, fontweight="bold")
            if col == 0:
                axis.set_ylabel(
                    f"{MODES[mode]['short']}：{MODES[mode]['unit']}",
                    fontweight="bold",
                )
            if row == 1:
                axis.set_xlabel("set番号（0〜127）")
                ticks = list(range(0, len(set_ids), 16)) + [len(set_ids) - 1]
                axis.set_xticks(sorted(set(ticks)))
    fig.suptitle(
        f"{dataset_label}・Unified 1K・8-way（128 sets）｜Dynamic / Static のset別分布\n"
        "Dynamic＝packet頻度を含む　Static＝各unique宛先IPを1回だけ数える",
        fontsize=16,
        fontweight="bold",
        y=0.995,
    )
    fig.text(
        0.5,
        0.012,
        "注：Staticはrouting prefix数やcache entry数ではない。同じset番号でもCRCとrawが収容する/16は一致しない。",
        ha="center",
        fontsize=10.5,
        color="#465A65",
    )
    fig.tight_layout(rect=(0.04, 0.05, 0.995, 0.91))
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def plot_ranked(
    path: Path,
    distributions: dict[str, dict[str, list[int]]],
    dataset_label: str,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(13.6, 7.6))
    width = 0.42
    for axis, mode in zip(axes, MODES):
        ranks = list(range(1, len(distributions[mode]["crc16"]) + 1))
        for offset, method in ((-width / 2, "crc16"), (width / 2, "raw16")):
            ordered = sorted(distributions[mode][method], reverse=True)
            axis.bar(
                [rank + offset for rank in ranks],
                ordered,
                width=width,
                color=COLORS[method],
                label=METHOD_LABELS[method],
                edgecolor="none",
            )
        axis.set_title(
            f"{MODES[mode]['short']}：{conclusion(mode, distributions[mode])}",
            loc="left",
            fontsize=12,
            fontweight="bold",
        )
        axis.set_ylabel(str(MODES[mode]["unit"]))
        axis.set_xlim(0, len(ranks) + 1)
        axis.set_xticks([1, 16, 32, 48, 64, 80, 96, 112, 128])
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{int(value):,}"))
        axis.grid(True, axis="y", alpha=0.23)
        axis.legend(frameon=False, fontsize=10)
    axes[-1].set_xlabel("負荷の大きい順のset順位（1＝最多）")
    fig.suptitle(
        f"{dataset_label}：set番号を外してCRC32(/16)と/16 rawを比較",
        fontsize=16.5,
        fontweight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.012,
        "Dynamicは人気IPの影響を含み、StaticはIPアドレス集合そのものの広がりを示す。",
        ha="center",
        fontsize=10.5,
        color="#465A65",
    )
    fig.tight_layout(rect=(0.025, 0.05, 0.995, 0.93))
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def verify_against_hit_csv(
    hit_csv: Path,
    dynamic: dict[str, list[int]],
) -> dict[str, Any]:
    result: dict[str, Any] = {"available": hit_csv.exists()}
    if not hit_csv.exists():
        return result
    hit_columns = {"crc16": "crc16_hits", "raw16": "raw16_hits"}
    hits = {method: [] for method in METHODS}
    with hit_csv.open(newline="") as fp:
        for row in csv.DictReader(fp):
            for method in METHODS:
                hits[method].append(int(row[hit_columns[method]]))
    for method in METHODS:
        miss_counts = [
            dynamic[method][index] - hits[method][index]
            for index in range(len(dynamic[method]))
        ]
        result[method] = {
            "all_sets_nonnegative": all(count >= 0 for count in miss_counts),
            "packets": sum(dynamic[method]),
            "hits": sum(hits[method]),
            "misses": sum(miss_counts),
        }
    return result


def write_summary(
    path: Path,
    args: argparse.Namespace,
    distributions: dict[str, dict[str, list[int]]],
    verification: dict[str, Any],
) -> None:
    lines = [
        f"# {args.dataset_label} CRC32(/16) vs /16 raw: dynamic and static set distribution",
        "",
        f"- trace: `{args.trace}`",
        f"- processed packets: {sum(distributions['dynamic']['crc16']):,}",
        f"- unique destination IPs: {sum(distributions['static']['crc16']):,}",
        f"- capacity: {args.capacity:,} entries",
        f"- way: {args.way}",
        f"- sets: {args.capacity // args.way}",
        "- CRC32(/16): CRC32 of the zero-extended top 16 address bits, modulo 128",
        "- /16 raw: lower 7 bits of /16 = IPv4 bit positions 10..16 (one-based from MSB)",
        "- dynamic: every packet contributes one count",
        "- static: every distinct destination IP contributes one count, irrespective of packet frequency",
        "- these are set-input distributions, not hit counts",
        "",
        "| population | method | total | active sets | max-set share | Gini | CV | top 12.5% share |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        for method in METHODS:
            stat = metrics(distributions[mode][method])
            lines.append(
                f"| {MODES[mode]['short']} | {METHOD_LABELS[method]} | "
                f"{stat['total']:,} | {stat['active_sets']} | "
                f"{stat['max_share_percent']:.6f}% | {stat['gini']:.6f} | "
                f"{stat['cv']:.6f} | {stat['top_12_5_share_percent']:.6f}% |"
            )
    lines.extend(["", "## Cross-check against DB-derived per-set hit counters", ""])
    if verification.get("available"):
        for method in METHODS:
            item = verification[method]
            lines.append(
                f"- {METHOD_LABELS[method]}: every set satisfies packet count >= hit count = "
                f"{item['all_sets_nonnegative']}; packets {item['packets']:,} - "
                f"hits {item['hits']:,} = misses {item['misses']:,}"
            )
    else:
        lines.append("- hit-count CSV was not available; consistency check was skipped")
    lines.append(
        "- The DB first-/second-miss arrays are per-prefix diagnostics and are not mutually exclusive packet counts, so they are not added to hits here."
    )
    lines.extend(
        [
            "",
            "## Reading the figures",
            "",
            "- The by-set figures expose individual hot sets, but set IDs are not paired across methods.",
            "- The ranked figure compares the load-distribution shape after removing the arbitrary set labels.",
            "- Dynamic includes traffic popularity; static isolates how the observed unique destination-IP space maps to sets.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    if args.capacity <= 0 or args.way <= 0 or args.capacity % args.way:
        raise ValueError("capacity must be a positive multiple of way")
    expected_sets = args.capacity // args.way
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    set_ids, distributions = read_distribution(input_path)
    if len(set_ids) != expected_sets:
        raise ValueError(f"got {len(set_ids)} sets; expected {expected_sets}")
    dynamic_total = sum(distributions["dynamic"]["crc16"])
    if dynamic_total != args.processed:
        raise ValueError(f"counted {dynamic_total:,} packets; expected {args.processed:,}")
    for mode in MODES:
        if sum(distributions[mode]["crc16"]) != sum(distributions[mode]["raw16"]):
            raise ValueError(f"{mode}: CRC and raw totals differ")

    configure_japanese_font()
    plot_by_set(
        output_dir / "dynamic_packet_weighted_by_set.png",
        "dynamic",
        set_ids,
        distributions["dynamic"],
        args.dataset_label,
    )
    plot_by_set(
        output_dir / "static_unique_ip_by_set.png",
        "static",
        set_ids,
        distributions["static"],
        args.dataset_label,
    )
    plot_ranked(
        output_dir / "dynamic_static_ranked.png", distributions, args.dataset_label
    )
    plot_dynamic_static_by_set(
        output_dir / "dynamic_static_by_set.png",
        set_ids,
        distributions,
        args.dataset_label,
    )
    verification = verify_against_hit_csv(Path(args.hit_csv), distributions["dynamic"])
    write_summary(output_dir / "SUMMARY.md", args, distributions, verification)

    print(output_dir / "SUMMARY.md")
    print(output_dir / "dynamic_packet_weighted_by_set.png")
    print(output_dir / "static_unique_ip_by_set.png")
    print(output_dir / "dynamic_static_ranked.png")
    print(output_dir / "dynamic_static_by_set.png")


if __name__ == "__main__":
    main()
