#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
#   "pymongo>=4.6",
# ]
# ///
"""Compare CRC and designated-bit UnifiedCache index methods for /16 and /24.

The default datasets are the Chicago trace used in the presentation and the
anonymized WIDE trace from 2025-09-27. Results are read from MongoDB; this
script never inserts or updates simulator documents.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


CRC16 = 16
DIRECT16 = 116
CRC24 = 24
DIRECT24 = 124
INDEX_TYPES = (CRC16, DIRECT16, CRC24, DIRECT24)
INDEX_LABELS = {
    CRC16: "CRC32（先頭16 bit）",
    DIRECT16: "/16の指定bit",
    CRC24: "CRC32（先頭24 bit）",
    DIRECT24: "/24の指定bit",
}


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    rule_file_name: str
    trace_file_name: str
    processed: int


DATASETS = (
    Dataset(
        key="chicago",
        label="Chicago（匿名）",
        rule_file_name="route-views.chicago.rib.20160628.1400.unique.rule",
        trace_file_name="equinix-chicago.dirB.20140320-140100.UTC.anon.pcap",
        processed=6_338_755,
    ),
    Dataset(
        key="wide_202509",
        label="WIDE 2025-09-27（匿名）",
        rule_file_name="rib.20250927.0600.unique.rule",
        trace_file_name="202509271400.pcap",
        processed=10_000_000,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read paired UnifiedCache CRC16/direct-/16 and CRC24/direct-/24 "
            "hit rates for anonymized Chicago and WIDE 2025-09-27 traces, "
            "then write a CSV, figure, and summary."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--start-exp", type=int, default=10)
    parser.add_argument("--end-exp", type=int, default=15)
    parser.add_argument("--tag-min", type=int, default=9)
    parser.add_argument("--tag-max", type=int, default=24)
    parser.add_argument("--insertion-policy", default="exclusive")
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument(
        "--output-dir",
        default=(
            "scripts/reports/"
            "crc16_direct16_crc24_direct24_chicago_wide202509_anon"
        ),
    )
    return parser.parse_args()


def nested_get(value: Any, *path: str, default: Any = None) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def normalized_tag_ranges(parameter: dict[str, Any]) -> tuple[tuple[int, int], ...]:
    raw = parameter.get("cachetaglength", parameter.get("cache_tag_length", []))
    if not isinstance(raw, list):
        return ()
    ranges: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            return ()
        ranges.append((int(item[0]), int(item[1])))
    return tuple(ranges)


def tag_ranges_match(
    parameter: dict[str, Any], expected: tuple[int, int], way: int
) -> bool:
    ranges = normalized_tag_ranges(parameter)
    if not ranges:
        return False
    # The simulator accepts one shared range or one identical range per way.
    return len(ranges) in (1, way) and all(item == expected for item in ranges)


def fetch_latest(
    collection,
    dataset: Dataset,
    capacities: list[int],
    args: argparse.Namespace,
) -> dict[tuple[int, int], dict[str, Any]]:
    query = {
        "simulator_result.type": "UnifiedCache",
        "rule_file_name": dataset.rule_file_name,
        "trace_file_name": dataset.trace_file_name,
        "simulator_result.processed": dataset.processed,
        "simulator_result.parameter.way": args.way,
        "simulator_result.parameter.size": {"$in": capacities},
        "simulator_result.parameter.cacheindextype": {"$in": list(INDEX_TYPES)},
    }
    projection = {
        "timestamp": 1,
        "rule_file_name": 1,
        "trace_file_name": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter": 1,
    }

    expected_tag = (args.tag_min, args.tag_max)
    latest: dict[tuple[int, int], dict[str, Any]] = {}
    for doc in collection.find(query, projection):
        parameter = nested_get(doc, "simulator_result", "parameter", default={})
        if not isinstance(parameter, dict):
            continue
        insertion = parameter.get(
            "insertionpolicy", parameter.get("insertion_policy", "")
        )
        if insertion != args.insertion_policy:
            continue
        if not tag_ranges_match(parameter, expected_tag, args.way):
            continue

        key = (int(parameter["cacheindextype"]), int(parameter["size"]))
        if key not in latest or doc.get("timestamp") > latest[key].get("timestamp"):
            latest[key] = doc
    return latest


def require_complete(
    dataset: Dataset,
    latest: dict[tuple[int, int], dict[str, Any]],
    capacities: list[int],
) -> None:
    missing = [
        (index_type, capacity)
        for index_type in INDEX_TYPES
        for capacity in capacities
        if (index_type, capacity) not in latest
    ]
    if missing:
        formatted = ", ".join(
            f"index={index_type},capacity={capacity}"
            for index_type, capacity in missing
        )
        raise RuntimeError(f"{dataset.label}: missing results: {formatted}")


def hitrate_percent(doc: dict[str, Any]) -> float:
    return float(nested_get(doc, "simulator_result", "hitrate", default=0.0)) * 100.0


def direct_bit_range(
    prefix_length: int, capacity: int, way: int
) -> tuple[int, int, int]:
    sets = capacity // way
    index_bits = int(math.log2(sets))
    # Human-facing numbering is one-based from the IPv4 MSB.
    return prefix_length - index_bits + 1, prefix_length, index_bits


def write_csv(
    path: Path,
    all_latest: dict[str, dict[tuple[int, int], dict[str, Any]]],
    capacities: list[int],
    args: argparse.Namespace,
) -> None:
    fields = [
        "dataset",
        "dataset_label",
        "rule_file_name",
        "trace_file_name",
        "processed",
        "capacity",
        "capacity_label",
        "way",
        "sets",
        "direct16_bit_start_one_based",
        "direct16_bit_end_one_based",
        "direct24_bit_start_one_based",
        "direct24_bit_end_one_based",
        "direct_index_bits",
        "crc16_hitrate_percent",
        "direct16_hitrate_percent",
        "crc24_hitrate_percent",
        "direct24_hitrate_percent",
        "crc16_minus_direct_pp",
        "crc24_minus_direct24_pp",
    ]
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for dataset in DATASETS:
            latest = all_latest[dataset.key]
            for capacity in capacities:
                crc16 = hitrate_percent(latest[(CRC16, capacity)])
                direct16 = hitrate_percent(latest[(DIRECT16, capacity)])
                crc24 = hitrate_percent(latest[(CRC24, capacity)])
                direct24 = hitrate_percent(latest[(DIRECT24, capacity)])
                bit16_start, bit16_end, index_bits = direct_bit_range(
                    16, capacity, args.way
                )
                bit24_start, bit24_end, _ = direct_bit_range(
                    24, capacity, args.way
                )
                writer.writerow(
                    {
                        "dataset": dataset.key,
                        "dataset_label": dataset.label,
                        "rule_file_name": dataset.rule_file_name,
                        "trace_file_name": dataset.trace_file_name,
                        "processed": dataset.processed,
                        "capacity": capacity,
                        "capacity_label": f"{capacity // 1024}K",
                        "way": args.way,
                        "sets": capacity // args.way,
                        "direct16_bit_start_one_based": bit16_start,
                        "direct16_bit_end_one_based": bit16_end,
                        "direct24_bit_start_one_based": bit24_start,
                        "direct24_bit_end_one_based": bit24_end,
                        "direct_index_bits": index_bits,
                        "crc16_hitrate_percent": f"{crc16:.6f}",
                        "direct16_hitrate_percent": f"{direct16:.6f}",
                        "crc24_hitrate_percent": f"{crc24:.6f}",
                        "direct24_hitrate_percent": f"{direct24:.6f}",
                        "crc16_minus_direct_pp": f"{crc16 - direct16:+.6f}",
                        "crc24_minus_direct24_pp": (
                            f"{crc24 - direct24:+.6f}"
                        ),
                    }
                )


def configure_japanese_font() -> None:
    candidates = [
        "Noto Sans CJK JP",
        "Noto Sans JP",
        "Yu Gothic",
        "IPAexGothic",
        "DejaVu Sans",
    ]
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def plot_results(
    path: Path,
    all_latest: dict[str, dict[tuple[int, int], dict[str, Any]]],
    capacities: list[int],
) -> None:
    configure_japanese_font()
    labels = [f"{capacity // 1024}K" for capacity in capacities]
    x = list(range(len(capacities)))
    colors = {
        CRC16: "#2F6FB0",
        DIRECT16: "#E6862D",
        CRC24: "#2E8B57",
        DIRECT24: "#8A5BA7",
    }
    markers = {CRC16: "o", DIRECT16: "s", CRC24: "^", DIRECT24: "D"}
    linestyles = {CRC16: "-", DIRECT16: "--", CRC24: "-", DIRECT24: "--"}

    fig = plt.figure(figsize=(15.4, 6.2))
    grid = fig.add_gridspec(
        2,
        2,
        height_ratios=[3.2, 1.15],
        hspace=0.18,
        wspace=0.16,
        left=0.055,
        right=0.985,
        top=0.88,
        bottom=0.12,
    )
    top_axes = [fig.add_subplot(grid[0, col]) for col in range(2)]
    delta_axes = [fig.add_subplot(grid[1, col], sharex=top_axes[col]) for col in range(2)]

    for col, dataset in enumerate(DATASETS):
        latest = all_latest[dataset.key]
        hit_values: dict[int, list[float]] = {
            index_type: [
                hitrate_percent(latest[(index_type, capacity)])
                for capacity in capacities
            ]
            for index_type in INDEX_TYPES
        }
        axis = top_axes[col]
        for index_type in INDEX_TYPES:
            axis.plot(
                x,
                hit_values[index_type],
                color=colors[index_type],
                marker=markers[index_type],
                linestyle=linestyles[index_type],
                linewidth=2.5,
                markersize=6,
                label=INDEX_LABELS[index_type],
            )
        all_rates = [value for values in hit_values.values() for value in values]
        margin = max(0.35, (max(all_rates) - min(all_rates)) * 0.08)
        axis.set_ylim(min(all_rates) - margin, min(100.0, max(all_rates) + margin))
        axis.set_title(dataset.label, fontsize=16, fontweight="bold", pad=8)
        axis.set_ylabel("ヒット率（%）" if col == 0 else "")
        axis.grid(True, alpha=0.24)
        axis.tick_params(axis="x", labelbottom=False)

        delta16 = [
            hit_values[CRC16][index] - hit_values[DIRECT16][index]
            for index in range(len(capacities))
        ]
        delta24 = [
            hit_values[CRC24][index] - hit_values[DIRECT24][index]
            for index in range(len(capacities))
        ]
        delta_axis = delta_axes[col]
        width = 0.34
        delta_axis.bar(
            [value - width / 2 for value in x],
            delta16,
            color="#4A80BD",
            width=width,
            label="CRC16 − /16指定bit",
        )
        delta_axis.bar(
            [value + width / 2 for value in x],
            delta24,
            color="#6C9A6A",
            width=width,
            label="CRC24 − /24指定bit",
        )
        delta_axis.axhline(0.0, color="#333333", linewidth=0.8)
        max_abs = max(abs(value) for value in delta16 + delta24)
        limit = max(0.022, max_abs * 1.35)
        delta_axis.set_ylim(-limit, limit)
        delta_axis.set_ylabel("CRC − 指定bit\n（point）" if col == 0 else "")
        delta_axis.set_xticks(x, labels)
        delta_axis.grid(True, axis="y", alpha=0.2)
        delta_axis.tick_params(labelsize=10)
        for offset, values in ((-width / 2, delta16), (width / 2, delta24)):
            for index, value in enumerate(values):
                vertical = 4 if value >= 0 else -10
                delta_axis.annotate(
                    f"{value:+.3f}",
                    (index + offset, value),
                    xytext=(0, vertical),
                    textcoords="offset points",
                    ha="center",
                    va="bottom" if value >= 0 else "top",
                    fontsize=8,
                )

    handles, legend_labels = top_axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        legend_labels,
        loc="upper center",
        ncol=4,
        frameon=False,
        fontsize=12,
        bbox_to_anchor=(0.52, 0.995),
    )
    fig.text(
        0.5,
        0.025,
        "総エントリ数（8-way）",
        ha="center",
        fontsize=12,
    )
    fig.savefig(path, dpi=180, facecolor="white")
    plt.close(fig)


def write_summary(
    path: Path,
    all_latest: dict[str, dict[tuple[int, int], dict[str, Any]]],
    capacities: list[int],
    args: argparse.Namespace,
) -> None:
    lines = [
        "# CRC16/direct-/16 and CRC24/direct-/24 hit-rate comparison",
        "",
        f"- way: {args.way}",
        f"- capacities: {capacities[0]}..{capacities[-1]} entries",
        f"- tag: /{args.tag_min}../{args.tag_max} on every way",
        f"- insertion: {args.insertion_policy}",
        "- designated-bit numbering: one-based from the IPv4 MSB",
        "",
    ]
    for dataset in DATASETS:
        latest = all_latest[dataset.key]
        delta16 = [
            hitrate_percent(latest[(CRC16, capacity)])
            - hitrate_percent(latest[(DIRECT16, capacity)])
            for capacity in capacities
        ]
        delta24 = [
            hitrate_percent(latest[(CRC24, capacity)])
            - hitrate_percent(latest[(DIRECT24, capacity)])
            for capacity in capacities
        ]
        lines.extend(
            [
                f"## {dataset.label}",
                "",
                f"- rule: `{dataset.rule_file_name}`",
                f"- trace: `{dataset.trace_file_name}`",
                f"- processed: {dataset.processed:,}",
                f"- max |CRC16 - direct-/16|: {max(abs(value) for value in delta16):.6f} point",
                f"- max |CRC24 - direct-/24|: {max(abs(value) for value in delta24):.6f} point",
                "",
                "| capacity | /16 designated bits | /24 designated bits | CRC16 | /16 bits | CRC24 | /24 bits | CRC16-/16 | CRC24-/24 |",
                "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for capacity in capacities:
            crc16 = hitrate_percent(latest[(CRC16, capacity)])
            direct16 = hitrate_percent(latest[(DIRECT16, capacity)])
            crc24 = hitrate_percent(latest[(CRC24, capacity)])
            direct24 = hitrate_percent(latest[(DIRECT24, capacity)])
            bit16_start, bit16_end, index_bits = direct_bit_range(
                16, capacity, args.way
            )
            bit24_start, bit24_end, _ = direct_bit_range(
                24, capacity, args.way
            )
            lines.append(
                f"| {capacity // 1024}K | 第{bit16_start}〜{bit16_end}bit "
                f"({index_bits}bit) | 第{bit24_start}〜{bit24_end}bit "
                f"({index_bits}bit) | {crc16:.6f}% | {direct16:.6f}% | "
                f"{crc24:.6f}% | {direct24:.6f}% | "
                f"{crc16 - direct16:+.6f} | {crc24 - direct24:+.6f} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    if args.start_exp > args.end_exp:
        raise ValueError("--start-exp must be <= --end-exp")
    capacities = [1 << exponent for exponent in range(args.start_exp, args.end_exp + 1)]
    if any((capacity // args.way) & ((capacity // args.way) - 1) for capacity in capacities):
        raise ValueError("every capacity/way set count must be a power of two")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    collection = client[args.db][args.collection]

    all_latest: dict[str, dict[tuple[int, int], dict[str, Any]]] = {}
    for dataset in DATASETS:
        latest = fetch_latest(collection, dataset, capacities, args)
        require_complete(dataset, latest, capacities)
        all_latest[dataset.key] = latest

    csv_path = output_dir / "crc16_direct16_crc24_direct24_by_capacity.csv"
    figure_path = output_dir / "crc16_direct16_crc24_direct24_by_capacity.png"
    summary_path = output_dir / "SUMMARY.md"
    write_csv(csv_path, all_latest, capacities, args)
    plot_results(figure_path, all_latest, capacities)
    write_summary(summary_path, all_latest, capacities, args)

    print(summary_path)
    print(csv_path)
    print(figure_path)


if __name__ == "__main__":
    main()
