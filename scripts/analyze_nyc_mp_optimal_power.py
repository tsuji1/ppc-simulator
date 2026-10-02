#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Calculate cycle-aware power for NYC MP2/MP3 miss-rate-optimal points."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


SCRIPT_DIR = Path(__file__).resolve().parent
VIEWER = Path("/home/yuzugon/ppc-result-viewer")
if str(VIEWER) not in sys.path:
    sys.path.insert(0, str(VIEWER))

from scripts.cacti_exec import run_cacti  # type: ignore  # noqa: E402
from scripts.compare_multilayer_unified import (  # type: ignore  # noqa: E402
    configure_cacti_env,
    row_for_doc,
)
from plot_global_xor_anon_vil_mp_bars import timing_adjusted_metrics  # noqa: E402


TRACE = "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap"
RULE = "rrc11.bview.20190117.1600.unique.rule"
OUTPUT = SCRIPT_DIR / "reports/nyc-mp-optimal-power"
POWER_OF_TWO_CAPACITIES = {512, 1024, 2048, 4096, 8192, 16384, 32768}
MP3_SWEEP_CAPACITIES = {1024, 2048, 4096, 8192}
EXTRA_MP2_EQUAL_CAPACITIES = {20000, 49152, 65536}
EXTRA_MP3_EQUAL_CAPACITIES = {
    512, 10000, 10920, 11000, 12000, 13000, 21840, 32768, 43688,
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017/"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--cacti-collection", default="cacti_results")
    parser.add_argument("--trace", default=TRACE)
    parser.add_argument("--rule", default=RULE)
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--max-total-capacity", type=int, default=131072)
    parser.add_argument("--dram-pj-per-burst", type=float, default=4000)
    parser.add_argument("--cpu-frequency-ghz", type=float, default=2.0)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--write-back-cacti", action="store_true")
    return parser.parse_args()


def layer_signature(doc: dict[str, Any]) -> tuple[tuple[int, int, int], ...]:
    layers = doc.get("simulator_result", {}).get("parameter", {}).get("cachelayers", [])
    return tuple(
        (int(layer.get("size", 0)), int(layer.get("way", 0)), int(layer.get("refbits", 0)))
        for layer in layers
    )


def accepted(signature: tuple[tuple[int, int, int], ...]) -> bool:
    if len(signature) not in (2, 3):
        return False
    capacities = tuple(item[0] for item in signature)
    ways = tuple(item[1] for item in signature)
    refbits = tuple(item[2] for item in signature)
    if any(way != 8 for way in ways) or refbits[0] != 24:
        return False
    if len(signature) == 2:
        normal_sweep = all(capacity in POWER_OF_TWO_CAPACITIES for capacity in capacities)
        extra_equal_point = (
            capacities[0] == capacities[1]
            and capacities[0] in EXTRA_MP2_EQUAL_CAPACITIES
        )
        return (
            refbits[0] > refbits[1]
            and 16 <= refbits[1] <= 23
            and (normal_sweep or extra_equal_point)
        )
    normal_sweep = all(capacity in MP3_SWEEP_CAPACITIES for capacity in capacities)
    extra_equal_point = (
        capacities[0] == capacities[1] == capacities[2]
        and capacities[0] in EXTRA_MP3_EQUAL_CAPACITIES
    )
    return (
        refbits[0] > refbits[1] > refbits[2] >= 10
        and (normal_sweep or extra_equal_point)
    )


def latest_documents(collection: Any, args: argparse.Namespace) -> list[dict[str, Any]]:
    query = {
        "trace_file_name": args.trace,
        "rule_file_name": args.rule,
        "simulator_result.type": "MultiLayerCacheExclusive",
        "simulator_result.processed": args.processed,
    }
    latest: dict[str, dict[str, Any]] = {}
    for doc in sorted(collection.find(query), key=lambda item: item.get("timestamp"), reverse=True):
        signature = layer_signature(doc)
        if not accepted(signature):
            continue
        key = json.dumps(signature)
        latest.setdefault(key, doc)
    return list(latest.values())


def miss_rate(doc: dict[str, Any]) -> float:
    return (1.0 - float(doc["simulator_result"].get("hitrate", 0) or 0)) * 100.0


def select_optimal(docs: list[dict[str, Any]], max_total_capacity: int) -> list[dict[str, Any]]:
    best: dict[tuple[str, int], dict[str, Any]] = {}
    for doc in docs:
        signature = layer_signature(doc)
        architecture = f"MP{len(signature)}"
        total_capacity = sum(item[0] for item in signature)
        if total_capacity > max_total_capacity:
            continue
        key = (architecture, total_capacity)
        if key not in best or miss_rate(doc) < miss_rate(best[key]):
            best[key] = doc
    return [best[key] for key in sorted(best, key=lambda item: (item[1], item[0]))]


def calculate_rows(
    collection: Any,
    docs: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for doc in docs:
        signature = layer_signature(doc)
        architecture = f"MP{len(signature)}"
        try:
            old_row, updates = row_for_doc(doc, run_cacti, args)
            cacti_results = updates.get("cacti_results") or doc.get("cacti_results")
            metrics = timing_adjusted_metrics(doc, old_row, cacti_results, args)
            if args.write_back_cacti and updates:
                collection.update_one({"_id": doc["_id"]}, {"$set": updates})
            sim = doc["simulator_result"]
            capacities = tuple(item[0] for item in signature)
            refbits = tuple(item[2] for item in signature)
            rows.append(
                {
                    "architecture": architecture,
                    "total_capacity": sum(capacities),
                    "capacities": "-".join(map(str, capacities)),
                    "refbits": "-".join(map(str, refbits)),
                    "processed": int(sim.get("processed", 0) or 0),
                    "hitrate_percent": float(sim.get("hitrate", 0) or 0) * 100.0,
                    "miss_rate_percent": miss_rate(doc),
                    **metrics,
                    "source_id": str(doc["_id"]),
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "architecture": architecture,
                    "signature": str(signature),
                    "source_id": str(doc.get("_id", "")),
                    "error": str(exc).replace("\n", " ")[:1000],
                }
            )
    rows.sort(key=lambda row: (int(row["total_capacity"]), str(row["architecture"])))
    return rows, errors


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def configure_axes(ax: Any, ylabel: str) -> None:
    ax.set_xscale("log", base=2)
    ax.set_xlim(900, 145000)
    ticks = (1024, 2048, 4096, 8192, 16384, 32768, 65536, 98304, 131072)
    labels = ("1K", "2K", "4K", "8K", "16K", "32K", "64K", "96K", "128K")
    ax.set_xticks(ticks, labels)
    ax.set_xlabel("合計キャッシュ容量（entries、log2）", fontsize=13)
    ax.set_ylabel(ylabel, fontsize=13)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.9)
    ax.grid(axis="x", which="major", color="#eeeeee", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=10, labelrotation=30)
    ax.tick_params(axis="y", labelsize=11)


def scatter(ax: Any, rows: list[dict[str, Any]], metric: str) -> None:
    styles = {
        "MP2": ("#3182bd", "D", "MP2 optimal"),
        "MP3": ("#08519c", "P", "MP3 optimal"),
    }
    for architecture, (color, marker, label) in styles.items():
        selected = [row for row in rows if row["architecture"] == architecture]
        ax.scatter(
            [int(row["total_capacity"]) for row in selected],
            [float(row[metric]) for row in selected],
            s=90,
            color=color,
            marker=marker,
            edgecolor="#222222",
            linewidth=0.45,
            label=label,
            zorder=4,
        )


def plot(rows: list[dict[str, Any]], output_dir: Path) -> None:
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.2))
    scatter(axes[0], rows, "miss_rate_percent")
    scatter(axes[1], rows, "power_mw")
    configure_axes(axes[0], "ミス率（%）")
    configure_axes(axes[1], "推定消費電力（mW）")
    axes[0].legend(frameon=False, fontsize=11)
    axes[1].legend(frameon=False, fontsize=11)
    fig.suptitle("NYC元匿名：MP2/MP3 optimalのミス率と推定消費電力", fontsize=18, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(output_dir / "nyc_mp_optimal_miss_power.png", dpi=220, facecolor="white")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    scatter(ax, rows, "power_mw")
    configure_axes(ax, "推定消費電力（mW）")
    ax.legend(frameon=False, fontsize=12)
    ax.set_title("NYC元匿名：MP2/MP3 optimalの推定消費電力", fontsize=17, weight="bold")
    fig.tight_layout()
    fig.savefig(output_dir / "nyc_mp_optimal_power.png", dpi=220, facecolor="white")
    plt.close(fig)


def write_report(path: Path, rows: list[dict[str, Any]], source_count: int, errors: list[dict[str, str]]) -> None:
    def find(architecture: str, capacity: int) -> dict[str, Any] | None:
        return next(
            (
                row
                for row in rows
                if row["architecture"] == architecture
                and int(row["total_capacity"]) == capacity
            ),
            None,
        )

    lines = [
        "# NYC MP optimal power",
        "",
        "MP2/MP3ごとに、同じ合計容量でミス率が最小の構成をoptimalとして選択した。",
        "その構成に既存のCACTI SRAM + DRAMモデルとcache cycle判定を適用した。",
        "",
        f"- 入力した重複除去済みMP構成: {source_count}",
        f"- 電力計算済みoptimal点: {len(rows)}",
        f"- 計算失敗: {len(errors)}",
        "",
        "| 構成 | 合計容量 | ミス率 | 推定電力 | bank容量 | refbits | cache cycles |",
        "|---|---:|---:|---:|---|---|---:|",
    ]
    for architecture, capacity in (
        ("MP2", 32768),
        ("MP3", 30000),
        ("MP3", 32760),
        ("MP3", 33000),
        ("MP3", 36000),
        ("MP3", 39000),
        ("MP2", 40000),
        ("MP2", 40960),
        ("MP2", 65536),
        ("MP3", 65520),
        ("MP2", 98304),
        ("MP3", 98304),
        ("MP2", 131072),
        ("MP3", 131064),
    ):
        row = find(architecture, capacity)
        if row:
            lines.append(
                f"| {architecture} optimal | {capacity} | "
                f"{float(row['miss_rate_percent']):.4f}% | {float(row['power_mw']):.3f} mW | "
                f"{row['capacities']} | {row['refbits']} | {int(row['cache_cycles'])} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = arguments()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_cacti_env(args)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[args.db][args.collection]
        docs = latest_documents(collection, args)
        optimal = select_optimal(docs, args.max_total_capacity)
        rows, errors = calculate_rows(collection, optimal, args)
    finally:
        client.close()
    write_csv(args.output_dir / "nyc_mp_optimal_power.csv", rows)
    write_csv(
        args.output_dir / "errors.csv",
        errors,
        ["architecture", "signature", "source_id", "error"],
    )
    plot(rows, args.output_dir)
    write_report(args.output_dir / "REPORT.md", rows, len(docs), errors)
    print(
        f"source_configs={len(docs)} optimal_points={len(optimal)} "
        f"power_rows={len(rows)} errors={len(errors)} output={args.output_dir}"
    )
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
