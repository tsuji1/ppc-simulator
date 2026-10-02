#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Append NYC 64K..128K VIL and fixed-MP measurements to the plotting CSV."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from plot_global_xor_anon_vil_mp_bars import (
    VIL_INDEXES,
    VIL_LABELS,
    base_query,
    configure_cacti_env,
    doc_matches_config,
    latest_doc,
    mp_config,
    row_for_doc,
    run_cacti,
    timing_adjusted_metrics,
    vil_config,
)


SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR / "reports/nyc-mp-optimal/capacity_results.csv"
OUTPUT = SCRIPT_DIR / "reports/nyc-mp-optimal/capacity_results_128k.csv"
MISSING = SCRIPT_DIR / "reports/nyc-mp-optimal/missing_128k.csv"
TRACE = "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap"
RULE = "rrc11.bview.20190117.1600.unique.rule"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.getenv("DATABASE_URL", "mongodb://localhost:27017"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--cacti-collection", default="cacti_results")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--dram-pj-per-burst", type=float, default=4000)
    parser.add_argument("--cpu-frequency-ghz", type=float, default=2.0)
    parser.add_argument("--write-back-cacti", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def specs() -> list[tuple[str, str, int | None, int, int, Any]]:
    result = []
    for index in VIL_INDEXES:
        for capacity in (65536, 98304, 131072):
            result.append(("VIL", VIL_LABELS[index], index, capacity, capacity, vil_config(index, capacity)))
    for bank in (32768, 49152, 65536):
        result.append(("MP2", "MP 2-cache（/24, /18）", None, bank, bank * 2, mp_config(2, bank)))
    for bank in (21840, 32768, 43688):
        result.append(("MP3", "MP 3-cache（/24, /21, /18）", None, bank, bank * 3, mp_config(3, bank)))
    return result


def main() -> int:
    args = arguments()
    configure_cacti_env(args)
    base_rows = read_csv(BASE)
    extended_keys = {
        (architecture, series, str(bank))
        for architecture, series, _index, bank, _total, _config in specs()
    }
    rows = [
        row for row in base_rows
        if not (
            row["condition"] == "original"
            and row["trace"] == "NYC"
            and (row["architecture"], row["series"], row["bank_capacity"]) in extended_keys
        )
    ]
    missing: list[dict[str, str]] = []
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        collection = client[args.db][args.collection]
        for architecture, series, index, bank, total, config in specs():
            docs = [
                doc for doc in collection.find(base_query(config, TRACE, RULE, args.processed))
                if doc_matches_config(doc, config)
            ]
            doc = latest_doc(docs)
            if doc is None:
                missing.append({"architecture": architecture, "series": series, "bank_capacity": str(bank)})
                continue
            old_row, updates = row_for_doc(doc, run_cacti, args)
            cacti_results = updates.get("cacti_results") or doc.get("cacti_results")
            metrics = timing_adjusted_metrics(doc, old_row, cacti_results, args)
            if args.write_back_cacti and updates:
                collection.update_one({"_id": doc["_id"]}, {"$set": updates})
            sim = doc["simulator_result"]
            hitrate = float(sim.get("hitrate", 0) or 0) * 100
            rows.append({
                "condition_index": 0,
                "condition": "original",
                "condition_label": "元匿名トレース",
                "trace_index": 2,
                "trace": "NYC",
                "trace_file_name": TRACE,
                "rule_file_name": RULE,
                "architecture": architecture,
                "series": series,
                "index": "" if index is None else index,
                "bank_capacity": bank,
                "total_capacity": total,
                "processed": int(sim.get("processed", 0) or 0),
                "hitrate_percent": hitrate,
                "miss_rate_percent": 100 - hitrate,
                **metrics,
                "source_id": str(doc["_id"]),
            })
    finally:
        client.close()

    rows.sort(key=lambda row: (
        int(row["condition_index"]), int(row["trace_index"]), row["architecture"],
        row["series"], int(row["bank_capacity"]),
    ))
    fields = list(base_rows[0])
    with OUTPUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with MISSING.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["architecture", "series", "bank_capacity"])
        writer.writeheader()
        writer.writerows(missing)
    print(f"rows={len(rows)} extended={len(specs()) - len(missing)} missing={len(missing)} output={OUTPUT}")
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
