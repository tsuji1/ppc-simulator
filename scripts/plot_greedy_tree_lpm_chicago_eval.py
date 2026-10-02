#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Compare Chicago original, global XOR, and exact tree-greedy transforms."""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


VIEWER = Path("/home/yuzugon/ppc-result-viewer")
if str(VIEWER) not in sys.path:
    sys.path.insert(0, str(VIEWER))

from scripts.cacti_exec import run_cacti  # type: ignore  # noqa: E402
from scripts.compare_fixed_config_cross_trace import (  # type: ignore  # noqa: E402
    FixedConfig,
    base_query,
    doc_matches_config,
    latest_doc,
)
from scripts.compare_multilayer_unified import (  # type: ignore  # noqa: E402
    configure_cacti_env,
    row_for_doc,
)


RULE = "route-views.chicago.rib.20160628.1400.unique.rule"
CONDITIONS = [
    ("Original", "equinix-chicago.dirB.20140320-140100.UTC.anon.pcap"),
    ("Global XOR", "2025-09-27.txt"),
    ("Greedy top-down", "chicago-to-2025-09-27-top-down-10m.txt"),
    ("Greedy bottom-up", "chicago-to-2025-09-27-bottom-up-10m.txt"),
]
TAG_LENGTH = tuple((9, 24) for _ in range(8))


def mp(series: str, refbits: tuple[int, int], capacities: tuple[int, int]) -> FixedConfig:
    return FixedConfig(series, "MultiLayerCacheExclusive", 2, capacities, refbits, 8, None, (), "", "", "")


def ps(series: str, index: int) -> FixedConfig:
    return FixedConfig(series, "UnifiedCache", 1, (8192,), (), 8, index, TAG_LENGTH, "exclusive", "", "")


CONFIGS = [
    mp("MP 24-16-2048-2048", (24, 16), (2048, 2048)),
    mp("MP 24-18-1024-1024", (24, 18), (1024, 1024)),
    mp("MP 24-18-2048-2048", (24, 18), (2048, 2048)),
    mp("MP 24-19-1024-2048", (24, 19), (1024, 2048)),
    mp("MP 24-20-2048-2048", (24, 20), (2048, 2048)),
    mp("MP 24-20-4096-4096", (24, 20), (4096, 4096)),
    ps("PS 16 8192", 16),
    ps("PS 18 8192", 18),
    ps("PS 20 8192", 20),
    ps("PS 22 8192", 22),
    ps("PS 24 8192", 24),
    ps("PS ideal 8192", 2),
]

REPORT_ROOT = Path("scripts/reports/greedy-tree-lpm/chicago/2025-09-27")
GLOBAL_ROOT = Path("scripts/reports/global-xor-lpm-tv-exhaustive24/chicago/2025-09-27")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--cacti-collection", default="cacti_results")
    parser.add_argument("--processed", type=int, default=6_338_755)
    parser.add_argument("--dram-pj-per-burst", type=float, default=4000)
    parser.add_argument("--output-dir", type=Path, default=Path("scripts/reports/greedy-tree-lpm/chicago/2025-09-27/evaluation"))
    parser.add_argument("--write-back", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    return parser.parse_args()


def collect(collection: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for condition_index, (condition, trace) in enumerate(CONDITIONS):
        for config_index, config in enumerate(CONFIGS):
            query = base_query(config, trace, RULE, args.processed)
            docs = [doc for doc in collection.find(query) if doc_matches_config(doc, config)]
            doc = latest_doc(docs)
            if doc is None:
                missing.append({"condition": condition, "trace_file_name": trace, "series": config.series, "reason": "not found"})
                continue
            try:
                row, updates = row_for_doc(doc, run_cacti, args)
            except Exception as exc:
                missing.append({"condition": condition, "trace_file_name": trace, "series": config.series, "reason": str(exc).replace("\n", " ")[:1000]})
                continue
            if args.write_back:
                collection.update_one({"_id": doc["_id"]}, {"$set": updates})
            rows.append(
                {
                    "condition_index": condition_index,
                    "condition": condition,
                    "trace_file_name": trace,
                    "config_index": config_index,
                    "series": config.series,
                    "hit_rate_percent": float(row["hitrate"]) * 100,
                    "miss_rate_percent": (1 - float(row["hitrate"])) * 100,
                    "power_mw": float(row["power_mw"]),
                    "throughput_gbps": float(row["throughput_gbps"]),
                    "source_id": row["id"],
                }
            )
    by_key = {(row["condition"], row["series"]): row for row in rows}
    for row in rows:
        original = by_key.get(("Original", row["series"]))
        if original is None:
            row["miss_rate_delta_vs_original_pp"] = ""
            row["power_delta_vs_original_mw"] = ""
        else:
            row["miss_rate_delta_vs_original_pp"] = float(row["miss_rate_percent"]) - float(original["miss_rate_percent"])
            row["power_delta_vs_original_mw"] = float(row["power_mw"]) - float(original["power_mw"])
    return rows, missing


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot(rows: list[dict[str, Any]], metric: str, ylabel: str, output: Path) -> None:
    by_key = {(int(row["condition_index"]), int(row["config_index"])): row for row in rows}
    colors = ["#6b7280", "#8b5cf6", "#2563eb", "#f59e0b"]
    x = list(range(len(CONFIGS)))
    width = 0.2
    fig, ax = plt.subplots(figsize=(18, 7.5))
    for condition_index, (condition, _) in enumerate(CONDITIONS):
        offset = (condition_index - 1.5) * width
        values = [float(by_key[(condition_index, index)][metric]) for index in x]
        ax.bar([index + offset for index in x], values, width=width * 0.94, label=condition, color=colors[condition_index])
    ax.set_xticks(x, [config.series for config in CONFIGS], rotation=32, ha="right")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=4)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def load_lpm_distributions() -> dict[str, dict[int, float]]:
    result: dict[str, dict[int, float]] = {name: {} for name in ("Target", "Original", "Global XOR", "Greedy top-down", "Greedy bottom-up")}
    with (REPORT_ROOT / "top-down/lpm_distribution_comparison.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            prefix = int(row["lpm_prefix_length"])
            result["Target"][prefix] = float(row["target_ratio"])
            if row["method"] == "baseline-anonymized":
                result["Original"][prefix] = float(row["ratio"])
            elif row["method"] == "greedy-full-top-down":
                result["Greedy top-down"][prefix] = float(row["ratio"])
    with (REPORT_ROOT / "bottom-up/lpm_distribution_comparison.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "greedy-full-bottom-up":
                result["Greedy bottom-up"][int(row["lpm_prefix_length"])] = float(row["ratio"])
    with (GLOBAL_ROOT / "lpm_distribution.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            result["Global XOR"][int(row["lpm_prefix_length"])] = float(row["after_percent"]) / 100
    return result


def write_lpm_outputs(distributions: dict[str, dict[int, float]], output_dir: Path) -> dict[str, float]:
    target = distributions["Target"]
    tv = {
        condition: 0.5 * sum(abs(values.get(prefix, 0) - target.get(prefix, 0)) for prefix in range(33))
        for condition, values in distributions.items()
        if condition != "Target"
    }
    with (output_dir / "lpm_tv_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["condition", "tv_distance", "relative_reduction_vs_original"])
        for condition in ("Original", "Global XOR", "Greedy top-down", "Greedy bottom-up"):
            reduction = 1 - tv[condition] / tv["Original"]
            writer.writerow([condition, f"{tv[condition]:.12f}", f"{reduction:.12f}"])

    colors = {"Target": "#111827", "Original": "#6b7280", "Global XOR": "#8b5cf6", "Greedy top-down": "#2563eb", "Greedy bottom-up": "#f59e0b"}
    styles = {"Target": "-", "Original": "--", "Global XOR": "-.", "Greedy top-down": "-", "Greedy bottom-up": ":"}
    fig, ax = plt.subplots(figsize=(13, 7))
    for condition, values in distributions.items():
        label = condition if condition == "Target" else f"{condition} (TV={tv[condition]:.3f})"
        ax.plot(range(33), [values.get(prefix, 0) * 100 for prefix in range(33)], label=label, color=colors[condition], linestyle=styles[condition], linewidth=2.2)
    ax.set_xticks(range(33), [f"/{prefix}" for prefix in range(33)], rotation=55, ha="right")
    ax.set_xlabel("Longest matching prefix length")
    ax.set_ylabel("Packet share (%)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(output_dir / "lpm_distribution_comparison.png", dpi=200)
    plt.close(fig)
    return tv


def write_summary(path: Path, rows: list[dict[str, Any]], tv: dict[str, float]) -> None:
    by_condition = {condition: [row for row in rows if row["condition"] == condition] for condition, _ in CONDITIONS}
    original = {row["series"]: row for row in by_condition["Original"]}
    lines = [
        "# Chicago → WIDE 2025-09: exact tree-greedy evaluation",
        "",
        "- packets: 6,338,755 valid IPv4 TCP/UDP packets (the whole Chicago trace; maximum was 10M)",
        "- routing table: `route-views.chicago.rib.20160628.1400.unique.rule`",
        "- target: WIDE 2025-09-27 LPM distribution",
        "- greedy passes: one; strict TV improvement only; active nodes `/0` through `/23`",
        "- cache configurations: six MP and six PS configurations, all 8-way",
        "- power model: DRAM 4,000 pJ/burst and 320.1 mW background",
        "",
        "## LPM TV distance",
        "",
        "| condition | TV | reduction vs original |",
        "| --- | ---: | ---: |",
    ]
    for condition in ("Original", "Global XOR", "Greedy top-down", "Greedy bottom-up"):
        reduction = 1 - tv[condition] / tv["Original"]
        lines.append(f"| {condition} | {tv[condition]:.6f} | {reduction * 100:.2f}% |")
    lines.extend(("", "## Cache and power summary", "", "| condition | mean miss rate | mean power | configs with lower miss than original | configs with lower power than original |", "| --- | ---: | ---: | ---: | ---: |"))
    for condition in ("Original", "Global XOR", "Greedy top-down", "Greedy bottom-up"):
        subset = by_condition[condition]
        mean_miss = statistics.mean(float(row["miss_rate_percent"]) for row in subset)
        mean_power = statistics.mean(float(row["power_mw"]) for row in subset)
        lower_miss = sum(float(row["miss_rate_percent"]) < float(original[row["series"]]["miss_rate_percent"]) for row in subset)
        lower_power = sum(float(row["power_mw"]) < float(original[row["series"]]["power_mw"]) for row in subset)
        lines.append(f"| {condition} | {mean_miss:.4f}% | {mean_power:.2f} mW | {lower_miss}/12 | {lower_power}/12 |")
    lines.extend(("", "The top-down traversal fits the target LPM distribution best, but that does not imply the best cache behavior. The bottom-up traversal has lower mean miss rate and power than top-down in this representative case. Results should therefore be compared per cache configuration, not inferred from TV alone.", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_cacti_env(args)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        rows, missing = collect(client[args.db][args.collection], args)
    finally:
        client.close()
    rows.sort(key=lambda row: (int(row["condition_index"]), int(row["config_index"])))
    fields = [
        "condition", "trace_file_name", "series", "hit_rate_percent", "miss_rate_percent",
        "miss_rate_delta_vs_original_pp", "power_mw", "power_delta_vs_original_mw",
        "throughput_gbps", "source_id",
    ]
    write_csv(args.output_dir / "cache_power_comparison.csv", rows, fields)
    write_csv(args.output_dir / "missing.csv", missing, ["condition", "trace_file_name", "series", "reason"])
    if not missing and rows:
        plot(rows, "miss_rate_percent", "Miss rate (%)", args.output_dir / "miss_rate_comparison.png")
        plot(rows, "power_mw", "Estimated total power (mW)", args.output_dir / "power_comparison.png")
        tv = write_lpm_outputs(load_lpm_distributions(), args.output_dir)
        write_summary(args.output_dir / "SUMMARY.md", rows, tv)
    print(f"rows={len(rows)} missing={len(missing)} output_dir={args.output_dir}")
    return 2 if missing and args.fail_on_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
