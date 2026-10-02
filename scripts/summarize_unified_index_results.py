#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "pymongo>=4.6",
# ]
# ///
import argparse
import csv
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from pymongo import MongoClient


DEFAULT_INDEX_TYPES = [
    116,
    118,
    120,
    124,
    20816,
    21212,
    21608,
    30816,
    31212,
    31608,
    40816,
    41212,
    41608,
]


def parse_csv_ints(value: str) -> List[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def expected_capacities(start_exp: int, end_exp: int) -> List[int]:
    if start_exp > end_exp:
        raise ValueError("--start-exp must be <= --end-exp")
    return [1 << exp for exp in range(start_exp, end_exp + 1)]


def index_label(index_type: int) -> str:
    if 100 <= index_type <= 132:
        return f"direct-top-/{index_type - 100}"
    if 20000 <= index_type < 30000:
        start, width = divmod(index_type - 20000, 100)
        return f"direct-bit{start}-{start + width - 1}"
    if 30000 <= index_type < 40000:
        start, width = divmod(index_type - 30000, 100)
        return f"xor-bit{start}-{start + width - 1}"
    if 40000 <= index_type < 50000:
        start, width = divmod(index_type - 40000, 100)
        return f"crc-bit{start}-{start + width - 1}"
    return str(index_type)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create UnifiedCache hitrate tables by cache index type and capacity."
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI (default: DATABASE_URL or mongodb://localhost:27017/)",
    )
    parser.add_argument("--db", default="db", help="Database name")
    parser.add_argument("--collection", default="simulator_results", help="Collection name")
    parser.add_argument("--rule-file-name", default="rib.20260327.0600.unique.rule")
    parser.add_argument("--trace-file-name", default="2026-03-27.pcap")
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument("--start-exp", type=int, default=6)
    parser.add_argument("--end-exp", type=int, default=14)
    parser.add_argument(
        "--cache-index-types",
        default=",".join(str(value) for value in DEFAULT_INDEX_TYPES),
        help="Comma-separated cache index types.",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/unified_window_index_20260327",
        help="Directory for CSV/Markdown outputs.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="MongoDB server selection timeout in milliseconds.",
    )
    return parser.parse_args()


def nested_get(doc: Dict[str, object], path: Iterable[str]) -> object:
    cur: object = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def fetch_latest_rows(collection, args: argparse.Namespace, index_types: List[int], capacities: List[int]):
    query: Dict[str, object] = {
        "simulator_result.type": "UnifiedCache",
        "simulator_result.parameter.way": args.way,
        "simulator_result.parameter.cacheindextype": {"$in": index_types},
        "simulator_result.parameter.size": {"$in": capacities},
        "rule_file_name": args.rule_file_name,
        "trace_file_name": args.trace_file_name,
    }
    projection = {
        "_id": 0,
        "timestamp": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter.size": 1,
        "simulator_result.parameter.cacheindextype": 1,
    }

    latest: Dict[Tuple[int, int], Dict[str, object]] = {}
    doc_counts: Dict[Tuple[int, int], int] = {}
    for doc in collection.find(query, projection):
        sim = doc.get("simulator_result") or {}
        param = sim.get("parameter") or {}
        index_type = int(param["cacheindextype"])
        capacity = int(param["size"])
        key = (index_type, capacity)
        doc_counts[key] = doc_counts.get(key, 0) + 1
        if key not in latest or doc.get("timestamp") > latest[key].get("timestamp"):
            latest[key] = doc
    return latest, doc_counts


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def write_details_csv(path: Path, latest, doc_counts, index_types: List[int], capacities: List[int]) -> None:
    fields = [
        "cache_index_type",
        "index_label",
        "capacity",
        "capacity_exp",
        "hitrate_percent",
        "missrate_percent",
        "processed",
        "doc_count",
        "latest_timestamp",
    ]
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for index_type in index_types:
            for capacity in capacities:
                doc = latest.get((index_type, capacity))
                sim = doc.get("simulator_result") if doc else None
                hitrate = float(sim["hitrate"]) * 100.0 if sim and sim.get("hitrate") is not None else None
                writer.writerow(
                    {
                        "cache_index_type": index_type,
                        "index_label": index_label(index_type),
                        "capacity": capacity,
                        "capacity_exp": capacity.bit_length() - 1,
                        "hitrate_percent": fmt_pct(hitrate),
                        "missrate_percent": fmt_pct(100.0 - hitrate if hitrate is not None else None),
                        "processed": sim.get("processed", "") if sim else "",
                        "doc_count": doc_counts.get((index_type, capacity), 0),
                        "latest_timestamp": doc.get("timestamp", "") if doc else "",
                    }
                )


def write_wide_csv(path: Path, latest, index_types: List[int], capacities: List[int]) -> None:
    fields = ["cache_index_type", "index_label"] + [f"2^{capacity.bit_length() - 1}" for capacity in capacities]
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for index_type in index_types:
            row = {"cache_index_type": index_type, "index_label": index_label(index_type)}
            for capacity in capacities:
                doc = latest.get((index_type, capacity))
                sim = doc.get("simulator_result") if doc else None
                hitrate = float(sim["hitrate"]) * 100.0 if sim and sim.get("hitrate") is not None else None
                row[f"2^{capacity.bit_length() - 1}"] = fmt_pct(hitrate)
            writer.writerow(row)


def write_best_csv(path: Path, latest, index_types: List[int], capacities: List[int]) -> None:
    fields = ["capacity", "capacity_exp", "best_cache_index_type", "best_index_label", "best_hitrate_percent"]
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        for capacity in capacities:
            best = None
            for index_type in index_types:
                doc = latest.get((index_type, capacity))
                sim = doc.get("simulator_result") if doc else None
                if not sim or sim.get("hitrate") is None:
                    continue
                hitrate = float(sim["hitrate"]) * 100.0
                if best is None or hitrate > best[1]:
                    best = (index_type, hitrate)
            writer.writerow(
                {
                    "capacity": capacity,
                    "capacity_exp": capacity.bit_length() - 1,
                    "best_cache_index_type": best[0] if best else "",
                    "best_index_label": index_label(best[0]) if best else "",
                    "best_hitrate_percent": fmt_pct(best[1] if best else None),
                }
            )


def write_markdown(path: Path, latest, doc_counts, args: argparse.Namespace, index_types: List[int], capacities: List[int]) -> None:
    headers = ["index", "label"] + [f"2^{capacity.bit_length() - 1}" for capacity in capacities]
    lines = [
        "# UnifiedCache Window Index Results",
        "",
        f"- rule: `{args.rule_file_name}`",
        f"- trace: `{args.trace_file_name}`",
        f"- way: `{args.way}`",
        "- metric: latest document hitrate percent per index/capacity",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for index_type in index_types:
        cells = [str(index_type), f"`{index_label(index_type)}`"]
        for capacity in capacities:
            doc = latest.get((index_type, capacity))
            sim = doc.get("simulator_result") if doc else None
            hitrate = float(sim["hitrate"]) * 100.0 if sim and sim.get("hitrate") is not None else None
            cells.append(fmt_pct(hitrate))
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## Best By Capacity", "", "| capacity | index | label | hitrate |", "| --- | ---: | --- | ---: |"])
    for capacity in capacities:
        best = None
        for index_type in index_types:
            doc = latest.get((index_type, capacity))
            sim = doc.get("simulator_result") if doc else None
            if not sim or sim.get("hitrate") is None:
                continue
            hitrate = float(sim["hitrate"]) * 100.0
            if best is None or hitrate > best[1]:
                best = (index_type, hitrate)
        if best:
            lines.append(
                f"| 2^{capacity.bit_length() - 1} | {best[0]} | `{index_label(best[0])}` | {best[1]:.6f} |"
            )
        else:
            lines.append(f"| 2^{capacity.bit_length() - 1} |  |  |  |")

    duplicates = sorted((key, count) for key, count in doc_counts.items() if count > 1)
    if duplicates:
        lines.extend(["", "## Duplicate Documents", "", "最新timestampのdocumentを採用しています。", ""])
        for (index_type, capacity), count in duplicates:
            lines.append(f"- index={index_type}, capacity=2^{capacity.bit_length() - 1}: {count} docs")

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    index_types = parse_csv_ints(args.cache_index_types)
    capacities = expected_capacities(args.start_exp, args.end_exp)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    collection = client[args.db][args.collection]
    latest, doc_counts = fetch_latest_rows(collection, args, index_types, capacities)

    details_csv = outdir / "unified_window_index_details.csv"
    wide_csv = outdir / "unified_window_index_hitrate_wide.csv"
    best_csv = outdir / "unified_window_index_best_by_capacity.csv"
    markdown = outdir / "unified_window_index_hitrate_table.md"

    write_details_csv(details_csv, latest, doc_counts, index_types, capacities)
    write_wide_csv(wide_csv, latest, index_types, capacities)
    write_best_csv(best_csv, latest, index_types, capacities)
    write_markdown(markdown, latest, doc_counts, args, index_types, capacities)

    missing = [
        (index_type, capacity)
        for index_type in index_types
        for capacity in capacities
        if (index_type, capacity) not in latest
    ]
    print(f"wrote {details_csv}")
    print(f"wrote {wide_csv}")
    print(f"wrote {best_csv}")
    print(f"wrote {markdown}")
    if missing:
        print("missing:")
        for index_type, capacity in missing:
            print(f"  index={index_type} capacity=2^{capacity.bit_length() - 1}")


if __name__ == "__main__":
    main()
