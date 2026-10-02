#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "matplotlib>=3.7",
#   "pymongo>=4.6",
# ]
# ///
"""Compare UnifiedCache CRC32(/16) and direct-/16 indexes for Chicago traces."""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


HASH16 = 16
DIRECT16 = 116


@dataclass(frozen=True)
class Config:
    rule_file_name: str
    size: int
    way: int
    processed: int
    cache_tag_length: str
    insertion_policy: str

    @property
    def sets(self) -> int:
        return self.size // self.way

    @property
    def index_bits(self) -> int:
        return int(math.log2(self.sets))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find paired Chicago UnifiedCache results for cache index type 16 "
            "(CRC32 of the leading /16) and 116 (direct /16), then write a "
            "seven-trace comparison table and plot."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--rule-regex", default="chicago")
    parser.add_argument("--trace-regex", default="chicago")
    parser.add_argument("--capacity", type=int)
    parser.add_argument("--way", type=int)
    parser.add_argument("--processed", type=int)
    parser.add_argument("--limit-days", type=int, default=7)
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/chicago_hash16_vs_direct16",
    )
    parser.add_argument("--timeout-ms", type=int, default=10_000)
    return parser.parse_args()


def nested_get(value: Any, path: Iterable[str], default: Any = None) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def normalize_tag_length(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ";".join(
            "-".join(str(part) for part in item) if isinstance(item, list) else str(item)
            for item in value
        )
    return str(value)


def trace_label(trace_file_name: str) -> str:
    name = Path(trace_file_name).name
    match = re.search(r"(20\d{6})(?:[-_]?(\d{6}))?", name)
    if not match:
        return name
    date = match.group(1)
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}"


def decode_counter_rows(binary_value: Any, rows: int) -> list[list[int]]:
    if not binary_value or rows <= 0:
        return []
    payload = bytes(binary_value)
    raw = gzip.decompress(payload)
    expected = rows * 32 * 4
    if len(raw) != expected:
        raise ValueError(f"counter bytes {len(raw)} != expected {expected}")
    values = struct.unpack(f"<{rows * 32}I", raw)
    return [list(values[index * 32 : (index + 1) * 32]) for index in range(rows)]


def gini(values: list[int]) -> float:
    nonnegative = sorted(max(0, int(value)) for value in values)
    total = sum(nonnegative)
    if not nonnegative or total == 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(nonnegative))
    count = len(nonnegative)
    return (2 * weighted) / (count * total) - (count + 1) / count


def set_metrics(doc: dict[str, Any]) -> dict[str, float | int]:
    rows = int(doc.get("unified_stat_rows") or 0)
    hit_rows = decode_counter_rows(doc.get("hit_count_list_compressed"), rows)
    first_rows = decode_counter_rows(doc.get("first_miss_count_compressed"), rows)
    second_rows = decode_counter_rows(doc.get("second_miss_count_compressed"), rows)
    if not hit_rows:
        return {
            "active_sets": 0,
            "max_access_share_percent": 0.0,
            "access_gini": 0.0,
            "second_miss_total": 0,
        }
    access_by_set = [
        sum(hit_rows[index]) + sum(first_rows[index]) + sum(second_rows[index])
        for index in range(rows)
    ]
    total = sum(access_by_set)
    return {
        "active_sets": sum(value > 0 for value in access_by_set),
        "max_access_share_percent": (max(access_by_set) / total * 100.0) if total else 0.0,
        "access_gini": gini(access_by_set),
        "second_miss_total": sum(sum(row) for row in second_rows),
    }


def latest_pairs(collection, args: argparse.Namespace):
    query: dict[str, Any] = {
        "simulator_result.type": "UnifiedCache",
        "simulator_result.parameter.cacheindextype": {"$in": [HASH16, DIRECT16]},
        "rule_file_name": {"$regex": args.rule_regex, "$options": "i"},
        "trace_file_name": {"$regex": args.trace_regex, "$options": "i"},
    }
    if args.capacity is not None:
        query["simulator_result.parameter.size"] = args.capacity
    if args.way is not None:
        query["simulator_result.parameter.way"] = args.way
    if args.processed is not None:
        query["simulator_result.processed"] = args.processed

    projection = {
        "timestamp": 1,
        "rule_file_name": 1,
        "trace_file_name": 1,
        "unified_stat_rows": 1,
        "hit_count_list_compressed": 1,
        "first_miss_count_compressed": 1,
        "second_miss_count_compressed": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter": 1,
    }

    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    doc_counts: defaultdict[tuple[Any, ...], int] = defaultdict(int)
    for doc in collection.find(query, projection):
        parameter = nested_get(doc, ("simulator_result", "parameter"), {})
        index_type = int(parameter.get("cacheindextype", -1))
        config = Config(
            rule_file_name=str(doc.get("rule_file_name", "")),
            size=int(parameter.get("size", 0)),
            way=int(parameter.get("way", 0)),
            processed=int(nested_get(doc, ("simulator_result", "processed"), 0)),
            cache_tag_length=normalize_tag_length(
                parameter.get("cachetaglength", parameter.get("cache_tag_length"))
            ),
            insertion_policy=str(
                parameter.get("insertionpolicy", parameter.get("insertion_policy", ""))
            ),
        )
        key = (str(doc.get("trace_file_name", "")), config, index_type)
        doc_counts[key] += 1
        if key not in latest or doc.get("timestamp") > latest[key].get("timestamp"):
            latest[key] = doc

    grouped: defaultdict[Config, dict[str, dict[int, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for (trace, config, index_type), doc in latest.items():
        grouped[config][trace][index_type] = doc

    paired_by_config: dict[Config, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    for config, trace_docs in grouped.items():
        pairs = []
        for trace, by_index in trace_docs.items():
            if HASH16 in by_index and DIRECT16 in by_index:
                pairs.append((trace, by_index[HASH16], by_index[DIRECT16]))
        if pairs:
            pairs.sort(key=lambda item: (trace_label(item[0]), item[0]))
            paired_by_config[config] = pairs
    return paired_by_config, doc_counts


def choose_config(
    paired_by_config: dict[Config, list[tuple[str, dict[str, Any], dict[str, Any]]]]
) -> Config:
    if not paired_by_config:
        raise RuntimeError("no paired hash16/direct16 Chicago results found")
    return max(
        paired_by_config,
        key=lambda config: (
            min(len(paired_by_config[config]), 7),
            len(paired_by_config[config]),
            config.processed,
            config.size,
            -config.way,
        ),
    )


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    collection = client[args.db][args.collection]
    paired_by_config, doc_counts = latest_pairs(collection, args)
    config = choose_config(paired_by_config)
    pairs = paired_by_config[config]
    if args.limit_days > 0:
        pairs = pairs[: args.limit_days]

    rows: list[dict[str, Any]] = []
    for trace, hash_doc, direct_doc in pairs:
        hash_rate = float(nested_get(hash_doc, ("simulator_result", "hitrate"), 0.0)) * 100.0
        direct_rate = float(nested_get(direct_doc, ("simulator_result", "hitrate"), 0.0)) * 100.0
        hash_metrics = set_metrics(hash_doc)
        direct_metrics = set_metrics(direct_doc)
        rows.append(
            {
                "day": trace_label(trace),
                "trace_file_name": trace,
                "hash16_hitrate_percent": hash_rate,
                "direct16_hitrate_percent": direct_rate,
                "hash_minus_direct_pp": hash_rate - direct_rate,
                "hash16_active_sets": hash_metrics["active_sets"],
                "direct16_active_sets": direct_metrics["active_sets"],
                "hash16_max_access_share_percent": hash_metrics[
                    "max_access_share_percent"
                ],
                "direct16_max_access_share_percent": direct_metrics[
                    "max_access_share_percent"
                ],
                "hash16_access_gini": hash_metrics["access_gini"],
                "direct16_access_gini": direct_metrics["access_gini"],
                "hash16_second_miss_total": hash_metrics["second_miss_total"],
                "direct16_second_miss_total": direct_metrics["second_miss_total"],
            }
        )

    csv_path = output_dir / "chicago_hash16_vs_direct16_7days.csv"
    with csv_path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    labels = [row["day"] for row in rows]
    hash_rates = [row["hash16_hitrate_percent"] for row in rows]
    direct_rates = [row["direct16_hitrate_percent"] for row in rows]
    deltas = [row["hash_minus_direct_pp"] for row in rows]
    x = list(range(len(rows)))

    fig, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(11, 7),
        gridspec_kw={"height_ratios": [3, 1.35]},
        sharex=True,
    )
    top.plot(x, hash_rates, marker="o", linewidth=2.4, label="CRC32 of leading /16")
    top.plot(
        x,
        direct_rates,
        marker="s",
        linewidth=2.2,
        linestyle="--",
        label=f"direct /16: use lower {config.index_bits} bits",
    )
    margin = max(0.2, (max(hash_rates + direct_rates) - min(hash_rates + direct_rates)) * 0.2)
    top.set_ylim(min(hash_rates + direct_rates) - margin, max(hash_rates + direct_rates) + margin)
    top.set_ylabel("hit rate (%)")
    top.set_title("Chicago: CRC32(/16) and direct-/16 hit rates")
    top.grid(True, alpha=0.25)
    top.legend(loc="best")

    colors = ["#2f6fb0" if value >= 0 else "#d45a4f" for value in deltas]
    bottom.bar(x, deltas, color=colors)
    bottom.axhline(0.0, color="#333333", linewidth=0.8)
    bottom.set_ylabel("CRC − direct\n(pp)")
    bottom.set_xticks(x, labels, rotation=25, ha="right")
    bottom.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    png_path = output_dir / "chicago_hash16_vs_direct16_7days.png"
    fig.savefig(png_path, dpi=180)
    plt.close(fig)

    abs_deltas = [abs(value) for value in deltas]
    summary_path = output_dir / "SUMMARY.md"
    lines = [
        "# Chicago CRC32(/16) vs direct-/16",
        "",
        f"- rule: `{config.rule_file_name}`",
        f"- capacity: {config.size} entries",
        f"- way: {config.way}",
        f"- sets: {config.sets}",
        f"- direct index bits: lower {config.index_bits} bits of the leading /16",
        f"- processed: {config.processed}",
        f"- cache tag length: `{config.cache_tag_length}`",
        f"- insertion policy: `{config.insertion_policy}`",
        f"- paired traces used: {len(rows)}",
        f"- maximum absolute hit-rate difference: {max(abs_deltas):.6f} pp",
        f"- mean absolute hit-rate difference: {sum(abs_deltas) / len(abs_deltas):.6f} pp",
        "",
        "| day | CRC32(/16) | direct-/16 | delta (pp) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['day']} | {row['hash16_hitrate_percent']:.6f}% | "
            f"{row['direct16_hitrate_percent']:.6f}% | "
            f"{row['hash_minus_direct_pp']:+.6f} |"
        )
    lines.extend(
        [
            "",
            "## Available paired configurations",
            "",
            "| paired traces | capacity | way | sets | processed | tag length | insertion | rule |",
            "| ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for candidate, candidate_pairs in sorted(
        paired_by_config.items(),
        key=lambda item: (-len(item[1]), -item[0].processed, -item[0].size),
    ):
        lines.append(
            f"| {len(candidate_pairs)} | {candidate.size} | {candidate.way} | "
            f"{candidate.sets} | {candidate.processed} | "
            f"`{candidate.cache_tag_length}` | `{candidate.insertion_policy}` | "
            f"`{candidate.rule_file_name}` |"
        )
    summary_path.write_text("\n".join(lines) + "\n")
    print(summary_path)
    print(csv_path)
    print(png_path)


if __name__ == "__main__":
    main()
