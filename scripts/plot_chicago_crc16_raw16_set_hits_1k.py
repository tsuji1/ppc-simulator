#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
#   "pymongo>=4.6",
# ]
# ///
"""Plot per-set hit counts for Chicago CRC32(/16) and raw-/16 indexing.

The script reads the latest exact-condition UnifiedCache documents from
MongoDB.  It does not run the simulator or update the database.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import statistics
import struct
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from pymongo import MongoClient


CRC16 = 16
RAW16 = 116
INDEX_LABELS = {
    CRC16: "CRC32（先頭16 bit）",
    RAW16: "/16 raw（第10〜16 bit）",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read exact-condition Chicago UnifiedCache 1K/8-way results from "
            "MongoDB and plot hit counts for each of the 128 sets."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument(
        "--rule-file-name",
        default="route-views.chicago.rib.20160628.1400.unique.rule",
    )
    parser.add_argument(
        "--trace-file-name",
        default="equinix-chicago.dirB.20140320-140100.UTC.anon.pcap",
    )
    parser.add_argument("--processed", type=int, default=6_338_755)
    parser.add_argument("--capacity", type=int, default=1024)
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--tag-min", type=int, default=9)
    parser.add_argument("--tag-max", type=int, default=24)
    parser.add_argument("--insertion-policy", default="exclusive")
    parser.add_argument("--index-policy", default="fixed")
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/chicago_crc16_raw16_set_hits_1k",
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


def parameter_matches(parameter: dict[str, Any], args: argparse.Namespace) -> bool:
    expected_tag = (args.tag_min, args.tag_max)
    ranges = normalized_tag_ranges(parameter)
    if len(ranges) not in (1, args.way) or any(item != expected_tag for item in ranges):
        return False
    insertion = parameter.get(
        "insertionpolicy", parameter.get("insertion_policy", "")
    )
    if insertion != args.insertion_policy:
        return False
    index_policy = parameter.get("indexpolicy", parameter.get("index_policy", "fixed"))
    return index_policy == args.index_policy


def fetch_latest_documents(collection, args: argparse.Namespace) -> dict[int, dict[str, Any]]:
    query = {
        "simulator_result.type": "UnifiedCache",
        "rule_file_name": args.rule_file_name,
        "trace_file_name": args.trace_file_name,
        "simulator_result.processed": args.processed,
        "simulator_result.parameter.size": args.capacity,
        "simulator_result.parameter.way": args.way,
        "simulator_result.parameter.cacheindextype": {"$in": [CRC16, RAW16]},
    }
    projection = {
        "timestamp": 1,
        "rule_file_name": 1,
        "trace_file_name": 1,
        "unified_stat_encoding": 1,
        "unified_stat_rows": 1,
        "hit_count_list_compressed": 1,
        "first_miss_count_compressed": 1,
        "second_miss_count_compressed": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.hit": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter": 1,
        "simulator_result.statdetail.cachelinehitcount": 1,
        "simulator_result.statdetail.CachelineHitCount": 1,
        "simulator_result.statdetail.cachelinefirstmisscount": 1,
        "simulator_result.statdetail.CachelineFirstMissCount": 1,
        "simulator_result.statdetail.cachelinesecondmisscount": 1,
        "simulator_result.statdetail.CachelineSecondMissCount": 1,
    }
    latest: dict[int, dict[str, Any]] = {}
    for doc in collection.find(query, projection):
        parameter = nested_get(doc, "simulator_result", "parameter", default={})
        if not isinstance(parameter, dict) or not parameter_matches(parameter, args):
            continue
        index_type = int(parameter["cacheindextype"])
        if index_type not in latest or doc.get("timestamp") > latest[index_type].get(
            "timestamp"
        ):
            latest[index_type] = doc
    missing = [index_type for index_type in (CRC16, RAW16) if index_type not in latest]
    if missing:
        raise RuntimeError(f"missing exact-condition documents for index types: {missing}")
    return latest


def decode_compressed_rows(blob: Any, rows: int, field_name: str) -> list[list[int]]:
    if blob is None:
        return []
    raw = gzip.decompress(bytes(blob))
    expected = rows * 32 * 4
    if len(raw) != expected:
        raise ValueError(
            f"{field_name}: decompressed {len(raw)} bytes; expected {expected}"
        )
    values = struct.unpack(f"<{rows * 32}I", raw)
    return [list(values[i * 32 : (i + 1) * 32]) for i in range(rows)]


def legacy_rows(doc: dict[str, Any], lower: str, upper: str) -> list[list[int]]:
    stat = nested_get(doc, "simulator_result", "statdetail", default={})
    if not isinstance(stat, dict):
        return []
    value = stat.get(lower, stat.get(upper, []))
    return [[int(item) for item in row] for row in value] if value else []


def counter_rows(
    doc: dict[str, Any], compressed_field: str, legacy_lower: str, legacy_upper: str
) -> list[list[int]]:
    rows = int(doc.get("unified_stat_rows") or 0)
    compressed = doc.get(compressed_field)
    if compressed is not None:
        return decode_compressed_rows(compressed, rows, compressed_field)
    return legacy_rows(doc, legacy_lower, legacy_upper)


def per_set_counts(doc: dict[str, Any]) -> dict[str, list[int]]:
    hit_rows = counter_rows(
        doc,
        "hit_count_list_compressed",
        "cachelinehitcount",
        "CachelineHitCount",
    )
    first_rows = counter_rows(
        doc,
        "first_miss_count_compressed",
        "cachelinefirstmisscount",
        "CachelineFirstMissCount",
    )
    second_rows = counter_rows(
        doc,
        "second_miss_count_compressed",
        "cachelinesecondmisscount",
        "CachelineSecondMissCount",
    )
    if not hit_rows or len(hit_rows) != len(first_rows) or len(hit_rows) != len(second_rows):
        raise ValueError("hit/first-miss/second-miss row counts do not match")
    hits = [sum(row) for row in hit_rows]
    first = [sum(row) for row in first_rows]
    second = [sum(row) for row in second_rows]
    accesses = [hits[i] + first[i] + second[i] for i in range(len(hits))]
    return {"hits": hits, "first_misses": first, "second_misses": second, "accesses": accesses}


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
        "top_12_5_share_percent": sum(sorted(values, reverse=True)[:top_count]) / total * 100.0
        if total
        else 0.0,
    }


def configure_japanese_font() -> None:
    candidates = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic", "IPAexGothic"]
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def plot_by_set(
    path: Path,
    counts: dict[int, dict[str, list[int]]],
    db_hitrates: dict[int, float],
) -> None:
    configure_japanese_font()
    set_ids = list(range(len(counts[CRC16]["hits"])))
    colors = {CRC16: "#2F6FB0", RAW16: "#E6862D"}
    max_hit = max(max(counts[index]["hits"]) for index in (CRC16, RAW16))
    fig, axes = plt.subplots(2, 1, figsize=(14.2, 7.6), sharex=True, sharey=True)
    for axis, index_type in zip(axes, (CRC16, RAW16)):
        values = counts[index_type]["hits"]
        stat = metrics(values)
        axis.bar(set_ids, values, width=0.88, color=colors[index_type], edgecolor="none")
        axis.set_ylim(0, max_hit * 1.06)
        axis.set_ylabel("ヒット数")
        axis.grid(True, axis="y", alpha=0.22)
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{int(value):,}"))
        axis.set_title(
            f"{INDEX_LABELS[index_type]}：全体ヒット率 {db_hitrates[index_type]:.6f}% "
            f"｜Gini {stat['gini']:.3f}｜最大set占有率 {stat['max_share_percent']:.2f}%",
            loc="left",
            fontsize=12,
            fontweight="bold",
        )
    axes[-1].set_xlabel("set番号（0〜127）")
    ticks = list(range(0, len(set_ids), 8)) + [len(set_ids) - 1]
    axes[-1].set_xticks(sorted(set(ticks)))
    delta = db_hitrates[CRC16] - db_hitrates[RAW16]
    fig.suptitle(
        "Chicago匿名・Unified 1K・8-way：setごとのヒット数\n"
        f"CRC32(/16) − /16 raw = {delta:+.6f} point",
        fontsize=17,
        fontweight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.012,
        "注：index関数が異なるため、同じset番号でも収容する/16 prefixは一致しない。棒の形は負荷分散の比較に用いる。",
        ha="center",
        fontsize=10.5,
        color="#465A65",
    )
    fig.tight_layout(rect=(0.025, 0.05, 0.995, 0.93))
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def plot_ranked(path: Path, counts: dict[int, dict[str, list[int]]]) -> None:
    configure_japanese_font()
    colors = {CRC16: "#2F6FB0", RAW16: "#E6862D"}
    ranks = list(range(1, len(counts[CRC16]["hits"]) + 1))
    fig, axis = plt.subplots(figsize=(12.8, 5.9))
    width = 0.42
    for offset, index_type in ((-width / 2, CRC16), (width / 2, RAW16)):
        values = sorted(counts[index_type]["hits"], reverse=True)
        axis.bar(
            [rank + offset for rank in ranks],
            values,
            width=width,
            color=colors[index_type],
            label=INDEX_LABELS[index_type],
            edgecolor="none",
        )
    axis.set_title("set別ヒット数を多い順に並べた分布", fontsize=16, fontweight="bold")
    axis.set_xlabel("ヒット数順位（1＝最も多いset）")
    axis.set_ylabel("ヒット数")
    axis.set_xlim(0, len(ranks) + 1)
    axis.set_xticks([1, 16, 32, 48, 64, 80, 96, 112, 128])
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{int(value):,}"))
    axis.grid(True, axis="y", alpha=0.23)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def write_csv(path: Path, counts: dict[int, dict[str, list[int]]]) -> None:
    fields = [
        "set_id",
        "crc16_hits",
        "raw16_hits",
        "crc16_hit_share_percent",
        "raw16_hit_share_percent",
        "crc16_first_misses",
        "raw16_first_misses",
        "crc16_second_misses",
        "raw16_second_misses",
        "crc16_accesses",
        "raw16_accesses",
        "crc16_local_hitrate_percent",
        "raw16_local_hitrate_percent",
    ]
    totals = {index: sum(counts[index]["hits"]) for index in (CRC16, RAW16)}
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for set_id in range(len(counts[CRC16]["hits"])):
            row: dict[str, Any] = {"set_id": set_id}
            for prefix, index_type in (("crc16", CRC16), ("raw16", RAW16)):
                hits = counts[index_type]["hits"][set_id]
                accesses = counts[index_type]["accesses"][set_id]
                row[f"{prefix}_hits"] = hits
                row[f"{prefix}_hit_share_percent"] = (
                    f"{hits / totals[index_type] * 100.0:.9f}"
                    if totals[index_type]
                    else "0.000000000"
                )
                row[f"{prefix}_first_misses"] = counts[index_type]["first_misses"][set_id]
                row[f"{prefix}_second_misses"] = counts[index_type]["second_misses"][set_id]
                row[f"{prefix}_accesses"] = accesses
                row[f"{prefix}_local_hitrate_percent"] = (
                    f"{hits / accesses * 100.0:.9f}" if accesses else ""
                )
            writer.writerow(row)


def write_summary(
    path: Path,
    args: argparse.Namespace,
    docs: dict[int, dict[str, Any]],
    counts: dict[int, dict[str, list[int]]],
    db_hitrates: dict[int, float],
) -> None:
    lines = [
        "# Chicago CRC32(/16) vs /16 raw: per-set hits",
        "",
        f"- rule: `{args.rule_file_name}`",
        f"- trace: `{args.trace_file_name}`",
        f"- processed: {args.processed:,}",
        f"- capacity: {args.capacity:,} entries",
        f"- way: {args.way}",
        f"- sets: {args.capacity // args.way}",
        f"- tag: /{args.tag_min}../{args.tag_max}",
        f"- insertion: `{args.insertion_policy}`",
        f"- index policy: `{args.index_policy}`",
        "- raw-/16 at this capacity uses the lower 7 bits of /16, i.e. IPv4 bit positions 10..16 (one-based from MSB)",
        "- same set number across the two methods does not represent the same /16 prefixes",
        "",
        "| method | DB hit rate | total set hits | active sets | max-set share | Gini | CV | top 12.5% share | timestamp |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for index_type in (CRC16, RAW16):
        stat = metrics(counts[index_type]["hits"])
        lines.append(
            f"| {INDEX_LABELS[index_type]} | {db_hitrates[index_type]:.6f}% | "
            f"{stat['total']:,} | {stat['active_sets']} | "
            f"{stat['max_share_percent']:.6f}% | {stat['gini']:.6f} | "
            f"{stat['cv']:.6f} | {stat['top_12_5_share_percent']:.6f}% | "
            f"{docs[index_type].get('timestamp')} |"
        )
    lines.extend(
        [
            "",
            f"- CRC32(/16) - /16 raw hit-rate difference: {db_hitrates[CRC16] - db_hitrates[RAW16]:+.6f} point",
            f"- total hit-count difference: {sum(counts[CRC16]['hits']) - sum(counts[RAW16]['hits']):+,}",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    expected_sets = args.capacity // args.way
    if args.capacity % args.way != 0 or expected_sets <= 0:
        raise ValueError("capacity must be a positive multiple of way")
    if expected_sets & (expected_sets - 1):
        raise ValueError("set count must be a power of two for raw-/16 indexing")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    collection = client[args.db][args.collection]
    docs = fetch_latest_documents(collection, args)
    counts = {index: per_set_counts(docs[index]) for index in (CRC16, RAW16)}
    for index_type in (CRC16, RAW16):
        if len(counts[index_type]["hits"]) != expected_sets:
            raise ValueError(
                f"index {index_type}: got {len(counts[index_type]['hits'])} sets; "
                f"expected {expected_sets}"
            )
    db_hitrates = {
        index: float(nested_get(docs[index], "simulator_result", "hitrate", default=0.0))
        * 100.0
        for index in (CRC16, RAW16)
    }

    csv_path = output_dir / "set_hit_counts.csv"
    plot_path = output_dir / "set_hit_counts_by_set.png"
    ranked_path = output_dir / "set_hit_counts_ranked.png"
    summary_path = output_dir / "SUMMARY.md"
    write_csv(csv_path, counts)
    plot_by_set(plot_path, counts, db_hitrates)
    plot_ranked(ranked_path, counts)
    write_summary(summary_path, args, docs, counts, db_hitrates)
    print(summary_path)
    print(csv_path)
    print(plot_path)
    print(ranked_path)


if __name__ == "__main__":
    main()
