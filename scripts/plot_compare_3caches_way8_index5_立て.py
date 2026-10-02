#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "matplotlib>=3.7",
#   "pymongo>=4.6",
# ]
# ///
import argparse
import os
import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


PointMap = Dict[int, List[float]]
UnifiedPointSeries = Dict[int, List[Tuple[int, float]]]


UNIFIED_INDEX_COLORS = {
    2: "#e67e22",
    3: "#d73027",
    4: "#1a9850",
    5: "#2980b9",
}
UNIFIED_INDEX_LABELS = {
    2: "IDEAL",
    3: "index24",
    4: "index20",
    5: "index18",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare FullAssociative, MultiPrefixCache(MultiLayerCacheExclusive), "
            "and UnifiedCache with constraints: way=8, Unified index=2/5, "
            "Exclusive refbits=/24,/18."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI",
    )
    parser.add_argument("--db", default="db", help="Database name")
    parser.add_argument("--collection", default="simulator_results", help="Collection name")
    parser.add_argument("--rule-file-name", default=None, help="Optional rule_file_name filter")
    parser.add_argument("--trace-file-name", default=None, help="Optional trace_file_name filter")
    parser.add_argument(
        "--max-capacity",
        type=float,
        default=None,
        help="Optional max capacity to include on x-axis; applied after --start-exp/--end-exp",
    )
    parser.add_argument(
        "--start-exp",
        type=int,
        default=6,
        help="Start exponent for capacity range, inclusive (default: 6)",
    )
    parser.add_argument(
        "--end-exp",
        type=int,
        default=14,
        help="End exponent for capacity range, inclusive (default: 14)",
    )
    parser.add_argument(
        "--hitrate-ymins",
        type=float,
        nargs="+",
        default=[50.0, 98.0, 99.0],
        help="Y-axis minimums for hitrate graphs (default: 50 98 99)",
    )
    parser.add_argument(
        "--missrate-ymaxes",
        type=float,
        nargs="+",
        default=[2.0],
        help="Y-axis maximums for missrate graphs (default: 2)",
    )
    parser.add_argument(
        "--unified-index-types",
        type=int,
        nargs="+",
        default=[2, 5],
        help="UnifiedCache cache index types to plot (default: 2 5)",
    )
    parser.add_argument(
        "--output-prefix",
        default="scripts/results/compare_3caches_way8_index2_5",
        help="Output file prefix",
    )
    return parser.parse_args()


def build_common_query(args: argparse.Namespace) -> Dict[str, object]:
    query: Dict[str, object] = {}
    if args.rule_file_name:
        query["rule_file_name"] = args.rule_file_name
    if args.trace_file_name:
        query["trace_file_name"] = args.trace_file_name
    return query


def avg_points(point_map: PointMap) -> List[Tuple[int, float]]:
    points = []
    for x in sorted(point_map.keys()):
        vals = point_map[x]
        points.append((x, sum(vals) / len(vals)))
    return points


def capacity_range(args: argparse.Namespace) -> List[int]:
    if args.start_exp > args.end_exp:
        raise ValueError("--start-exp must be less than or equal to --end-exp")

    capacities = [2**exp for exp in range(args.start_exp, args.end_exp + 1)]
    if args.max_capacity is not None:
        capacities = [capacity for capacity in capacities if capacity <= args.max_capacity]
    if not capacities:
        raise ValueError("No capacities remain after applying capacity filters")
    return capacities


def format_limit(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value).replace(".", "p")


def configure_capacity_axis(capacities: List[int]) -> None:
    plt.xscale("log", base=2)
    plt.xticks(capacities, [f"$2^{{{capacity.bit_length() - 1}}}$" for capacity in capacities])
    plt.xlim(capacities[0], capacities[-1])


def fetch_full_associative(
    collection, common_query: Dict[str, object], capacity_set: Set[int]
) -> PointMap:
    query = dict(common_query)
    query.update(
        {
            "simulator_result.type": "FullAssociativeLRUCache",
            "simulator_result.parameter.size": {"$in": sorted(capacity_set)},
        }
    )
    projection = {"_id": 0, "simulator_result.hitrate": 1, "simulator_result.parameter.size": 1}

    points: PointMap = defaultdict(list)
    for doc in collection.find(query, projection):
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {})
        hitrate = sim.get("hitrate")
        size = param.get("size")
        if hitrate is None or size is None:
            continue
        size_i = int(size)
        if size_i not in capacity_set:
            continue
        points[size_i].append(float(hitrate) * 100.0)
    return points


def fetch_unified_way8_indexes(
    collection, common_query: Dict[str, object], capacity_set: Set[int], index_types: List[int]
) -> Dict[int, PointMap]:
    query = dict(common_query)
    query.update(
        {
            "simulator_result.type": "UnifiedCache",
            "simulator_result.parameter.way": 8,
            "simulator_result.parameter.cacheindextype": {"$in": index_types},
            "simulator_result.parameter.size": {"$in": sorted(capacity_set)},
        }
    )
    projection = {
        "_id": 0,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.cacheindextype": 1,
        "simulator_result.parameter.size": 1,
    }

    points_by_index: Dict[int, PointMap] = {
        int(index_type): defaultdict(list) for index_type in index_types
    }
    for doc in collection.find(query, projection):
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {})
        hitrate = sim.get("hitrate")
        index = param.get("cacheindextype")
        size = param.get("size")
        if hitrate is None or index is None or size is None:
            continue
        index_i = int(index)
        size_i = int(size)
        if index_i not in points_by_index or size_i not in capacity_set:
            continue
        points_by_index[index_i][size_i].append(float(hitrate) * 100.0)
    return points_by_index


def unified_label(index: int) -> str:
    label = UNIFIED_INDEX_LABELS.get(index, f"index{index}")
    return f"UnifiedCache (way=8, {label})"


def unified_style(index: int) -> Dict[str, object]:
    return {
        "color": UNIFIED_INDEX_COLORS.get(index, "#7f8c8d"),
        "marker": "o",
        "linestyle": "-",
        "linewidth": 2.5,
        "label": unified_label(index),
    }


def fetch_multiprefix_exclusive_way8_24_18(
    collection, common_query: Dict[str, object], capacity_set: Set[int]
) -> PointMap:
    query = dict(common_query)
    query.update(
        {
            "simulator_result.type": "MultiLayerCacheExclusive",
            "simulator_result.parameter.cachelayers": {
                "$all": [
                    {"$elemMatch": {"way": 8, "refbits": 24}},
                    {"$elemMatch": {"way": 8, "refbits": 18}},
                ]
            },
        }
    )
    projection = {
        "_id": 0,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.cachelayers.size": 1,
    }

    points: PointMap = defaultdict(list)
    for doc in collection.find(query, projection):
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {})
        layers = param.get("cachelayers", [])
        hitrate = sim.get("hitrate")
        if hitrate is None or len(layers) < 2:
            continue
        l1_size = layers[0].get("size")
        l2_size = layers[1].get("size")
        if l1_size is None or l2_size is None:
            continue
        total_capacity = int(l1_size) + int(l2_size)
        if total_capacity not in capacity_set:
            continue
        points[total_capacity].append(float(hitrate) * 100.0)
    return points


def plot_hitrate(
    full_points: List[Tuple[int, float]],
    multi_points: List[Tuple[int, float]],
    unified_series: UnifiedPointSeries,
    capacities: List[int],
    ymin: float,
    output_path: str,
) -> None:
    plt.figure(figsize=(12, 7))

    if full_points:
        plt.plot(
            [x for x, _ in full_points],
            [y for _, y in full_points],
            color="#2c3e50",
            marker="D",
            linestyle="-.",
            linewidth=2.5,
            label="FullAssociative",
        )
    if multi_points:
        plt.plot(
            [x for x, _ in multi_points],
            [y for _, y in multi_points],
            color="#8e44ad",
            marker="^",
            linestyle="--",
            linewidth=2.5,
            label="MultiPrefixCache (Exclusive way=8, /24,/18)",
        )
    for index in sorted(unified_series.keys()):
        points = unified_series[index]
        if not points:
            continue
        plt.plot([x for x, _ in points], [y for _, y in points], **unified_style(index))

    plt.title("Hitrate Comparison")
    plt.xlabel("Capacity")
    plt.ylabel("Hit Rate (%)")
    plt.ylim(ymin, 100)
    configure_capacity_axis(capacities)
    plt.grid(True, alpha=0.3)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(output_path, dpi=170)
    plt.close()


def plot_missrate(
    full_points: List[Tuple[int, float]],
    multi_points: List[Tuple[int, float]],
    unified_series: UnifiedPointSeries,
    capacities: List[int],
    ymax: float,
    output_path: str,
) -> None:
    plt.figure(figsize=(12, 7))

    if full_points:
        plt.plot(
            [x for x, _ in full_points],
            [100.0 - y for _, y in full_points],
            color="#2c3e50",
            marker="D",
            linestyle="-.",
            linewidth=2.5,
            label="FullAssociative",
        )
    if multi_points:
        plt.plot(
            [x for x, _ in multi_points],
            [100.0 - y for _, y in multi_points],
            color="#8e44ad",
            marker="^",
            linestyle="--",
            linewidth=2.5,
            label="MultiPrefixCache (Exclusive way=8, /24,/18)",
        )
    for index in sorted(unified_series.keys()):
        points = unified_series[index]
        if not points:
            continue
        plt.plot(
            [x for x, _ in points],
            [100.0 - y for _, y in points],
            **unified_style(index),
        )

    plt.title("Miss Rate Comparison (100 - hitrate)")
    plt.xlabel("Capacity")
    plt.ylabel("Miss Rate (%)")
    plt.ylim(0, ymax)
    configure_capacity_axis(capacities)
    plt.grid(True, alpha=0.3)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(output_path, dpi=170)
    plt.close()


def main() -> int:
    args = parse_args()
    capacities = capacity_range(args)
    capacity_set = set(capacities)

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[args.db][args.collection]
        common_query = build_common_query(args)

        full = fetch_full_associative(collection, common_query, capacity_set)
        unified_by_index = fetch_unified_way8_indexes(
            collection, common_query, capacity_set, args.unified_index_types
        )
        multi = fetch_multiprefix_exclusive_way8_24_18(collection, common_query, capacity_set)
    finally:
        client.close()

    full_points = avg_points(full)
    unified_series: UnifiedPointSeries = {
        index: avg_points(points) for index, points in unified_by_index.items()
    }
    multi_points = avg_points(multi)

    if not (full_points or any(unified_series.values()) or multi_points):
        print("No data points to plot with current filters.", file=sys.stderr)
        return 1

    out_dir = os.path.dirname(args.output_prefix)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    outputs: List[str] = []
    for ymin in args.hitrate_ymins:
        output_hitrate = f"{args.output_prefix}_hitrate_ymin{format_limit(float(ymin))}.png"
        plot_hitrate(full_points, multi_points, unified_series, capacities, float(ymin), output_hitrate)
        outputs.append(output_hitrate)

    for ymax in args.missrate_ymaxes:
        output_missrate = f"{args.output_prefix}_missrate_ymax{format_limit(float(ymax))}.png"
        plot_missrate(full_points, multi_points, unified_series, capacities, float(ymax), output_missrate)
        outputs.append(output_missrate)

    for output in outputs:
        print(f"Saved graph: {output}")
    print(f"capacity range: 2^{args.start_exp}..2^{args.end_exp}")
    print(f"capacities: {', '.join(str(capacity) for capacity in capacities)}")
    print(f"FullAssociative points: {len(full_points)}")
    print(f"MultiPrefixCache points: {len(multi_points)}")
    for index in sorted(unified_series.keys()):
        print(f"UnifiedCache {UNIFIED_INDEX_LABELS.get(index, f'index{index}')} points: {len(unified_series[index])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
