#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Create grouped-bar miss-rate and power plots for anonymous VIL and MP caches."""

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
from matplotlib.patches import Patch
from pymongo import MongoClient


VIEWER = Path("/home/yuzugon/ppc-result-viewer")
if str(VIEWER) not in sys.path:
    sys.path.insert(0, str(VIEWER))

from models.unifiedcache import UnifiedCacheResult  # type: ignore  # noqa: E402
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


OUTPUT = Path(__file__).resolve().parent / "reports/global-xor-anon-vil-mp-capacity32k"
VIL_CAPACITIES = (1024, 2048, 4096, 8192, 16384, 32768)
MP2_BANK_CAPACITIES = (512, 1024, 2048, 4096, 8192, 16384)
MP3_BANK_CAPACITIES = (512, 1024, 2048, 4096, 8192)
VIL_INDEXES = (16, 18, 20, 22, 24, 2)
VIL_LABELS = {
    16: "VIL /16", 18: "VIL /18", 20: "VIL /20",
    22: "VIL /22", 24: "VIL /24", 2: "VIL ideal",
}
VIL_COLORS = {
    16: "#c6dbef", 18: "#9ecae1", 20: "#6baed6",
    22: "#3182bd", 24: "#08519c", 2: "#d7191c",
}
MP_COLORS = {"MP 2-cache（/24, /18）": "#f28e2b", "MP 3-cache（/24, /21, /18）": "#59a14f"}
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


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--cacti-collection", default="cacti_results")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--dram-pj-per-burst", type=float, default=4000)
    parser.add_argument("--cpu-frequency-ghz", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--write-back-cacti", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    return parser.parse_args()


def vil_config(index: int, capacity: int) -> FixedConfig:
    return FixedConfig(
        VIL_LABELS[index], "UnifiedCache", 1, (capacity,), (), 8, index,
        TAG_LENGTH, "exclusive", "", "",
    )


def mp_config(layers: int, bank_capacity: int) -> FixedConfig:
    refs = (24, 18) if layers == 2 else (24, 21, 18)
    capacities = tuple(bank_capacity for _ in refs)
    return FixedConfig(
        f"MP {layers}-cache", "MultiLayerCacheExclusive", layers,
        capacities, refs, 8, None, (), "", "", "",
    )


def timing_adjusted_metrics(
    doc: dict[str, Any], old_row: dict[str, Any], cacti_results: list[dict[str, Any]], args: argparse.Namespace,
) -> dict[str, float | int]:
    sim = doc["simulator_result"]
    processed = int(sim.get("processed", 0) or 0)
    if processed <= 0 or not cacti_results:
        raise ValueError("processed and CACTI results are required")

    if sim.get("type") == "UnifiedCache":
        result = UnifiedCacheResult(sim)
        miss = result.miss_count()
        depth_average = result.depth_average()
    else:
        stat = sim.get("statdetail", {})
        hit = sum(int(value) for value in stat.get("hit", []))
        miss = max(0, processed - hit)
        depthsum = float(stat.get("depthsum", 0) or 0)
        depth_average = depthsum / miss if miss else 0.0

    cpu_cycle_ns = 1.0 / args.cpu_frequency_ghz
    cacti_cycle_ns = max(float(item["cycle_time"]) for item in cacti_results)
    cache_cycles = max(1, math.ceil(cacti_cycle_ns / cpu_cycle_ns - 1e-12))
    dram_cycles = (miss / processed) * depth_average * 8
    effective_cycles = max(float(cache_cycles), dram_cycles)
    throughput = args.cpu_frequency_ghz * 512 / effective_cycles

    old_throughput = float(old_row["throughput_gbps"])
    old_dynamic = float(old_row["dynamic_power_mw"])
    static_power = float(old_row["static_power_mw"])
    dynamic_power = old_dynamic * throughput / old_throughput
    return {
        "throughput_gbps": throughput,
        "power_mw": dynamic_power + static_power,
        "dynamic_power_mw": dynamic_power,
        "static_power_mw": static_power,
        "cacti_cycle_time_ns": cacti_cycle_ns,
        "cache_cycles": cache_cycles,
        "dram_cycles": dram_cycles,
    }


def config_specs() -> list[tuple[str, str, int | None, int, int, FixedConfig]]:
    specs: list[tuple[str, str, int | None, int, int, FixedConfig]] = []
    for index in VIL_INDEXES:
        for capacity in VIL_CAPACITIES:
            specs.append(("VIL", VIL_LABELS[index], index, capacity, capacity, vil_config(index, capacity)))
    for bank in MP2_BANK_CAPACITIES:
        specs.append(("MP2", "MP 2-cache（/24, /18）", None, bank, bank * 2, mp_config(2, bank)))
    for bank in MP3_BANK_CAPACITIES:
        specs.append(("MP3", "MP 3-cache（/24, /21, /18）", None, bank, bank * 3, mp_config(3, bank)))
    return specs


def collect(collection: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for condition_index, (condition, (condition_label, traces)) in enumerate(TRACES.items()):
        for trace_index, (trace_label, trace, rule) in enumerate(traces):
            expected_processed = 6_338_755 if trace_label == "Chicago" else args.processed
            for architecture, series, index, bank_capacity, total_capacity, config in config_specs():
                query = base_query(config, trace, rule, expected_processed)
                docs = [doc for doc in collection.find(query) if doc_matches_config(doc, config)]
                doc = latest_doc(docs)
                if doc is None:
                    missing.append({
                        "condition": condition, "trace": trace_label, "architecture": architecture,
                        "series": series, "bank_capacity": str(bank_capacity),
                        "total_capacity": str(total_capacity), "reason": "not found",
                    })
                    continue
                try:
                    old_row, updates = row_for_doc(doc, run_cacti, args)
                    cacti_results = updates.get("cacti_results") or doc.get("cacti_results")
                    metrics = timing_adjusted_metrics(doc, old_row, cacti_results, args)
                except Exception as exc:
                    missing.append({
                        "condition": condition, "trace": trace_label, "architecture": architecture,
                        "series": series, "bank_capacity": str(bank_capacity),
                        "total_capacity": str(total_capacity), "reason": str(exc).replace("\n", " ")[:1000],
                    })
                    continue
                if args.write_back_cacti and updates:
                    collection.update_one({"_id": doc["_id"]}, {"$set": updates})
                sim = doc["simulator_result"]
                hitrate = float(sim.get("hitrate", 0) or 0) * 100
                rows.append({
                    "condition_index": condition_index, "condition": condition,
                    "condition_label": condition_label, "trace_index": trace_index,
                    "trace": trace_label, "trace_file_name": trace,
                    "rule_file_name": rule, "architecture": architecture,
                    "series": series, "index": "" if index is None else index,
                    "bank_capacity": bank_capacity, "total_capacity": total_capacity,
                    "processed": int(sim.get("processed", 0) or 0),
                    "hitrate_percent": hitrate, "miss_rate_percent": 100 - hitrate,
                    **metrics, "source_id": str(doc["_id"]),
                })
    return rows, missing


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def values_for(
    rows: list[dict[str, Any]], condition: str, trace_index: int,
    architecture: str, series: str, capacities: tuple[int, ...], metric: str,
) -> list[float]:
    lookup = {
        int(row["bank_capacity"]): float(row[metric])
        for row in rows
        if row["condition"] == condition and row["trace_index"] == trace_index
        and row["architecture"] == architecture and row["series"] == series
    }
    return [lookup.get(capacity, math.nan) for capacity in capacities]


def draw_vil(ax: Any, rows: list[dict[str, Any]], condition: str, trace_index: int, metric: str) -> None:
    x = list(range(len(VIL_CAPACITIES)))
    width = 0.13
    for order, index in enumerate(VIL_INDEXES):
        offset = (order - (len(VIL_INDEXES) - 1) / 2) * width
        ax.bar(
            [value + offset for value in x],
            values_for(rows, condition, trace_index, "VIL", VIL_LABELS[index], VIL_CAPACITIES, metric),
            width=width, color=VIL_COLORS[index], edgecolor="white", linewidth=0.25,
        )
    ax.set_xticks(x, ("1K", "2K", "4K", "8K", "16K", "32K"))
    ax.set_xlabel("VIL cache容量（entries）")


def draw_mp(ax: Any, rows: list[dict[str, Any]], condition: str, trace_index: int, metric: str) -> None:
    bank_capacities = MP2_BANK_CAPACITIES
    x = list(range(len(bank_capacities)))
    width = 0.36
    ax.bar(
        [value - width / 2 for value in x],
        values_for(rows, condition, trace_index, "MP2", "MP 2-cache（/24, /18）", bank_capacities, metric),
        width=width, color=MP_COLORS["MP 2-cache（/24, /18）"], edgecolor="white", linewidth=0.3,
    )
    ax.bar(
        [value + width / 2 for value in x],
        values_for(rows, condition, trace_index, "MP3", "MP 3-cache（/24, /21, /18）", bank_capacities, metric),
        width=width, color=MP_COLORS["MP 3-cache（/24, /21, /18）"], edgecolor="white", linewidth=0.3,
    )
    ax.set_xticks(x, ("0.5K", "1K", "2K", "4K", "8K", "16K"))
    ax.set_xlabel("1 bankあたり容量（MP2合計=2倍、MP3合計=3倍）")


def plot_condition(
    rows: list[dict[str, Any]], condition: str, metric: str, ylabel: str, title: str, path: Path,
) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(20, 11.6), sharey="row")
    for trace_index in range(3):
        trace_label = TRACES[condition][1][trace_index][0]
        draw_vil(axes[0][trace_index], rows, condition, trace_index, metric)
        draw_mp(axes[1][trace_index], rows, condition, trace_index, metric)
        axes[0][trace_index].set_title(f"{trace_label} — VIL cache", fontsize=15, fontweight="bold")
        axes[1][trace_index].set_title(f"{trace_label} — MP cache", fontsize=15, fontweight="bold")
        for row in range(2):
            ax = axes[row][trace_index]
            ax.grid(axis="y", alpha=0.22)
            ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].set_ylabel(ylabel)
    axes[1][0].set_ylabel(ylabel)
    legend = [Patch(facecolor=VIL_COLORS[index], label=VIL_LABELS[index]) for index in VIL_INDEXES]
    legend += [Patch(facecolor=MP_COLORS[label], label=label) for label in ("MP 2-cache（/24, /18）", "MP 3-cache（/24, /21, /18）")]
    fig.legend(handles=legend, loc="lower center", ncol=8, frameon=False, fontsize=11)
    fig.suptitle(f"{TRACES[condition][0]}：{title}", fontsize=20, fontweight="bold")
    fig.tight_layout(rect=(0, 0.07, 1, 0.95), h_pad=2.7)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def write_report(path: Path, rows: list[dict[str, Any]], missing: list[dict[str, str]]) -> None:
    lines = [
        "# Anonymous VIL / MP capacity sweep",
        "",
        "- VIL cache: 8-way, /16,/18,/20,/22,/24 and ideal, 1K..32K entries.",
        "- MP 2-cache: 8-way, /24,/18, equal banks, total capacity 1K..32K entries.",
        "- MP 3-cache: 8-way, /24,/21,/18, equal banks, total capacity 1.5K..24K entries.",
        "- Power: current CACTI data-array/tag model and 2 GHz timing are applied internally.",
        "",
        f"Rows: {len(rows)}; missing: {len(missing)}.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = arguments()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False})
    configure_cacti_env(args)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        rows, missing = collect(client[args.db][args.collection], args)
    finally:
        client.close()
    rows.sort(key=lambda row: (
        row["condition_index"], row["trace_index"], row["architecture"],
        str(row["series"]), row["bank_capacity"],
    ))
    write_csv(args.output_dir / "capacity_results.csv", rows)
    write_csv(
        args.output_dir / "missing.csv", missing,
        ["condition", "trace", "architecture", "series", "bank_capacity", "total_capacity", "reason"],
    )
    for condition in TRACES:
        plot_condition(rows, condition, "miss_rate_percent", "ミス率（%）", "ミス率",
                       args.output_dir / f"{condition}_miss_rate.png")
        plot_condition(rows, condition, "power_mw", "推定消費電力（mW）", "推定消費電力",
                       args.output_dir / f"{condition}_power.png")
    write_report(args.output_dir / "REPORT.md", rows, missing)
    print(f"rows={len(rows)} missing={len(missing)} output={args.output_dir}")
    return 2 if missing and args.fail_on_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
