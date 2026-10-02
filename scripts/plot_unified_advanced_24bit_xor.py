#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Compare advanced UnifiedCache policies on 24-bit XOR transformed traces."""

from __future__ import annotations

import argparse
import csv
import math
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
from scripts.compare_multilayer_unified import configure_cacti_env, row_for_doc  # type: ignore  # noqa: E402


OUTPUT = Path(__file__).resolve().parent / "reports" / "unified-advanced-24bit-xor"
TAG_LENGTH = [[9, 24] for _ in range(8)]
TRACES = [
    ("Chicago -> 2025-09", "2025-09-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
    ("Chicago -> 2025-12", "2025-12-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
    ("Chicago -> 2026-03", "2026-03-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
    ("NYC -> 2025-09", "2025-09-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
    ("NYC -> 2025-12", "2025-12-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
    ("NYC -> 2026-03", "2026-03-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
    ("anon-WIDE -> 2025-09", "2025-09-27.txt", "rib.20250927.0600.unique.rule"),
    ("anon-WIDE -> 2025-12", "2025-12-27.txt", "rib.20251227.0600.unique.rule"),
    ("anon-WIDE -> 2026-03", "2026-03-27.txt", "rib.20260327.0600.unique.rule"),
]
CONFIGS = [
    ("baseline /24", False, 0, False),
    ("length-aware MP", True, 0, False),
    ("way quota 2+6", False, 2, False),
    ("skewed 2-hash", False, 0, True),
    ("combined", True, 2, True),
]
COLORS = ["#64748b", "#2563eb", "#f59e0b", "#16a34a", "#dc2626"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--cacti-collection", default="cacti_results")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--dram-pj-per-burst", type=float, default=4000)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--write-back", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    return parser.parse_args()


def query_for(trace: str, rule: str, processed: int, multi_probe: bool, wide_ways: int, skewed: bool) -> dict[str, Any]:
    return {
        "trace_file_name": trace,
        "rule_file_name": rule,
        "simulator_result.type": "UnifiedCache",
        "simulator_result.processed": {"$lte": processed},
        "simulator_result.parameter.size": 8192,
        "simulator_result.parameter.way": 8,
        "simulator_result.parameter.cacheindextype": 24,
        "simulator_result.parameter.cachetaglength": TAG_LENGTH,
        "simulator_result.parameter.insertionpolicy": "exclusive",
        "simulator_result.parameter.lengthawaremultiprobe": multi_probe,
        "simulator_result.parameter.multiprobelengths": [18, 20, 22, 24],
        "simulator_result.parameter.wayquotawidemax": 18,
        "simulator_result.parameter.wayquotawideways": wide_ways,
        "simulator_result.parameter.skewedassociative": skewed,
    }


def probe_adjusted_row(doc: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    base, updates = row_for_doc(doc, run_cacti, args)
    sim = doc["simulator_result"]
    processed = int(sim.get("processed", 0) or 0)
    stat = sim.get("statdetail", {})
    probe_count = int(stat.get("setprobecount", 0) or 0)
    average_probes = probe_count / processed if processed > 0 and probe_count > 0 else 1.0

    cacti_results = updates.get("cacti_results", doc.get("cacti_results"))
    if not cacti_results:
        raise ValueError("missing cacti_results after power estimation")
    cacti = cacti_results[0]
    tag_energy_raw = cacti.get("tag_array_dynamic_read_energy")
    if tag_energy_raw in (None, "null"):
        tag_energy_raw = cacti.get("total_dynamic_associative_search_energy")
    if tag_energy_raw in (None, "null"):
        raise ValueError("missing CACTI tag-read energy")
    tag_energy_nj = float(tag_energy_raw)

    extra_tag_energy = max(0.0, average_probes - 1.0) * tag_energy_nj
    packet_rate = float(base["throughput_gbps"]) / 512.0
    extra_dynamic_power = extra_tag_energy * packet_rate * 1000.0
    adjusted_power = float(base["power_mw"]) + extra_dynamic_power
    adjusted_dynamic = float(base["dynamic_power_mw"]) + extra_dynamic_power
    adjusted_sram_energy = float(base["sram_dynamic_energy_nj_per_packet"]) + extra_tag_energy

    row = dict(base)
    row.update(
        average_set_probes=average_probes,
        tag_read_energy_nj=tag_energy_nj,
        extra_tag_energy_nj_per_packet=extra_tag_energy,
        base_power_mw=float(base["power_mw"]),
        power_mw=adjusted_power,
        dynamic_power_mw=adjusted_dynamic,
        sram_dynamic_energy_nj_per_packet=adjusted_sram_energy,
    )
    power_model = {
        "total_power": adjusted_power,
        "dynamic_power": adjusted_dynamic,
        "static_energy": float(base["static_power_mw"]),
        "sram_dynamic_energy": adjusted_sram_energy,
        "dram_dynamic_energy": float(base["dram_dynamic_energy_nj_per_packet"]),
        "average_set_probes": average_probes,
        "tag_read_energy_nj": tag_energy_nj,
        "parallel_probe_latency_multiplier": 1.0,
    }
    return row, power_model


def collect(collection: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for trace_index, (trace_label, trace, rule) in enumerate(TRACES):
        for config_index, (config_label, multi, wide_ways, skewed) in enumerate(CONFIGS):
            query = query_for(trace, rule, args.processed, multi, wide_ways, skewed)
            doc = collection.find_one(
                query,
                sort=[("simulator_result.processed", -1), ("timestamp", -1)],
            )
            if doc is None:
                missing.append({"trace": trace_label, "config": config_label, "reason": "not found"})
                continue
            try:
                row, power_model = probe_adjusted_row(doc, args)
            except Exception as exc:
                missing.append({"trace": trace_label, "config": config_label, "reason": str(exc)[:1000]})
                continue
            if args.write_back:
                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {f"advanced_policy_power_series.{int(args.dram_pj_per_burst)}": power_model}},
                )
            rows.append(
                {
                    "trace_index": trace_index,
                    "trace": trace_label,
                    "config_index": config_index,
                    "config": config_label,
                    "processed": int(doc["simulator_result"].get("processed", 0) or 0),
                    "hitrate_percent": float(row["hitrate"]) * 100.0,
                    "power_mw": float(row["power_mw"]),
                    "base_power_mw": float(row["base_power_mw"]),
                    "throughput_gbps": float(row["throughput_gbps"]),
                    "average_set_probes": float(row["average_set_probes"]),
                    "extra_tag_energy_nj_per_packet": float(row["extra_tag_energy_nj_per_packet"]),
                    "source_id": row["id"],
                }
            )
    return rows, missing


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def plot_metric(rows: list[dict[str, Any]], metric: str, ylabel: str, path: Path) -> None:
    lookup = {(int(row["trace_index"]), int(row["config_index"])): row for row in rows}
    x = list(range(len(TRACES)))
    group_width = 0.84
    width = group_width / len(CONFIGS)
    fig, ax = plt.subplots(figsize=(22, 8), facecolor="white")
    for ci, (label, *_rest) in enumerate(CONFIGS):
        offset = -group_width / 2 + (ci + 0.5) * width
        values = [float(lookup[(ti, ci)][metric]) if (ti, ci) in lookup else math.nan for ti in x]
        ax.bar([xi + offset for xi in x], values, width=width * 0.94, label=label, color=COLORS[ci])
    ax.set_xticks(x, [label.replace(" -> ", "\n") for label, _, _ in TRACES])
    ax.set_ylabel(ylabel)
    ax.set_title("UnifiedCache advanced policies on 24-bit XOR transformed traces")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    by_config = {label: [row for row in rows if row["config"] == label] for label, *_ in CONFIGS}
    baseline = by_config["baseline /24"]
    baseline_hit = statistics.mean(float(row["hitrate_percent"]) for row in baseline) if baseline else math.nan
    baseline_power = statistics.mean(float(row["power_mw"]) for row in baseline) if baseline else math.nan
    lines = [
        "# UnifiedCache advanced policy summary",
        "",
        "Power model: CACTI SRAM + DRAM model; parallel set probes keep one-access latency,",
        "while tag-read energy is multiplied by the measured average unique set probes.",
        "",
        "| Configuration | Mean hit rate | Δ hit rate | Mean power | Δ power | Mean probes |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, *_ in CONFIGS:
        values = by_config[label]
        if not values:
            continue
        hit = statistics.mean(float(row["hitrate_percent"]) for row in values)
        power = statistics.mean(float(row["power_mw"]) for row in values)
        probes = statistics.mean(float(row["average_set_probes"]) for row in values)
        lines.append(f"| {label} | {hit:.6f}% | {hit-baseline_hit:+.6f} pp | {power:.3f} mW | {power-baseline_power:+.3f} mW | {probes:.3f} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_cacti_env(args)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        rows, missing = collect(client[args.db][args.collection], args)
    finally:
        client.close()
    rows.sort(key=lambda row: (int(row["trace_index"]), int(row["config_index"])))
    write_csv(args.output_dir / "results.csv", rows)
    write_csv(args.output_dir / "missing.csv", missing)
    if rows:
        plot_metric(rows, "hitrate_percent", "Hit rate (%)", args.output_dir / "hitrate.png")
        plot_metric(rows, "power_mw", "Power (mW)", args.output_dir / "power.png")
        write_summary(args.output_dir / "SUMMARY.md", rows)
    print(f"rows={len(rows)} missing={len(missing)} output_dir={args.output_dir}")
    return 2 if missing and args.fail_on_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
