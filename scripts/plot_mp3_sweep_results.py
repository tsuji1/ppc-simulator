#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "matplotlib>=3.7",
#   "pymongo>=4.6",
# ]
# ///
"""Plot 3-layer MultiLayerCacheExclusive sweep results from MongoDB."""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient

from plot_mp3_sweep_overview import create_overview


TRACE_SPECS = {
    "chicago-anon": {
        "trace": "equinix-chicago.dirB.20140320-140100.UTC.anon.pcap",
        "rule": "route-views.chicago.rib.20160628.1400.unique.rule",
        "label": "Chicago anon",
        "color": "#1f77b4",
    },
    "wide-anon-20260327": {
        "trace": "202603271400.pcap",
        "rule": "rib.20260327.0600.unique.rule",
        "label": "WIDE anon 2026-03",
        "color": "#2ca02c",
    },
    "nyc-anon": {
        "trace": "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap",
        "rule": "rrc11.bview.20190117.1600.unique.rule",
        "label": "NYC anon",
        "color": "#d62728",
    },
}


@dataclass(frozen=True)
class ResultPoint:
    trace_key: str
    trace_label: str
    trace_file_name: str
    rule_file_name: str
    timestamp: Any
    processed: int
    hit: int
    hitrate_percent: float
    missrate_percent: float
    l1_size: int
    l2_size: int
    l3_size: int
    l1_refbits: int
    l2_refbits: int
    l3_refbits: int

    @property
    def total_capacity(self) -> int:
        return self.l1_size + self.l2_size + self.l3_size

    @property
    def capacity_signature(self) -> str:
        return f"{self.l1_size}-{self.l2_size}-{self.l3_size}"

    @property
    def refbits_signature(self) -> str:
        return f"{self.l1_refbits}-{self.l2_refbits}-{self.l3_refbits}"


@dataclass(frozen=True)
class VILPoint:
    trace_key: str
    trace_label: str
    trace_file_name: str
    rule_file_name: str
    timestamp: Any
    processed: int
    hit: int
    hitrate_percent: float
    missrate_percent: float
    capacity: int
    way: int
    cache_index_type: int
    cache_index_label: str
    tag_length: str
    policy: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create best-only, Pareto, and heatmap plots for MP3 sweep results."
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI",
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument(
        "--processed",
        type=int,
        default=None,
        help="Optional processed packet count filter. Default: use any processed count.",
    )
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--start-exp", type=int, default=10)
    parser.add_argument("--end-exp", type=int, default=13)
    parser.add_argument(
        "--min-refbits",
        type=int,
        default=10,
        help="Minimum L2/L3 prefix length for the MP3 sweep. Default: 10.",
    )
    parser.add_argument("--vil-start-exp", type=int, default=10)
    parser.add_argument("--vil-end-exp", type=int, default=15)
    parser.add_argument(
        "--vil-index-types",
        default="2,16,17,18,19,20,21,22,23,24",
        help="VIL/UnifiedCache index types. Default: IDEAL and PREFIX16..24.",
    )
    parser.add_argument("--vil-policy", default="exclusive")
    parser.add_argument(
        "--trace",
        action="append",
        choices=sorted(TRACE_SPECS.keys()),
        help="Trace key to include. Repeatable. Default: all built-in MP3 targets.",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/mp3_sweep_results",
        help="Directory for CSV, PNG, and Markdown outputs.",
    )
    parser.add_argument(
        "--missrate-ymax",
        type=float,
        default=None,
        help="Optional y-axis maximum for miss-rate plots.",
    )
    return parser.parse_args()


def nested_get(obj: dict[str, Any], path: Iterable[str], default: Any = None) -> Any:
    cur: Any = obj
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def layer_tuple(layer: dict[str, Any]) -> tuple[int, int, int]:
    return (int(layer.get("size", -1)), int(layer.get("way", -1)), int(layer.get("refbits", -1)))


def valid_layers(
    layers: list[dict[str, Any]],
    way: int,
    capacities: set[int],
    min_refbits: int,
) -> bool:
    if len(layers) != 3:
        return False
    parsed = [layer_tuple(layer) for layer in layers]
    if any(layer_way != way for _, layer_way, _ in parsed):
        return False
    if any(size not in capacities for size, _, _ in parsed):
        return False
    refbits = [refbits for _, _, refbits in parsed]
    return refbits[0] == 24 and refbits[0] > refbits[1] > refbits[2] >= min_refbits


def result_key(point: ResultPoint) -> tuple[Any, ...]:
    return (
        point.trace_key,
        point.l1_size,
        point.l2_size,
        point.l3_size,
        point.l1_refbits,
        point.l2_refbits,
        point.l3_refbits,
    )


def vil_index_label(index_type: int) -> str:
    if index_type == 2:
        return "IDEAL"
    if 6 <= index_type <= 24:
        return f"PREFIX{index_type}"
    if 100 <= index_type <= 124:
        return f"PREFIX{index_type - 100}_NOHASH"
    return f"INDEX{index_type}"


def normalize_tag_length(raw: Any) -> tuple[tuple[int, int], ...]:
    normalized = []
    for item in raw or []:
        if isinstance(item, dict):
            values = list(item.values())
        else:
            values = list(item)
        if len(values) >= 2:
            normalized.append((int(values[0]), int(values[1])))
    return tuple(normalized)


def fetch_vil_points(collection: Any, args: argparse.Namespace, trace_keys: list[str]) -> list[VILPoint]:
    capacities = {2**exp for exp in range(args.vil_start_exp, args.vil_end_exp + 1)}
    index_types = {int(value.strip()) for value in args.vil_index_types.split(",") if value.strip()}
    expected_tag_length = tuple((9, 24) for _ in range(args.way))
    latest: dict[tuple[str, int, int], VILPoint] = {}
    projection = {
        "_id": 0,
        "timestamp": 1,
        "trace_file_name": 1,
        "rule_file_name": 1,
        "simulator_result.processed": 1,
        "simulator_result.hit": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter": 1,
    }
    for trace_key in trace_keys:
        spec = TRACE_SPECS[trace_key]
        query = {
            "simulator_result.type": "UnifiedCache",
            "trace_file_name": spec["trace"],
            "rule_file_name": spec["rule"],
            "simulator_result.parameter.way": args.way,
            "simulator_result.parameter.size": {"$in": sorted(capacities)},
            "simulator_result.parameter.cacheindextype": {"$in": sorted(index_types)},
            "simulator_result.parameter.insertionpolicy": args.vil_policy,
        }
        for doc in collection.find(query, projection):
            sim = doc.get("simulator_result", {})
            param = sim.get("parameter", {})
            tag_length = normalize_tag_length(param.get("cachetaglength", []))
            if tag_length != expected_tag_length:
                continue
            processed = sim.get("processed")
            hit = sim.get("hit")
            hitrate = sim.get("hitrate")
            if processed is None or hit is None or hitrate is None:
                continue
            capacity = int(param.get("size", 0))
            index_type = int(param.get("cacheindextype", -1))
            hitrate_percent = float(hitrate) * 100.0
            point = VILPoint(
                trace_key=trace_key,
                trace_label=str(spec["label"]),
                trace_file_name=str(doc.get("trace_file_name", "")),
                rule_file_name=str(doc.get("rule_file_name", "")),
                timestamp=doc.get("timestamp"),
                processed=int(processed),
                hit=int(hit),
                hitrate_percent=hitrate_percent,
                missrate_percent=100.0 - hitrate_percent,
                capacity=capacity,
                way=int(param.get("way", 0)),
                cache_index_type=index_type,
                cache_index_label=vil_index_label(index_type),
                tag_length=",".join(f"{start}-{end}" for start, end in tag_length),
                policy=str(param.get("insertionpolicy", "")),
            )
            key = (trace_key, capacity, index_type)
            previous = latest.get(key)
            if previous is None or point.processed > previous.processed:
                latest[key] = point
            elif point.processed == previous.processed and (point.timestamp or "") > (previous.timestamp or ""):
                latest[key] = point
    return sorted(latest.values(), key=lambda p: (p.trace_key, p.capacity, p.cache_index_type))


def fetch_points(collection: Any, args: argparse.Namespace, trace_keys: list[str]) -> list[ResultPoint]:
    capacities = {2**exp for exp in range(args.start_exp, args.end_exp + 1)}
    latest: dict[tuple[Any, ...], ResultPoint] = {}

    projection = {
        "_id": 0,
        "timestamp": 1,
        "trace_file_name": 1,
        "rule_file_name": 1,
        "simulator_result.type": 1,
        "simulator_result.processed": 1,
        "simulator_result.hit": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.cachelayers": 1,
    }

    for trace_key in trace_keys:
        spec = TRACE_SPECS[trace_key]
        query = {
            "simulator_result.type": "MultiLayerCacheExclusive",
            "trace_file_name": spec["trace"],
            "rule_file_name": spec["rule"],
        }
        if args.processed is not None:
            query["simulator_result.processed"] = args.processed
        for doc in collection.find(query, projection):
            layers = nested_get(doc, ("simulator_result", "parameter", "cachelayers"), [])
            if not isinstance(layers, list) or not valid_layers(layers, args.way, capacities, args.min_refbits):
                continue
            sim = doc.get("simulator_result", {})
            hitrate = sim.get("hitrate")
            processed = sim.get("processed")
            hit = sim.get("hit")
            if hitrate is None or processed is None or hit is None:
                continue
            parsed_layers = [layer_tuple(layer) for layer in layers]
            hitrate_percent = float(hitrate) * 100.0
            point = ResultPoint(
                trace_key=trace_key,
                trace_label=str(spec["label"]),
                trace_file_name=str(doc.get("trace_file_name", "")),
                rule_file_name=str(doc.get("rule_file_name", "")),
                timestamp=doc.get("timestamp"),
                processed=int(processed),
                hit=int(hit),
                hitrate_percent=hitrate_percent,
                missrate_percent=100.0 - hitrate_percent,
                l1_size=parsed_layers[0][0],
                l2_size=parsed_layers[1][0],
                l3_size=parsed_layers[2][0],
                l1_refbits=parsed_layers[0][2],
                l2_refbits=parsed_layers[1][2],
                l3_refbits=parsed_layers[2][2],
            )
            key = result_key(point)
            previous = latest.get(key)
            if previous is None:
                latest[key] = point
            elif point.processed > previous.processed:
                latest[key] = point
            elif point.processed == previous.processed and (point.timestamp or "") > (previous.timestamp or ""):
                latest[key] = point

    return sorted(latest.values(), key=lambda p: (p.trace_key, p.total_capacity, p.missrate_percent))


def best_by_total_capacity(points: list[ResultPoint]) -> list[ResultPoint]:
    best: dict[tuple[str, int], ResultPoint] = {}
    for point in points:
        key = (point.trace_key, point.total_capacity)
        previous = best.get(key)
        if previous is None or point.missrate_percent < previous.missrate_percent:
            best[key] = point
    return sorted(best.values(), key=lambda p: (p.trace_key, p.total_capacity))


def pareto_frontier(points: list[ResultPoint]) -> list[ResultPoint]:
    best_per_capacity = best_by_total_capacity(points)
    by_trace: dict[str, list[ResultPoint]] = defaultdict(list)
    for point in best_per_capacity:
        by_trace[point.trace_key].append(point)

    frontier: list[ResultPoint] = []
    for trace_points in by_trace.values():
        current_best = float("inf")
        for point in sorted(trace_points, key=lambda p: (p.total_capacity, p.missrate_percent)):
            if point.missrate_percent < current_best:
                frontier.append(point)
                current_best = point.missrate_percent
    return sorted(frontier, key=lambda p: (p.trace_key, p.total_capacity))


def best_overall_by_trace(points: list[ResultPoint]) -> dict[str, ResultPoint]:
    best: dict[str, ResultPoint] = {}
    for point in points:
        previous = best.get(point.trace_key)
        if previous is None or point.missrate_percent < previous.missrate_percent:
            best[point.trace_key] = point
    return best


def write_points_csv(path: Path, points: list[ResultPoint]) -> None:
    fields = [
        "trace_key",
        "trace_label",
        "trace_file_name",
        "rule_file_name",
        "processed",
        "hit",
        "hitrate_percent",
        "missrate_percent",
        "total_capacity",
        "l1_size",
        "l2_size",
        "l3_size",
        "refbits",
        "capacity_signature",
        "timestamp",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "trace_key": point.trace_key,
                    "trace_label": point.trace_label,
                    "trace_file_name": point.trace_file_name,
                    "rule_file_name": point.rule_file_name,
                    "processed": point.processed,
                    "hit": point.hit,
                    "hitrate_percent": f"{point.hitrate_percent:.8f}",
                    "missrate_percent": f"{point.missrate_percent:.8f}",
                    "total_capacity": point.total_capacity,
                    "l1_size": point.l1_size,
                    "l2_size": point.l2_size,
                    "l3_size": point.l3_size,
                    "refbits": point.refbits_signature,
                    "capacity_signature": point.capacity_signature,
                    "timestamp": point.timestamp,
                }
            )


def write_vil_points_csv(path: Path, points: list[VILPoint]) -> None:
    fields = [
        "trace_key",
        "trace_label",
        "trace_file_name",
        "rule_file_name",
        "processed",
        "hit",
        "hitrate_percent",
        "missrate_percent",
        "capacity",
        "way",
        "cache_index_type",
        "cache_index_label",
        "tag_length",
        "policy",
        "timestamp",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "trace_key": point.trace_key,
                    "trace_label": point.trace_label,
                    "trace_file_name": point.trace_file_name,
                    "rule_file_name": point.rule_file_name,
                    "processed": point.processed,
                    "hit": point.hit,
                    "hitrate_percent": f"{point.hitrate_percent:.8f}",
                    "missrate_percent": f"{point.missrate_percent:.8f}",
                    "capacity": point.capacity,
                    "way": point.way,
                    "cache_index_type": point.cache_index_type,
                    "cache_index_label": point.cache_index_label,
                    "tag_length": point.tag_length,
                    "policy": point.policy,
                    "timestamp": point.timestamp,
                }
            )


def configure_total_capacity_axis(ax: Any, points: list[ResultPoint]) -> None:
    totals = sorted({p.total_capacity for p in points})
    if not totals:
        return
    ax.set_xlim(min(totals) * 0.95, max(totals) * 1.05)
    step = 4096
    ticks = [tick for tick in range(4096, max(totals) + step, step) if tick >= min(totals)]
    if ticks:
        ax.set_xticks(ticks)
        ax.set_xticklabels([f"{tick // 1024}K" for tick in ticks])


def plot_best_only(path: Path, best_points: list[ResultPoint], ymax: float | None) -> None:
    fig, ax = plt.subplots(figsize=(11, 6.4))
    by_trace: dict[str, list[ResultPoint]] = defaultdict(list)
    for point in best_points:
        by_trace[point.trace_key].append(point)

    for trace_key in sorted(by_trace):
        points = sorted(by_trace[trace_key], key=lambda p: p.total_capacity)
        spec = TRACE_SPECS[trace_key]
        ax.plot(
            [p.total_capacity for p in points],
            [p.missrate_percent for p in points],
            marker="o",
            linewidth=2.2,
            color=spec["color"],
            label=spec["label"],
        )
    ax.set_title("Best MP3 miss rate by total capacity")
    ax.set_xlabel("Total cache entries (L1 + L2 + L3)")
    ax.set_ylabel("Best miss rate (%)")
    if ymax is not None:
        ax.set_ylim(0, ymax)
    else:
        ax.set_ylim(bottom=0)
    configure_total_capacity_axis(ax, best_points)
    ax.grid(True, alpha=0.28)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_pareto(path: Path, points: list[ResultPoint], frontier: list[ResultPoint], ymax: float | None) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 6.8))
    by_trace: dict[str, list[ResultPoint]] = defaultdict(list)
    frontier_by_trace: dict[str, list[ResultPoint]] = defaultdict(list)
    for point in points:
        by_trace[point.trace_key].append(point)
    for point in frontier:
        frontier_by_trace[point.trace_key].append(point)

    for trace_key in sorted(by_trace):
        spec = TRACE_SPECS[trace_key]
        trace_points = by_trace[trace_key]
        ax.scatter(
            [p.total_capacity for p in trace_points],
            [p.missrate_percent for p in trace_points],
            s=9,
            alpha=0.16,
            color=spec["color"],
            linewidths=0,
            label=f"{spec['label']} all",
        )
        front = sorted(frontier_by_trace[trace_key], key=lambda p: p.total_capacity)
        if front:
            ax.plot(
                [p.total_capacity for p in front],
                [p.missrate_percent for p in front],
                marker="o",
                linewidth=2.4,
                color=spec["color"],
                label=f"{spec['label']} frontier",
            )
    ax.set_title("MP3 sweep Pareto frontier")
    ax.set_xlabel("Total cache entries (L1 + L2 + L3)")
    ax.set_ylabel("Miss rate (%)")
    if ymax is not None:
        ax.set_ylim(0, ymax)
    else:
        ax.set_ylim(bottom=0)
    configure_total_capacity_axis(ax, points)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8, ncols=2)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_best_config_heatmap(path: Path, points: list[ResultPoint], best_overall: dict[str, ResultPoint]) -> None:
    trace_keys = [key for key in sorted(TRACE_SPECS) if key in best_overall]
    if not trace_keys:
        return
    fig, axes = plt.subplots(1, len(trace_keys), figsize=(5.2 * len(trace_keys), 4.9), squeeze=False)
    for ax, trace_key in zip(axes[0], trace_keys):
        best = best_overall[trace_key]
        matching = [
            p
            for p in points
            if p.trace_key == trace_key
            and p.refbits_signature == best.refbits_signature
            and p.l3_size == best.l3_size
        ]
        grid: dict[tuple[int, int], ResultPoint] = {}
        for point in matching:
            key = (point.l1_size, point.l2_size)
            previous = grid.get(key)
            if previous is None or point.missrate_percent < previous.missrate_percent:
                grid[key] = point

        xs = sorted({p.l1_size for p in matching})
        ys = sorted({p.l2_size for p in matching})
        matrix = []
        for y in ys:
            row = []
            for x in xs:
                point = grid.get((x, y))
                row.append(point.missrate_percent if point else float("nan"))
            matrix.append(row)

        image = ax.imshow(matrix, origin="lower", aspect="auto", cmap="viridis_r")
        ax.set_title(
            f"{TRACE_SPECS[trace_key]['label']}\nref /{best.refbits_signature.replace('-', '/')} L3={best.l3_size}"
        )
        ax.set_xlabel("L1 entries")
        ax.set_ylabel("L2 entries")
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels([str(x) for x in xs], rotation=45, ha="right")
        ax.set_yticks(range(len(ys)))
        ax.set_yticklabels([str(y) for y in ys])
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="miss rate (%)")
    fig.suptitle("Capacity allocation heatmap at each trace's best refbits and L3")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_report(
    path: Path,
    points: list[ResultPoint],
    best_points: list[ResultPoint],
    frontier: list[ResultPoint],
    vil_points: list[VILPoint],
    min_refbits: int,
) -> None:
    best_overall = best_overall_by_trace(points)
    best_vil: dict[str, VILPoint] = {}
    for point in vil_points:
        previous = best_vil.get(point.trace_key)
        if previous is None or point.missrate_percent < previous.missrate_percent:
            best_vil[point.trace_key] = point
    lines = [
        "# MP3 sweep results",
        "",
        "- cache: `MultiLayerCacheExclusive`, 3 layers, way 8",
        "- capacity sweep: each layer `2^10..2^13`",
        f"- refbits sweep: first layer `/24`, later layers strictly descending from `/23..../{min_refbits}`",
        "- VIL: `UnifiedCache` / Prefix-Shared-Cache, way 8, exclusive, tag range `9-24` x 8 ways",
        "- VIL index sweep: `IDEAL` and `PREFIX16..PREFIX24`; capacity `2^10..2^15` entries",
        "- MP3 and VIL capacity plots compare entry counts, not equal bitsum or equal SRAM area",
        f"- documents used: `{len(points)}` latest unique configurations",
        f"- VIL documents used: `{len(vil_points)}` latest unique configurations",
        f"- best-by-total-capacity rows: `{len(best_points)}`",
        f"- Pareto frontier rows: `{len(frontier)}`",
        "",
        "## Best overall",
        "",
        "| trace | miss rate | hit rate | total capacity | capacities | refbits |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for trace_key in sorted(best_overall):
        point = best_overall[trace_key]
        lines.append(
            f"| {point.trace_label} | {point.missrate_percent:.4f}% | {point.hitrate_percent:.4f}% | "
            f"{point.total_capacity} | {point.capacity_signature} | /{point.refbits_signature.replace('-', '/')} |"
        )
    lines.extend(
        [
            "",
            "## VIL best overall",
            "",
            "| trace | miss rate | hit rate | capacity | index |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for trace_key in sorted(best_vil):
        point = best_vil[trace_key]
        lines.append(
            f"| {point.trace_label} | {point.missrate_percent:.4f}% | {point.hitrate_percent:.4f}% | "
            f"{point.capacity} | {point.cache_index_label} |"
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            "- `all_points.csv`: all latest unique sweep points used by the plots",
            "- `vil_points.csv`: VIL (UnifiedCache) IDEAL/PREFIX16..24 capacity sweep points",
            "- `best_by_total_capacity.csv`: one best point per trace and total capacity",
            "- `pareto_frontier.csv`: non-dominated points per trace",
            "- `best_overall_by_trace.csv`: single best point per trace",
            "- `best_missrate_by_total_capacity.png`: compact result figure",
            "- `pareto_frontier.png`: full sweep distribution plus frontier",
            "- `best_config_heatmap.png`: capacity allocation view around each trace's best setting",
            "- `overview.png`: one-page best-capacity, Pareto, and complete refbits-pair overview",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    trace_keys = args.trace or sorted(TRACE_SPECS.keys())
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[args.db][args.collection]
        points = fetch_points(collection, args, trace_keys)
        vil_points = fetch_vil_points(collection, args, trace_keys)
    finally:
        client.close()

    if not points:
        print("No MP3 sweep results found for the selected traces.", flush=True)
        return 1

    best_points = best_by_total_capacity(points)
    frontier = pareto_frontier(points)
    best_overall_points = sorted(best_overall_by_trace(points).values(), key=lambda p: p.trace_key)

    write_points_csv(outdir / "all_points.csv", points)
    write_vil_points_csv(outdir / "vil_points.csv", vil_points)
    write_points_csv(outdir / "best_by_total_capacity.csv", best_points)
    write_points_csv(outdir / "pareto_frontier.csv", frontier)
    write_points_csv(outdir / "best_overall_by_trace.csv", best_overall_points)
    plot_best_only(outdir / "best_missrate_by_total_capacity.png", best_points, args.missrate_ymax)
    plot_pareto(outdir / "pareto_frontier.png", points, frontier, args.missrate_ymax)
    plot_best_config_heatmap(outdir / "best_config_heatmap.png", points, best_overall_by_trace(points))
    overview_summary = create_overview(
        outdir / "all_points.csv",
        outdir / "overview.png",
        outdir / "vil_points.csv",
    )
    write_report(outdir / "REPORT.md", points, best_points, frontier, vil_points, args.min_refbits)

    print(f"Saved report directory: {outdir}")
    print(f"all points: {len(points)}")
    print(f"VIL points: {len(vil_points)}")
    for trace_key in trace_keys:
        count = sum(1 for p in points if p.trace_key == trace_key)
        refbits_pair_count = math.comb(24 - args.min_refbits, 2)
        expected = (args.end_exp - args.start_exp + 1) ** 3 * refbits_pair_count
        pair_count = overview_summary.get(trace_key, (0, 0))[1]
        vil_count = sum(1 for p in vil_points if p.trace_key == trace_key)
        print(
            f"{trace_key}: MP {count}/{expected} points, {pair_count}/{refbits_pair_count} refbits pairs; "
            f"VIL {vil_count}/60 points"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
