#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Plot anonymous PS capacity sweeps with CACTI cycle-time-aware power."""

from __future__ import annotations

import argparse
import csv
import math
import os
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

from models.unifiedcache import UnifiedCacheResult, estimate_unified_power  # type: ignore  # noqa: E402
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


ROOT = Path(__file__).resolve().parent / "reports/global-xor-anon-ps-capacity32k-cycle-aware"
CAPACITIES = (1024, 2048, 4096, 8192, 16384, 32768)
INDEXES = (16, 18, 20, 22, 24, 2)
INDEX_LABELS = {16: "PS /16", 18: "PS /18", 20: "PS /20", 22: "PS /22", 24: "PS /24", 2: "PS ideal"}
COLORS = {16: "#6baed6", 18: "#3182bd", 20: "#08519c", 22: "#74c476", 24: "#238b45", 2: "#d7191c"}
TAG_LENGTH = tuple((9, 24) for _ in range(8))

TRACES = {
    "original": (
        "元匿名トレース",
        (
            ("San Jose", "equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap", "route-views.isc.rib.20140320.1400.unique.rule"),
            ("Chicago", "equinix-chicago.dirB.20140320-140100.UTC.anon.pcap", "route-views.chicago.rib.20160628.1400.unique.rule"),
            ("NYC", "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap", "rrc11.bview.20190117.1600.unique.rule"),
        ),
    ),
    "target-2025-09": (
        "2025-09非匿名LPM分布へのマッチング後",
        (
            ("San Jose", "2025-09-27.txt", "route-views.isc.rib.20140320.1400.unique.rule"),
            ("Chicago", "2025-09-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
            ("NYC", "2025-09-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
        ),
    ),
    "target-2025-12": (
        "2025-12非匿名LPM分布へのマッチング後",
        (
            ("San Jose", "2025-12-27.txt", "route-views.isc.rib.20140320.1400.unique.rule"),
            ("Chicago", "2025-12-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
            ("NYC", "2025-12-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
        ),
    ),
    "target-2026-03": (
        "2026-03非匿名LPM分布へのマッチング後",
        (
            ("San Jose", "2026-03-27.txt", "route-views.isc.rib.20140320.1400.unique.rule"),
            ("Chicago", "2026-03-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
            ("NYC", "2026-03-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--cacti-collection", default="cacti_results")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--dram-pj-per-burst", type=float, default=4000)
    parser.add_argument("--cpu-frequency-ghz", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--write-back-cacti", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    return parser.parse_args()


def fixed_config(index: int, capacity: int) -> FixedConfig:
    return FixedConfig(
        INDEX_LABELS[index], "UnifiedCache", 1, (capacity,), (), 8, index,
        TAG_LENGTH, "exclusive", "", "",
    )


def positive_float(value: Any, name: str) -> float:
    result = float(value)
    if result <= 0:
        raise ValueError(f"{name} must be positive, got {result}")
    return result


def cycle_aware_metrics(
    doc: dict[str, Any],
    cacti_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, float | int]:
    sim = doc["simulator_result"]
    unified = UnifiedCacheResult(sim)
    if unified.Processed <= 0:
        raise ValueError("processed must be positive")
    if not cacti_results:
        raise ValueError("CACTI result is missing")

    cpu_cycle_ns = 1.0 / args.cpu_frequency_ghz
    cacti_cycle_ns = max(positive_float(row["cycle_time"], "CACTI cycle_time") for row in cacti_results)
    cacti_access_ns = max(positive_float(row["access_time"], "CACTI access_time") for row in cacti_results)
    cache_cycles = max(1, math.ceil(cacti_cycle_ns / cpu_cycle_ns - 1e-12))
    access_latency_cycles = max(1, math.ceil(cacti_access_ns / cpu_cycle_ns - 1e-12))

    depth_average = unified.depth_average()
    remained_rate = unified.miss_count() / unified.Processed
    dram_average_cycles = remained_rate * depth_average * 8
    effective_cycles = max(float(cache_cycles), dram_average_cycles)
    throughput_gbps = args.cpu_frequency_ghz * 512 / effective_cycles
    power = estimate_unified_power(
        sim, cacti_results, throughput_gbps, depth_average, args.dram_pj_per_burst,
    )
    if power is None:
        raise ValueError("cycle-aware power calculation failed")
    return {
        "cpu_cycle_ns": cpu_cycle_ns,
        "cacti_cycle_time_ns": cacti_cycle_ns,
        "cacti_access_time_ns": cacti_access_ns,
        "cache_initiation_cycles": cache_cycles,
        "access_latency_cycles": access_latency_cycles,
        "dram_average_cycles": dram_average_cycles,
        "effective_cycles_per_packet": effective_cycles,
        "cycle_aware_throughput_gbps": throughput_gbps,
        "cycle_aware_power_mw": power["total_power"],
        "cycle_aware_dynamic_power_mw": power["dynamic_power"],
        "static_power_mw": power["static_energy"],
    }


def collect(collection: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for condition_index, (condition, (condition_label, traces)) in enumerate(TRACES.items()):
        for trace_index, (trace_label, trace, rule) in enumerate(traces):
            expected_processed = 6_338_755 if trace_label == "Chicago" else args.processed
            for index in INDEXES:
                for capacity in CAPACITIES:
                    config = fixed_config(index, capacity)
                    query = base_query(config, trace, rule, expected_processed)
                    docs = [doc for doc in collection.find(query) if doc_matches_config(doc, config)]
                    doc = latest_doc(docs)
                    if doc is None:
                        missing.append({
                            "condition": condition,
                            "trace": trace_label,
                            "trace_file_name": trace,
                            "rule_file_name": rule,
                            "index": str(index),
                            "capacity": str(capacity),
                            "reason": "not found",
                        })
                        continue
                    try:
                        old_row, updates = row_for_doc(doc, run_cacti, args)
                        cacti_results = updates.get("cacti_results") or doc.get("cacti_results")
                        metrics = cycle_aware_metrics(doc, cacti_results, args)
                    except Exception as exc:
                        missing.append({
                            "condition": condition,
                            "trace": trace_label,
                            "trace_file_name": trace,
                            "rule_file_name": rule,
                            "index": str(index),
                            "capacity": str(capacity),
                            "reason": str(exc).replace("\n", " ")[:1000],
                        })
                        continue
                    if args.write_back_cacti and updates:
                        collection.update_one({"_id": doc["_id"]}, {"$set": updates})
                    sim = doc["simulator_result"]
                    rows.append({
                        "condition_index": condition_index,
                        "condition": condition,
                        "condition_label": condition_label,
                        "trace_index": trace_index,
                        "trace": trace_label,
                        "trace_file_name": trace,
                        "rule_file_name": rule,
                        "index": index,
                        "index_label": INDEX_LABELS[index],
                        "capacity": capacity,
                        "capacity_k": capacity // 1024,
                        "processed": int(sim.get("processed", 0) or 0),
                        "hitrate_percent": float(sim.get("hitrate", 0) or 0) * 100,
                        "miss_rate_percent": (1 - float(sim.get("hitrate", 0) or 0)) * 100,
                        "old_1cycle_power_mw": float(old_row["power_mw"]),
                        "old_1cycle_throughput_gbps": float(old_row["throughput_gbps"]),
                        **metrics,
                        "source_id": str(doc["_id"]),
                    })
    return rows, missing


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot_condition(
    rows: list[dict[str, Any]],
    condition: str,
    metric: str,
    ylabel: str,
    title_suffix: str,
    path: Path,
) -> None:
    subset = [row for row in rows if row["condition"] == condition]
    condition_label = TRACES[condition][0]
    fig, axes = plt.subplots(1, 3, figsize=(19, 6.6), sharex=True)
    for trace_index, ax in enumerate(axes):
        trace_label = TRACES[condition][1][trace_index][0]
        for index in INDEXES:
            points = sorted(
                (row for row in subset if row["trace_index"] == trace_index and row["index"] == index),
                key=lambda row: row["capacity"],
            )
            ax.plot(
                [row["capacity_k"] for row in points],
                [row[metric] for row in points],
                marker="o",
                linewidth=2,
                color=COLORS[index],
                label=INDEX_LABELS[index],
            )
        ax.set_title(trace_label, fontsize=16)
        ax.set_xticks([1, 2, 4, 8, 16, 32], ["1K", "2K", "4K", "8K", "16K", "32K"])
        ax.set_xlabel("キャッシュ容量（entries）")
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel(ylabel)
    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, frameon=False)
    fig.suptitle(f"{condition_label}：{title_suffix}", fontsize=20, fontweight="bold")
    fig.tight_layout(rect=(0, 0.10, 1, 0.93))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_cycle_table(rows: list[dict[str, Any]], path: Path) -> None:
    unique: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        unique.setdefault((row["index"], row["capacity"]), row)
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.8))
    for index in INDEXES:
        points = [unique[(index, capacity)] for capacity in CAPACITIES if (index, capacity) in unique]
        axes[0].plot([p["capacity_k"] for p in points], [p["cacti_cycle_time_ns"] for p in points],
                     marker="o", linewidth=2, color=COLORS[index], label=INDEX_LABELS[index])
        axes[1].step([p["capacity_k"] for p in points], [p["cache_initiation_cycles"] for p in points],
                     where="mid", marker="o", linewidth=2, color=COLORS[index], label=INDEX_LABELS[index])
    axes[0].axhline(0.5, color="#333333", linestyle="--", label="2 GHzの1 cycle (0.5 ns)")
    axes[0].set_ylabel("CACTI cycle time (ns)")
    axes[1].set_ylabel("必要なcache initiation cycles")
    for ax in axes:
        ax.set_xticks([1, 2, 4, 8, 16, 32], ["1K", "2K", "4K", "8K", "16K", "32K"])
        ax.set_xlabel("キャッシュ容量（entries）")
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_title("CACTI cycle time")
    axes[1].set_title("2 GHz換算の必要cycle数")
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, frameon=False)
    fig.suptitle("容量増加によるPS cacheのcycle増加", fontsize=19, fontweight="bold")
    fig.tight_layout(rect=(0, 0.10, 1, 0.92))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_report(path: Path, rows: list[dict[str, Any]], missing: list[dict[str, str]], args: argparse.Namespace) -> None:
    lines = [
        "# Anonymous PS capacity sweep through 32K",
        "",
        "## Method",
        "",
        f"- CPU frequency: {args.cpu_frequency_ghz:g} GHz ({1 / args.cpu_frequency_ghz:.3f} ns/cycle)",
        "- Cache initiation cycles: `ceil(CACTI cycle_time / CPU cycle time)`",
        "- Effective cycles/packet: `max(cache initiation cycles, average DRAM stall cycles)`",
        "- Dynamic power uses the resulting packet rate; SRAM/DRAM energy per packet is unchanged.",
        "- Static power is CACTI SRAM leakage plus 320.1 mW DRAM background.",
        "- `access_time` is reported as latency cycles but is not used as the pipelined initiation interval.",
        "",
        f"Rows: {len(rows)}; missing: {len(missing)}.",
        "",
        "## 32K summary",
        "",
        "| condition | trace | best miss | index | lowest cycle-aware power | index | cache cycles |",
        "|---|---|---:|---|---:|---|---:|",
    ]
    for condition in TRACES:
        for trace_index, (trace_label, _, _) in enumerate(TRACES[condition][1]):
            values = [row for row in rows if row["condition"] == condition and row["trace_index"] == trace_index and row["capacity"] == 32768]
            if not values:
                continue
            best_miss = min(values, key=lambda row: row["miss_rate_percent"])
            best_power = min(values, key=lambda row: row["cycle_aware_power_mw"])
            lines.append(
                f"| {condition} | {trace_label} | {best_miss['miss_rate_percent']:.6f}% | {best_miss['index_label']} "
                f"| {best_power['cycle_aware_power_mw']:.3f} mW | {best_power['index_label']} | {best_power['cache_initiation_cycles']} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False})
    configure_cacti_env(args)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        rows, missing = collect(client[args.db][args.collection], args)
    finally:
        client.close()
    rows.sort(key=lambda row: (row["condition_index"], row["trace_index"], row["index"], row["capacity"]))
    write_csv(args.output_dir / "capacity_cycle_aware_results.csv", rows)
    write_csv(
        args.output_dir / "missing.csv", missing,
        ["condition", "trace", "trace_file_name", "rule_file_name", "index", "capacity", "reason"],
    )
    for condition in TRACES:
        plot_condition(rows, condition, "miss_rate_percent", "ミス率（%）", "PS cacheミス率",
                       args.output_dir / f"{condition}_miss_rate.png")
        plot_condition(rows, condition, "cycle_aware_power_mw", "推定消費電力（mW）", "cycle考慮後の消費電力",
                       args.output_dir / f"{condition}_power_cycle_aware.png")
    if rows:
        plot_cycle_table(rows, args.output_dir / "cacti_cycle_by_capacity.png")
    write_report(args.output_dir / "REPORT.md", rows, missing, args)
    print(f"rows={len(rows)} missing={len(missing)} output={args.output_dir}")
    return 2 if missing and args.fail_on_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
