#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "pymongo>=4.6",
# ]
# ///
"""Diagnose the low NYC hit rate for the fixed 9-layer Multi-Prefix cache."""

from __future__ import annotations

import argparse
import csv
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient


DEFAULT_REFBITS = [24, 23, 22, 21, 20, 19, 18, 17, 16]
DEFAULT_NYC_TRACE = "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap"
DEFAULT_NYC_RULE = "rrc11.bview.20190117.1600.unique.rule"

FLOW_SUMMARY_BY_TRACE = {
    "2025-09-27.pcap": "scripts/reports/flow_stats_wide_same_date_no_icmp/2025-09-27-nonanon/flow_summary_no_icmp.csv",
    "2025-12-27.pcap": "scripts/reports/flow_stats_wide_same_date_no_icmp/2025-12-27-nonanon/flow_summary_no_icmp.csv",
    "2026-03-27.pcap": "scripts/reports/flow_stats_wide_same_date_no_icmp/2026-03-27-nonanon/flow_summary_no_icmp.csv",
    "202509271400.pcap": "scripts/reports/flow_stats_wide_same_date_no_icmp/2025-09-27-anon/flow_summary_no_icmp.csv",
    "202512271400.pcap": "scripts/reports/flow_stats_wide_same_date_no_icmp/2025-12-27-anon/flow_summary_no_icmp.csv",
    "202603271400.pcap": "scripts/reports/flow_stats_wide_same_date_no_icmp/2026-03-27-anon/flow_summary_no_icmp.csv",
    "equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap": "scripts/reports/flow_stats_no_icmp/equinix-sanjose-20140320/flow_summary_no_icmp.csv",
    "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap": "scripts/reports/flow_stats_no_icmp/equinix-nyc-20190117/flow_summary_no_icmp.csv",
    "jpix2sinet90s_5tuple.txt": "scripts/reports/flow_stats_no_icmp/jpix2sinet-20180502/flow_summary_no_icmp.csv",
}

FLOW_METRICS = [
    "included_packets",
    "included_flow_count",
    "packets_per_flow",
    "one_packet_flow_ratio",
    "top100_packet_share",
    "ge1024_packet_share",
    "ge8192_packet_share",
    "max_packets_per_flow",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze fixed MP9 hitrate and layer stats, focused on NYC."
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"),
        help="MongoDB URI",
    )
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--processed", type=int, default=10_000_000)
    parser.add_argument("--layer-size", type=int, default=1024)
    parser.add_argument("--way", type=int, default=8)
    parser.add_argument(
        "--refbits",
        default=",".join(str(x) for x in DEFAULT_REFBITS),
        help="Comma-separated MP layer refbits, in layer order",
    )
    parser.add_argument("--nyc-trace", default=DEFAULT_NYC_TRACE)
    parser.add_argument("--nyc-rule", default=DEFAULT_NYC_RULE)
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/nyc_mp9_hitrate_diagnosis",
        help="Output directory",
    )
    return parser.parse_args()


def parse_refbits(raw: str) -> list[int]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if not values:
        raise SystemExit("--refbits must not be empty")
    return values


def layer_signature(doc: dict[str, Any]) -> tuple[tuple[int, int, int], ...]:
    layers = (
        doc.get("simulator_result", {})
        .get("parameter", {})
        .get("cachelayers", [])
    )
    return tuple(
        (int(layer.get("size", -1)), int(layer.get("way", -1)), int(layer.get("refbits", -1)))
        for layer in layers
    )


def matches_fixed_mp9(
    doc: dict[str, Any],
    refbits: list[int],
    layer_size: int,
    way: int,
) -> bool:
    expected = tuple((layer_size, way, refbit) for refbit in refbits)
    return layer_signature(doc) == expected


def latest_fixed_docs(collection: Any, args: argparse.Namespace, refbits: list[int]) -> OrderedDict[tuple[str, str], dict[str, Any]]:
    query = {
        "simulator_result.type": "MultiLayerCacheExclusive",
        "simulator_result.processed": args.processed,
    }
    projection = {
        "_id": 0,
        "timestamp": 1,
        "trace_file_name": 1,
        "rule_file_name": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.hit": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter.cachelayers": 1,
        "simulator_result.statdetail.refered": 1,
        "simulator_result.statdetail.hit": 1,
        "simulator_result.statdetail.inserted": 1,
        "simulator_result.statdetail.replaced": 1,
        "simulator_result.statdetail.longestmatchmap": 1,
        "simulator_result.statdetail.matchmap": 1,
    }

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for doc in collection.find(query, projection):
        if not matches_fixed_mp9(doc, refbits, args.layer_size, args.way):
            continue
        key = (doc.get("trace_file_name", ""), doc.get("rule_file_name", ""))
        previous = latest.get(key)
        if previous is None or doc.get("timestamp") > previous.get("timestamp"):
            latest[key] = doc

    return OrderedDict(
        sorted(latest.items(), key=lambda item: item[1]["simulator_result"]["hitrate"])
    )


def numeric_list(value: Any) -> list[int]:
    if value is None:
        return []
    return [int(x) for x in value]


def percent(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator * 100.0


def cross_trace_rows(
    docs: OrderedDict[tuple[str, str], dict[str, Any]],
    refbits: list[int],
) -> list[dict[str, Any]]:
    rows = []
    for (trace, rule), doc in docs.items():
        sim = doc["simulator_result"]
        stat = sim.get("statdetail", {})
        hits = numeric_list(stat.get("hit"))
        inserted = numeric_list(stat.get("inserted"))
        replaced = numeric_list(stat.get("replaced"))
        processed = int(sim["processed"])
        hit = int(sim["hit"])
        misses = processed - hit
        total_inserted = sum(inserted)
        total_replaced = sum(replaced)
        max_insert_index = max(range(len(inserted)), key=lambda i: inserted[i]) if inserted else -1
        max_replace_index = max(range(len(replaced)), key=lambda i: replaced[i]) if replaced else -1
        last_idx = len(refbits) - 1
        last_hit = hits[last_idx] if len(hits) > last_idx else 0
        last_inserted = inserted[last_idx] if len(inserted) > last_idx else 0
        last_replaced = replaced[last_idx] if len(replaced) > last_idx else 0
        rows.append(
            {
                "trace_file_name": trace,
                "rule_file_name": rule,
                "hitrate_percent": sim["hitrate"] * 100.0,
                "processed": processed,
                "hit": hit,
                "misses": misses,
                "last_layer_refbits": refbits[last_idx],
                "last_layer_hits": last_hit,
                "last_layer_hit_share_percent": percent(last_hit, hit),
                "last_layer_inserted": last_inserted,
                "last_layer_replaced": last_replaced,
                "total_inserted": total_inserted,
                "total_replaced": total_replaced,
                "max_inserted_layer": refbits[max_insert_index] if max_insert_index >= 0 else "",
                "max_inserted_count": inserted[max_insert_index] if max_insert_index >= 0 else "",
                "max_replaced_layer": refbits[max_replace_index] if max_replace_index >= 0 else "",
                "max_replaced_count": replaced[max_replace_index] if max_replace_index >= 0 else "",
                "timestamp": doc.get("timestamp", ""),
            }
        )
    return rows


def layer_rows(doc: dict[str, Any], refbits: list[int]) -> list[dict[str, Any]]:
    sim = doc["simulator_result"]
    stat = sim.get("statdetail", {})
    processed = int(sim["processed"])
    refered = numeric_list(stat.get("refered"))
    hits = numeric_list(stat.get("hit"))
    inserted = numeric_list(stat.get("inserted"))
    replaced = numeric_list(stat.get("replaced"))
    cumulative_hit = 0
    rows = []
    for idx, refbit in enumerate(refbits):
        layer_refered = refered[idx] if idx < len(refered) else 0
        layer_hits = hits[idx] if idx < len(hits) else 0
        layer_inserted = inserted[idx] if idx < len(inserted) else 0
        layer_replaced = replaced[idx] if idx < len(replaced) else 0
        cumulative_hit += layer_hits
        rows.append(
            {
                "layer_index": idx,
                "refbits": refbit,
                "refered": layer_refered,
                "hits": layer_hits,
                "conditional_hitrate_percent": percent(layer_hits, layer_refered),
                "cumulative_hitrate_percent": percent(cumulative_hit, processed),
                "remaining_misses_after_layer": layer_refered - layer_hits,
                "inserted": layer_inserted,
                "replaced": layer_replaced,
                "replacement_per_insert_percent": percent(layer_replaced, layer_inserted),
                "hit_share_percent": percent(layer_hits, int(sim["hit"])),
            }
        )
    return rows


def lpm_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    sim = doc["simulator_result"]
    misses = int(sim["processed"]) - int(sim["hit"])
    longest = numeric_list(sim.get("statdetail", {}).get("longestmatchmap"))
    rows = []
    for prefix_len, count in enumerate(longest):
        if count == 0:
            continue
        rows.append(
            {
                "miss_longest_prefix_len": prefix_len,
                "misses": count,
                "miss_share_percent": percent(count, misses),
            }
        )
    return rows


def signature_label(signature: list[tuple[int, int, int]]) -> str:
    return ", ".join(f"/{refbits}:{size}" for size, _way, refbits in signature)


def selected_nyc_config_rows(
    collection: Any,
    args: argparse.Namespace,
    refbits: list[int],
) -> list[dict[str, Any]]:
    selected = [
        (
            "3cache 2048 each /24,/20,/16",
            [(2048, args.way, 24), (2048, args.way, 20), (2048, args.way, 16)],
        ),
        (
            "4cache 2048 each /24,/21,/18,/16",
            [(2048, args.way, 24), (2048, args.way, 21), (2048, args.way, 18), (2048, args.way, 16)],
        ),
        (
            "9cache 1024 each /24../16",
            [(args.layer_size, args.way, refbit) for refbit in refbits],
        ),
        (
            "2cache /24 1024 + /16 1024",
            [(1024, args.way, 24), (1024, args.way, 16)],
        ),
        (
            "2cache /24 1024 + /16 32768",
            [(1024, args.way, 24), (32768, args.way, 16)],
        ),
        (
            "2cache /24 32768 + /16 32768",
            [(32768, args.way, 24), (32768, args.way, 16)],
        ),
    ]
    by_signature = {tuple(signature): (label, signature) for label, signature in selected}
    latest: dict[tuple[tuple[int, int, int], ...], dict[str, Any]] = {}

    query = {
        "trace_file_name": args.nyc_trace,
        "rule_file_name": args.nyc_rule,
        "simulator_result.type": "MultiLayerCacheExclusive",
        "simulator_result.processed": args.processed,
    }
    projection = {
        "_id": 0,
        "timestamp": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.hit": 1,
        "simulator_result.processed": 1,
        "simulator_result.parameter.cachelayers": 1,
        "simulator_result.statdetail.hit": 1,
        "simulator_result.statdetail.inserted": 1,
        "simulator_result.statdetail.replaced": 1,
    }
    for doc in collection.find(query, projection):
        signature = layer_signature(doc)
        if signature not in by_signature:
            continue
        if signature not in latest or doc.get("timestamp") > latest[signature].get("timestamp"):
            latest[signature] = doc

    rows = []
    for signature, (label, signature_list) in by_signature.items():
        doc = latest.get(signature)
        if not doc:
            rows.append(
                {
                    "config": label,
                    "signature": signature_label(signature_list),
                    "found": False,
                    "hitrate_percent": "",
                    "misses": "",
                    "hits_by_layer": "",
                    "inserted_by_layer": "",
                    "replaced_by_layer": "",
                    "timestamp": "",
                }
            )
            continue
        sim = doc["simulator_result"]
        stat = sim.get("statdetail", {})
        rows.append(
            {
                "config": label,
                "signature": signature_label(signature_list),
                "found": True,
                "hitrate_percent": sim["hitrate"] * 100.0,
                "misses": int(sim["processed"]) - int(sim["hit"]),
                "hits_by_layer": ";".join(str(x) for x in numeric_list(stat.get("hit"))),
                "inserted_by_layer": ";".join(str(x) for x in numeric_list(stat.get("inserted"))),
                "replaced_by_layer": ";".join(str(x) for x in numeric_list(stat.get("replaced"))),
                "timestamp": doc.get("timestamp", ""),
            }
        )
    return rows


def read_metric_csv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    metrics: dict[str, str] = {}
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != ["metric", "value"]:
            return {}
        for row in reader:
            if len(row) >= 2:
                metrics[row[0]] = row[1]
    return metrics


def attach_flow_metrics(repo_root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joined = []
    for row in rows:
        trace = row["trace_file_name"]
        summary_path = FLOW_SUMMARY_BY_TRACE.get(trace)
        metrics = read_metric_csv(repo_root / summary_path) if summary_path else {}
        out = dict(row)
        for metric in FLOW_METRICS:
            out[metric] = metrics.get(metric, "")
        joined.append(out)
    return joined


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def fmt_int(value: Any) -> str:
    if value == "":
        return ""
    return f"{int(value):,}"


def fmt_pct(value: Any, digits: int = 3) -> str:
    if value == "":
        return ""
    return f"{float(value):.{digits}f}%"


def top_rows_by_count(rows: list[dict[str, Any]], count_key: str, limit: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: int(row[count_key]), reverse=True)[:limit]


def write_report(
    path: Path,
    args: argparse.Namespace,
    refbits: list[int],
    cross_rows: list[dict[str, Any]],
    flow_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    nyc_layers: list[dict[str, Any]],
    nyc_lpm_rows: list[dict[str, Any]],
    nyc_doc: dict[str, Any],
) -> None:
    sim = nyc_doc["simulator_result"]
    nyc_misses = int(sim["processed"]) - int(sim["hit"])
    latest_generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# NYC MP9 hitrate diagnosis",
        "",
        f"- generated_at_utc: `{latest_generated}`",
        f"- cache: `MultiLayerCacheExclusive`, refbits `{','.join(str(x) for x in refbits)}`, layer size `{args.layer_size}`, way `{args.way}`",
        f"- processed filter: `{args.processed:,}` packets",
        f"- NYC trace: `{args.nyc_trace}`",
        f"- NYC rule: `{args.nyc_rule}`",
        "",
        "## Main finding",
        "",
        (
            f"NYC is the outlier for this fixed MP9 config: hitrate is "
            f"`{sim['hitrate'] * 100.0:.4f}%`, leaving `{nyc_misses:,}` misses. "
            "The loss is concentrated at the coarse end: the final `/16` layer receives "
            f"`{nyc_layers[-1]['inserted']:,}` inserts and `{nyc_layers[-1]['replaced']:,}` replacements."
        ),
        "",
        "## Cross-trace MP9 results",
        "",
        "| trace | hitrate | misses | /16 hits | /16 inserted | /16 replaced | top100 share | 8192+ share |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in flow_rows:
        lines.append(
            "| {trace} | {hitrate} | {misses} | {l16_hits} | {l16_inserted} | {l16_replaced} | {top100} | {ge8192} |".format(
                trace=row["trace_file_name"],
                hitrate=fmt_pct(row["hitrate_percent"], 4),
                misses=fmt_int(row["misses"]),
                l16_hits=fmt_int(row["last_layer_hits"]),
                l16_inserted=fmt_int(row["last_layer_inserted"]),
                l16_replaced=fmt_int(row["last_layer_replaced"]),
                top100=fmt_pct(float(row["top100_packet_share"]) * 100.0, 2) if row["top100_packet_share"] != "" else "",
                ge8192=fmt_pct(float(row["ge8192_packet_share"]) * 100.0, 2) if row["ge8192_packet_share"] != "" else "",
            )
        )

    lines.extend(
        [
            "",
            "## NYC layer breakdown",
            "",
            "| layer | referenced | hits | conditional hitrate | cumulative hitrate | remaining misses | inserted | replaced |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in nyc_layers:
        lines.append(
            "| /{refbits} | {refered} | {hits} | {cond} | {cum} | {remaining} | {inserted} | {replaced} |".format(
                refbits=row["refbits"],
                refered=fmt_int(row["refered"]),
                hits=fmt_int(row["hits"]),
                cond=fmt_pct(row["conditional_hitrate_percent"], 2),
                cum=fmt_pct(row["cumulative_hitrate_percent"], 2),
                remaining=fmt_int(row["remaining_misses_after_layer"]),
                inserted=fmt_int(row["inserted"]),
                replaced=fmt_int(row["replaced"]),
            )
        )

    lines.extend(
        [
            "",
            "## NYC miss longest-prefix distribution",
            "",
            "This is the routing-table longest-match prefix length for packets that still missed after all MP9 layers.",
            "",
            "| prefix length | misses | miss share |",
            "| ---: | ---: | ---: |",
        ]
    )
    for row in top_rows_by_count(nyc_lpm_rows, "misses", limit=12):
        lines.append(
            "| /{prefix_len} | {misses} | {share} |".format(
                prefix_len=row["miss_longest_prefix_len"],
                misses=fmt_int(row["misses"]),
                share=fmt_pct(row["miss_share_percent"], 2),
            )
        )

    lines.extend(
        [
            "",
            "## Selected NYC MP configs",
            "",
            "| config | hitrate | misses | signature | inserted by layer | replaced by layer |",
            "| --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in selected_rows:
        lines.append(
            "| {config} | {hitrate} | {misses} | `{signature}` | `{inserted}` | `{replaced}` |".format(
                config=row["config"],
                hitrate=fmt_pct(row["hitrate_percent"], 4) if row["found"] else "",
                misses=fmt_int(row["misses"]) if row["found"] else "",
                signature=row["signature"],
                inserted=row["inserted_by_layer"],
                replaced=row["replaced_by_layer"],
            )
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- NYC has far weaker large-flow concentration than the high-hitrate traces in the available no-ICMP flow summaries. Its full 10M trace top100 packet share is about 5.49%, and 8192+ flow packet share is about 0.95%; WIDE traces are around 40-45% top100 and 39-43% for 8192+.",
            "- The MP9 cache is not failing in one of the fine layers first. It keeps passing traffic down until `/16`, where most hits occur, but `/16` also churns heavily because many distinct `/16` destinations compete for only 1024 entries.",
            "- Splitting capacity across nine 1024-entry layers is not automatically better for NYC. The selected-config table shows that moving capacity into the coarse `/16` layer sharply reduces `/16` replacements and raises hitrate.",
            "- The final misses are not just very-specific prefixes. The largest miss buckets are `/0`, `/16`, `/12`, `/14`, and `/13`, which means many misses land in coarse or default-routed regions where this fixed layer plan does not provide enough stable locality.",
            "",
            "## Output files",
            "",
            "- `mp9_cross_trace.csv`",
            "- `mp9_cross_trace_with_flow.csv`",
            "- `nyc_selected_mp_configs.csv`",
            "- `nyc_layer_breakdown.csv`",
            "- `nyc_miss_lpm_distribution.csv`",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    args = parse_args()
    refbits = parse_refbits(args.refbits)
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = repo_root / args.output_dir

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    collection = client[args.db][args.collection]

    docs = latest_fixed_docs(collection, args, refbits)
    if not docs:
        raise SystemExit("no fixed MP9 documents found")

    nyc_key = (args.nyc_trace, args.nyc_rule)
    nyc_doc = docs.get(nyc_key)
    if nyc_doc is None:
        available = "\n".join(f"- {trace} / {rule}" for trace, rule in docs.keys())
        raise SystemExit(f"NYC document not found for {nyc_key}. Available:\n{available}")

    cross = cross_trace_rows(docs, refbits)
    cross_with_flow = attach_flow_metrics(repo_root, cross)
    selected_rows = selected_nyc_config_rows(collection, args, refbits)
    nyc_layers = layer_rows(nyc_doc, refbits)
    nyc_lpm = lpm_rows(nyc_doc)

    write_csv(output_dir / "mp9_cross_trace.csv", cross)
    write_csv(output_dir / "mp9_cross_trace_with_flow.csv", cross_with_flow)
    write_csv(output_dir / "nyc_selected_mp_configs.csv", selected_rows)
    write_csv(output_dir / "nyc_layer_breakdown.csv", nyc_layers)
    write_csv(output_dir / "nyc_miss_lpm_distribution.csv", nyc_lpm)
    write_report(
        output_dir / "REPORT.md",
        args,
        refbits,
        cross,
        cross_with_flow,
        selected_rows,
        nyc_layers,
        nyc_lpm,
        nyc_doc,
    )

    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
