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
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


SeriesPoints = Dict[str, Dict[int, List[float]]]
INDEX_TYPES = [2, 3, 4, 5]
INDEX_LABELS = {
    2: "IDEAL",
    3: "index24",
    4: "index20",
    5: "index18",
}


def index_label(index: int) -> str:
    return INDEX_LABELS.get(index, f"index{index}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plot all-in-one hitrate graph with UnifiedCache(way4/8,index2/3/4/5), "
            "Exclusive(/24,/18,way4/8), and FullAssociative."
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
        "--output-prefix",
        default="scripts/hitrate_全部盛り_index2",
        help="Output file prefix",
    )
    return parser.parse_args()


def base_query(args: argparse.Namespace) -> Dict[str, object]:
    q: Dict[str, object] = {}
    if args.rule_file_name:
        q["rule_file_name"] = args.rule_file_name
    if args.trace_file_name:
        q["trace_file_name"] = args.trace_file_name
    return q


def add_point(series: SeriesPoints, label: str, x: int, y_percent: float) -> None:
    series[label][x].append(y_percent)


def fetch_unified(collection, common_query: Dict[str, object], series: SeriesPoints) -> int:
    q = dict(common_query)
    q.update(
        {
            "simulator_result.type": "UnifiedCache",
            "simulator_result.parameter.way": {"$in": [4, 8]},
            "simulator_result.parameter.cacheindextype": {"$in": INDEX_TYPES},
        }
    )
    proj = {
        "_id": 0,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.way": 1,
        "simulator_result.parameter.cacheindextype": 1,
        "simulator_result.parameter.size": 1,
    }
    count = 0
    for doc in collection.find(q, proj):
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {})
        hitrate = sim.get("hitrate")
        way = param.get("way")
        index = param.get("cacheindextype")
        size = param.get("size")
        if None in (hitrate, way, index, size):
            continue
        label = f"Unified way={int(way)} {index_label(int(index))}"
        add_point(series, label, int(size), float(hitrate) * 100.0)
        count += 1
    return count


def fetch_exclusive_24_18(collection, common_query: Dict[str, object], series: SeriesPoints) -> int:
    count = 0
    for way in (4, 8):
        q = dict(common_query)
        q.update(
            {
                "simulator_result.type": "MultiLayerCacheExclusive",
                "simulator_result.parameter.cachelayers": {
                    "$all": [
                        {"$elemMatch": {"way": way, "refbits": 24}},
                        {"$elemMatch": {"way": way, "refbits": 18}},
                    ]
                },
            }
        )
        proj = {
            "_id": 0,
            "simulator_result.hitrate": 1,
            "simulator_result.parameter.cachelayers.size": 1,
        }
        for doc in collection.find(q, proj):
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
            total_size = int(l1_size) + int(l2_size)
            label = f"Exclusive /24,/18 way={way}"
            add_point(series, label, total_size, float(hitrate) * 100.0)
            count += 1
    return count


def fetch_full_associative(collection, common_query: Dict[str, object], series: SeriesPoints) -> Tuple[int, str]:
    q = dict(common_query)
    q.update({"simulator_result.type": "FullAssociativeLRUCache"})
    proj = {
        "_id": 0,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.size": 1,
        "simulator_result.parameter.way": 1,
    }
    docs = list(collection.find(q, proj))
    if not docs:
        return 0, "FullAssociative data not found"

    has_way = any(
        doc.get("simulator_result", {}).get("parameter", {}).get("way") in (4, 8)
        for doc in docs
    )
    count = 0
    if has_way:
        for doc in docs:
            sim = doc.get("simulator_result", {})
            param = sim.get("parameter", {})
            hitrate = sim.get("hitrate")
            size = param.get("size")
            way = param.get("way")
            if hitrate is None or size is None or way not in (4, 8):
                continue
            label = f"FullAssociative way={int(way)}"
            add_point(series, label, int(size), float(hitrate) * 100.0)
            count += 1
        return count, "FullAssociative way=4/8 points plotted"

    for doc in docs:
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {})
        hitrate = sim.get("hitrate")
        size = param.get("size")
        if hitrate is None or size is None:
            continue
        add_point(series, "FullAssociative (way field not stored)", int(size), float(hitrate) * 100.0)
        count += 1
    return count, "FullAssociative docs have no way field; plotted as one baseline"


def collapse_avg(series: SeriesPoints) -> Dict[str, List[Tuple[int, float]]]:
    collapsed: Dict[str, List[Tuple[int, float]]] = {}
    for label, x_to_values in series.items():
        points: List[Tuple[int, float]] = []
        for x in sorted(x_to_values.keys()):
            vals = x_to_values[x]
            points.append((x, sum(vals) / len(vals)))
        collapsed[label] = points
    return collapsed


def style_for_label(label: str) -> Dict[str, object]:
    if label.startswith("Unified way=4 IDEAL"):
        return {"color": "#e67e22", "linestyle": "-", "marker": "o"}
    if label.startswith("Unified way=4 index24"):
        return {"color": "#c0392b", "linestyle": "-", "marker": "o"}
    if label.startswith("Unified way=4 index20"):
        return {"color": "#27ae60", "linestyle": "-", "marker": "o"}
    if label.startswith("Unified way=4 index18"):
        return {"color": "#2980b9", "linestyle": "-", "marker": "o"}
    if label.startswith("Unified way=8 IDEAL"):
        return {"color": "#e67e22", "linestyle": "--", "marker": "s"}
    if label.startswith("Unified way=8 index24"):
        return {"color": "#c0392b", "linestyle": "--", "marker": "s"}
    if label.startswith("Unified way=8 index20"):
        return {"color": "#27ae60", "linestyle": "--", "marker": "s"}
    if label.startswith("Unified way=8 index18"):
        return {"color": "#2980b9", "linestyle": "--", "marker": "s"}
    if label.startswith("Exclusive /24,/18 way=4"):
        return {"color": "#8e44ad", "linestyle": "-", "marker": "^", "linewidth": 2.5}
    if label.startswith("Exclusive /24,/18 way=8"):
        return {"color": "#8e44ad", "linestyle": "--", "marker": "v", "linewidth": 2.5}
    if label.startswith("FullAssociative"):
        return {"color": "#2c3e50", "linestyle": "-.", "marker": "D", "linewidth": 2.5}
    return {"linewidth": 2}


def plot(collapsed: Dict[str, List[Tuple[int, float]]], ymin: float, output_path: str, title_suffix: str) -> None:
    plt.figure(figsize=(13, 7))

    for label in sorted(collapsed.keys()):
        points = collapsed[label]
        if not points:
            continue
        x = [p[0] for p in points]
        y = [p[1] for p in points]
        kwargs = style_for_label(label)
        if "linewidth" not in kwargs:
            kwargs["linewidth"] = 2
        plt.plot(x, y, label=label, **kwargs)

    plt.title(f"Hitrate Comparison ({title_suffix})")
    plt.xlabel("Cache Size (Unified/Full=Size, Exclusive=Layer1+Layer2)")
    plt.ylabel("Hit Rate (%)")
    plt.ylim(ymin, 100.0)
    plt.grid(True, alpha=0.3)
    plt.legend(loc="best", fontsize=9)
    plt.tight_layout()

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_path, dpi=170)
    plt.close()


def main() -> int:
    args = parse_args()
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[args.db][args.collection]
        common_query = base_query(args)
        series: SeriesPoints = defaultdict(lambda: defaultdict(list))

        n_unified = fetch_unified(collection, common_query, series)
        n_exclusive = fetch_exclusive_24_18(collection, common_query, series)
        n_full, full_msg = fetch_full_associative(collection, common_query, series)
    finally:
        client.close()

    collapsed = collapse_avg(series)
    if not collapsed:
        print("No plottable records found.", file=sys.stderr)
        return 1

    output_50 = f"{args.output_prefix}_ymin50.png"
    output_98 = f"{args.output_prefix}_ymin98.png"

    plot(collapsed, 50.0, output_50, "Y min = 50%")
    plot(collapsed, 98.0, output_98, "Y min = 98%")

    print(f"Saved graph: {output_50}")
    print(f"Saved graph: {output_98}")
    print(f"Unified points: {n_unified}")
    print(f"Exclusive(/24,/18) points: {n_exclusive}")
    print(f"FullAssociative points: {n_full}")
    print(full_msg)
    for label in sorted(collapsed.keys()):
        vals = [v for _, v in collapsed[label]]
        print(f"{label}: points={len(vals)}, avg={sum(vals)/len(vals):.4f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
