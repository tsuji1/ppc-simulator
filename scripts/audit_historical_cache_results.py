# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymongo>=4.6",
# ]
# ///
"""Audit every MongoDB database/collection for historical cache results."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from collections.abc import Iterator
from typing import Any

from pymongo import MongoClient


TARGET_RATES = (88.60, 72.23, 76.34, 88.89)
RATE_KEYS = {"hitrate", "hit_rate", "hit-rate"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search all accessible MongoDB databases and collections for hit rates "
            "and all-/24 UnifiedCache configurations."
        )
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI (default: DATABASE_URL or mongodb://localhost:27017/)",
    )
    parser.add_argument("--tolerance", type=float, default=0.15, help="Hit-rate tolerance in percentage points")
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--output", default="", help="Optional JSON output path")
    return parser.parse_args()


def walk(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, child
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def rate_percent(path: str, value: Any) -> float | None:
    key = path.rsplit(".", 1)[-1].lower().replace(" ", "_")
    if key not in RATE_KEYS or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number * 100.0 if 0.0 <= number <= 1.0 else number


def find_first(doc: dict[str, Any], suffixes: tuple[str, ...]) -> Any:
    normalized = tuple(s.lower() for s in suffixes)
    for path, value in walk(doc):
        if path.lower().endswith(normalized):
            return value
    return None


def is_all_slash24(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if value == [24, 24]:
        return True
    return all(isinstance(item, list) and item == [24, 24] for item in value)


def summarize(doc: dict[str, Any]) -> dict[str, Any]:
    rates = []
    for path, value in walk(doc):
        percent = rate_percent(path, value)
        if percent is not None:
            rates.append({"path": path, "percent": percent})
    tag_length = find_first(doc, ("cachetaglength", "cache_tag_length"))
    return {
        "id": str(doc.get("_id", "")),
        "trace": find_first(doc, ("trace_file_name", "tracefilename", "trace")),
        "rule": find_first(doc, ("rule_file_name", "rulefilename", "rule")),
        "type": find_first(doc, ("simulator_result.type", "type")),
        "size": find_first(doc, ("parameter.size", "cache.size", "size")),
        "way": find_first(doc, ("parameter.way", "cache.way", "way")),
        "refbits": find_first(doc, ("parameter.refbits", "cache.refbits", "refbits")),
        "index_type": find_first(doc, ("cacheindextype", "cache_index_type")),
        "tag_length": tag_length,
        "all_slash24": is_all_slash24(tag_length),
        "processed": find_first(doc, ("simulator_result.processed", "processed")),
        "rates": rates,
    }


def main() -> int:
    args = parse_args()
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=args.timeout_ms)
    client.admin.command("ping")

    inventory: list[dict[str, Any]] = []
    rate_matches: list[dict[str, Any]] = []
    all_slash24_matches: list[dict[str, Any]] = []
    unified_way4_legacy_index_candidates: list[dict[str, Any]] = []
    exclusive_slash24_candidates: list[dict[str, Any]] = []
    trace_counts: Counter[str] = Counter()

    for db_name in client.list_database_names():
        if db_name in {"admin", "config", "local"}:
            continue
        database = client[db_name]
        for collection_name in database.list_collection_names():
            collection = database[collection_name]
            count = collection.estimated_document_count()
            inventory.append({"database": db_name, "collection": collection_name, "documents": count})
            if count == 0:
                continue

            for doc in collection.find({}):
                summary = summarize(doc)
                location = {"database": db_name, "collection": collection_name, **summary}
                if summary["trace"]:
                    trace_counts[str(summary["trace"])] += 1
                if summary["all_slash24"]:
                    all_slash24_matches.append(location)
                if (
                    summary["type"] == "UnifiedCache"
                    and summary["way"] == 4
                    and summary["index_type"] in {0, 1, 3}
                ):
                    unified_way4_legacy_index_candidates.append(location)
                if (
                    summary["type"] == "MultiLayerCacheExclusive"
                    and summary["size"] == 1024
                    and summary["way"] == 4
                    and summary["refbits"] == 24
                ):
                    exclusive_slash24_candidates.append(location)
                matched_targets = []
                for rate in summary["rates"]:
                    for target in TARGET_RATES:
                        if abs(rate["percent"] - target) <= args.tolerance:
                            matched_targets.append(
                                {"target": target, "path": rate["path"], "percent": rate["percent"]}
                            )
                if matched_targets:
                    location["matched_targets"] = matched_targets
                    rate_matches.append(location)

    result = {
        "inventory": inventory,
        "target_rates_percent": TARGET_RATES,
        "tolerance_percentage_points": args.tolerance,
        "rate_matches": rate_matches,
        "all_slash24_matches": all_slash24_matches,
        "unified_way4_legacy_index_candidates": unified_way4_legacy_index_candidates,
        "exclusive_slash24_candidates": exclusive_slash24_candidates,
        "trace_counts": dict(sorted(trace_counts.items())),
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(encoded + "\n")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
