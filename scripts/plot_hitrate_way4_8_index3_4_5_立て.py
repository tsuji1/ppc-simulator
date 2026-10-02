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
            "Plot UnifiedCache hitrate graph for way=4/8 and cacheindextype=2/3/4/5 "
            "from MongoDB."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI (default: DATABASE_URL env or mongodb://localhost:27017/)",
    )
    parser.add_argument("--db", default="db", help="Database name (default: db)")
    parser.add_argument(
        "--collection",
        default="simulator_results",
        help="Collection name (default: simulator_results)",
    )
    parser.add_argument("--rule-file-name", default=None, help="Optional rule_file_name filter")
    parser.add_argument("--trace-file-name", default=None, help="Optional trace_file_name filter")
    parser.add_argument(
        "--output",
        default="scripts/unified_way4_8_index2_3_4_5_hitrate.png",
        help="Output PNG path",
    )
    return parser.parse_args()


def fetch_data(args: argparse.Namespace) -> List[dict]:
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    collection = client[args.db][args.collection]

    query = {
        "simulator_result.type": "UnifiedCache",
        "simulator_result.parameter.way": {"$in": [4, 8]},
        "simulator_result.parameter.cacheindextype": {"$in": INDEX_TYPES},
    }
    if args.rule_file_name:
        query["rule_file_name"] = args.rule_file_name
    if args.trace_file_name:
        query["trace_file_name"] = args.trace_file_name

    projection = {
        "_id": 0,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter.way": 1,
        "simulator_result.parameter.cacheindextype": 1,
        "simulator_result.parameter.size": 1,
        "rule_file_name": 1,
        "trace_file_name": 1,
    }

    try:
        docs = list(collection.find(query, projection))
    finally:
        client.close()
    return docs


def build_series(docs: List[dict]) -> Tuple[Dict[Tuple[int, int], List[Tuple[int, float]]], List[int]]:
    series = defaultdict(list)
    all_sizes = set()

    for doc in docs:
        sim = doc.get("simulator_result", {})
        param = sim.get("parameter", {})
        hitrate = sim.get("hitrate")
        way = param.get("way")
        index = param.get("cacheindextype")
        size = param.get("size")

        if hitrate is None or way is None or index is None or size is None:
            continue

        way_i = int(way)
        index_i = int(index)
        size_i = int(size)
        hitrate_f = float(hitrate) * 100.0

        series[(way_i, index_i)].append((size_i, hitrate_f))
        all_sizes.add(size_i)

    for key in series:
        series[key].sort(key=lambda x: x[0])

    return series, sorted(all_sizes)


def plot_graph(series: Dict[Tuple[int, int], List[Tuple[int, float]]], sizes: List[int], output_path: str) -> None:
    color_by_index = {
        2: "#e67e22",
        3: "#d73027",
        4: "#1a9850",
        5: "#4575b4",
    }
    linestyle_by_way = {
        4: "-",
        8: "--",
    }
    marker_by_way = {
        4: "o",
        8: "s",
    }

    plt.figure(figsize=(11, 6))

    for way in [4, 8]:
        for index in INDEX_TYPES:
            points = series.get((way, index), [])
            if not points:
                continue
            x = [p[0] for p in points]
            y = [p[1] for p in points]
            plt.plot(
                x,
                y,
                label=f"way={way}, {index_label(index)}",
                color=color_by_index[index],
                linestyle=linestyle_by_way[way],
                marker=marker_by_way[way],
                linewidth=2,
            )

    plt.title("UnifiedCache Hitrate (way=4/8, IDEAL/index24/index20/index18)")
    plt.xlabel("Cache Size")
    plt.ylabel("Hit Rate (%)")
    plt.grid(True, alpha=0.3)
    if sizes:
        plt.xticks(sizes, [str(s) for s in sizes])
    plt.legend()
    plt.tight_layout()

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    plt.savefig(output_path, dpi=160)
    plt.close()


def main() -> int:
    args = parse_args()
    docs = fetch_data(args)
    if not docs:
        print("No documents found for way=4/8 and index=2/3/4/5.", file=sys.stderr)
        return 1

    series, sizes = build_series(docs)
    if not series:
        print("Documents found, but no plottable records.", file=sys.stderr)
        return 1

    plot_graph(series, sizes, args.output)

    print(f"Saved graph: {args.output}")
    for key in sorted(series.keys()):
        way, index = key
        values = [v for _, v in series[key]]
        print(
            f"way={way}, {index_label(index)}, points={len(values)}, "
            f"avg={sum(values)/len(values):.4f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
