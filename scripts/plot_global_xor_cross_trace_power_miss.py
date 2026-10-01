#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Create slide-18-style power and hit-rate graphs for global-XOR traces."""

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


ROOT = Path(__file__).resolve().parent / "reports" / "global-xor-cap8192-cross-trace"
TAG_LENGTH = tuple((9, 24) for _ in range(8))

TRACE_SETS = {
    "original": [
        ("JPIX-SINET 2018-05", "jpix2sinet90s_5tuple.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("SINET-JPIX 2018-05", "sinet2jpix90s_5tuple.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("WIDE 2025-09", "2025-09-27.pcap", "rib.20250927.0600.unique.rule"),
        ("WIDE 2025-12", "2025-12-27.pcap", "rib.20251227.0600.unique.rule"),
        ("WIDE 2026-03", "2026-03-27.pcap", "rib.20260327.0600.unique.rule"),
        ("San Jose 2014-03", "equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap", "route-views.isc.rib.20140320.1400.unique.rule"),
        ("Chicago 2014-03", "equinix-chicago.dirB.20140320-140100.UTC.anon.pcap", "route-views.chicago.rib.20160628.1400.unique.rule"),
        ("New York 2019-01", "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap", "rrc11.bview.20190117.1600.unique.rule"),
    ],
    "2025-09-27": [
        ("JPIX-SINET 2018-05", "jpix-sinet-2025-09-27.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("SINET-JPIX 2018-05", "sinet-jpix-2025-09-27.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("WIDE 2025-09", "wide-2025-09-to-2025-09-27.txt", "rib.20250927.0600.unique.rule"),
        ("WIDE 2025-12", "wide-2025-12-to-2025-09-27.txt", "rib.20251227.0600.unique.rule"),
        ("WIDE 2026-03", "wide-2026-03-to-2025-09-27.txt", "rib.20260327.0600.unique.rule"),
        ("San Jose 2014-03", "2025-09-27.txt", "route-views.isc.rib.20140320.1400.unique.rule"),
        ("Chicago 2014-03", "2025-09-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
        ("New York 2019-01", "2025-09-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
    ],
    "2025-12-27": [
        ("JPIX-SINET 2018-05", "jpix-sinet-2025-12-27.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("SINET-JPIX 2018-05", "sinet-jpix-2025-12-27.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("WIDE 2025-09", "wide-2025-09-to-2025-12-27.txt", "rib.20250927.0600.unique.rule"),
        ("WIDE 2025-12", "wide-2025-12-to-2025-12-27.txt", "rib.20251227.0600.unique.rule"),
        ("WIDE 2026-03", "wide-2026-03-to-2025-12-27.txt", "rib.20260327.0600.unique.rule"),
        ("San Jose 2014-03", "2025-12-27.txt", "route-views.isc.rib.20140320.1400.unique.rule"),
        ("Chicago 2014-03", "2025-12-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
        ("New York 2019-01", "2025-12-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
    ],
    "2026-03-27": [
        ("JPIX-SINET 2018-05", "jpix-sinet-2026-03-27.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("SINET-JPIX 2018-05", "sinet-jpix-2026-03-27.txt", "rrc06.bview.20180502.0000.unique.rule"),
        ("WIDE 2025-09", "wide-2025-09-to-2026-03-27.txt", "rib.20250927.0600.unique.rule"),
        ("WIDE 2025-12", "wide-2025-12-to-2026-03-27.txt", "rib.20251227.0600.unique.rule"),
        ("WIDE 2026-03", "wide-2026-03-to-2026-03-27.txt", "rib.20260327.0600.unique.rule"),
        ("San Jose 2014-03", "2026-03-27.txt", "route-views.isc.rib.20140320.1400.unique.rule"),
        ("Chicago 2014-03", "2026-03-27.txt", "route-views.chicago.rib.20160628.1400.unique.rule"),
        ("New York 2019-01", "2026-03-27.txt", "rrc11.bview.20190117.1600.unique.rule"),
    ],
}


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

COLORS = [
    "#9ecae1", "#6baed6", "#4292c6", "#3182bd", "#2171b5", "#08519c",
    "#c7e9c0", "#a1d99b", "#74c476", "#31a354", "#006d2c", "#d7191c",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017"))
    p.add_argument("--db", default="db")
    p.add_argument("--collection", default="simulator_results")
    p.add_argument("--cacti-collection", default="cacti_results")
    p.add_argument("--processed", type=int, default=10_000_000)
    p.add_argument("--dram-pj-per-burst", type=float, default=4000)
    p.add_argument("--output-dir", type=Path, default=ROOT)
    p.add_argument("--write-back", action="store_true")
    p.add_argument("--fail-on-missing", action="store_true")
    p.add_argument("--condition", choices=tuple(TRACE_SETS), default="original")
    return p.parse_args()


def collect(collection: Any, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    traces = TRACE_SETS[args.condition]
    for trace_index, (trace_label, trace, rule) in enumerate(traces):
        for config_index, config in enumerate(CONFIGS):
            query = base_query(config, trace, rule, args.processed)
            query.pop("simulator_result.processed", None)
            docs = [
                doc for doc in collection.find(query)
                if doc_matches_config(doc, config)
            ]
            doc = latest_doc(docs)
            if doc is None:
                missing.append({"trace_label": trace_label, "trace_file_name": trace, "rule_file_name": rule, "series": config.series, "reason": "not found"})
                continue
            try:
                row, updates = row_for_doc(doc, run_cacti, args)
            except Exception as exc:
                missing.append({"trace_label": trace_label, "trace_file_name": trace, "rule_file_name": rule, "series": config.series, "reason": str(exc).replace("\n", " ")[:1000]})
                continue
            if args.write_back:
                collection.update_one({"_id": doc["_id"]}, {"$set": updates})
            rows.append({
                "condition": args.condition,
                "trace_index": trace_index,
                "trace_label": trace_label,
                "trace_file_name": trace,
                "rule_file_name": rule,
                "config_index": config_index,
                "series": config.series,
                "hitrate_percent": float(row["hitrate"]) * 100.0,
                "miss_rate_percent": (1.0 - float(row["hitrate"])) * 100.0,
                "power_mw": float(row["power_mw"]),
                "throughput_gbps": float(row["throughput_gbps"]),
                "source_id": row["id"],
            })
            print(f"matched {trace_label.replace(chr(10), ' ')} | {config.series}")
    return rows, missing


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def plot(rows: list[dict[str, Any]], traces: list[tuple[str, str, str]], metric: str, ylabel: str, title: str, path: Path) -> None:
    by_key = {(int(r["trace_index"]), int(r["config_index"])): r for r in rows}
    n_traces = len(traces)
    n_configs = len(CONFIGS)
    group_width = 0.86
    bar_width = group_width / n_configs
    x = list(range(n_traces))

    fig, ax = plt.subplots(figsize=(20, 9), facecolor="white")
    for ci, config in enumerate(CONFIGS):
        offset = -group_width / 2 + (ci + 0.5) * bar_width
        values = [
            float(by_key[(ti, ci)][metric]) if (ti, ci) in by_key else math.nan
            for ti in range(n_traces)
        ]
        ax.bar([v + offset for v in x], values, width=bar_width * 0.94,
               color=COLORS[ci], edgecolor="#263238", linewidth=0.35, label=config.series)

    ax.axvspan(-0.5, 4.5, color="#4C78A8", alpha=0.08, zorder=0)
    ax.axvspan(4.5, 7.5, color="#F58518", alpha=0.08, zorder=0)
    ax.axvline(4.5, color="#9ca3af", linewidth=1.2)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_title(title, fontsize=17, pad=14)
    ax.set_xticks(x, [label for label, _, _ in traces], fontsize=11, rotation=28, ha="right")
    ax.grid(axis="y", alpha=0.28)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.105), ncol=4,
              frameon=False, fontsize=10)
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    fig.savefig(path, dpi=220, facecolor="white")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_cacti_env(args)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        rows, missing = collect(client[args.db][args.collection], args)
    finally:
        client.close()

    rows.sort(key=lambda r: (int(r["trace_index"]), int(r["config_index"])))
    slug = args.condition
    write_csv(args.output_dir / f"{slug}_capacity8192_power_miss.csv", rows,
              ["condition", "trace_index", "trace_label", "trace_file_name", "rule_file_name", "config_index", "series", "hitrate_percent", "miss_rate_percent", "power_mw", "throughput_gbps", "source_id"])
    write_csv(args.output_dir / f"{slug}_missing.csv", missing,
              ["trace_label", "trace_file_name", "rule_file_name", "series", "reason"])
    if rows:
        condition_title = "Original traces" if args.condition == "original" else f"24-bit XOR target: {args.condition}"
        traces = TRACE_SETS[args.condition]
        plot(rows, traces, "power_mw", "Power (mW)",
             f"{condition_title}: power (capacity 8192)",
             args.output_dir / f"{slug}_power_capacity8192.png")
        plot(rows, traces, "miss_rate_percent", "Miss rate (%)",
             f"{condition_title}: miss rate (capacity 8192)",
             args.output_dir / f"{slug}_miss_rate_capacity8192.png")

    print(f"condition={args.condition} rows={len(rows)} missing={len(missing)}")
    print(f"output_dir={args.output_dir}")
    return 2 if missing and args.fail_on_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
