#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["matplotlib>=3.7", "pymongo>=4.6"]
# ///
"""Compare TCP/UDP flow cardinality and per-set locality with UnifiedCache hit rates."""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import struct
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLOW_ROOT = ROOT / "scripts/reports/flow_stats"
DEFAULT_OUTPUT = ROOT / "scripts/reports/nyc_flow_set_locality_20260929"
DATASETS = [
    ("NYC", "equinix-nyc-20190117", "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap", "rrc11.bview.20190117.1600.unique.rule", 10_000_000),
    ("San Jose", "equinix-sanjose-20140320", "equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap", "route-views.isc.rib.20140320.1400.unique.rule", 10_000_000),
    ("Chicago", "equinix-chicago-20140320", "equinix-chicago.dirB.20140320-140100.UTC.anon.pcap", "route-views.chicago.rib.20160628.1400.unique.rule", 6_338_755),
    ("WIDE Sep", "2025-09-27", "2025-09-27.pcap", "rib.20250927.0600.unique.rule", 10_000_000),
    ("WIDE Dec", "2025-12-27", "2025-12-27.pcap", "rib.20251227.0600.unique.rule", 10_000_000),
    ("WIDE Mar", "2026-03-27", "2026-03-27.pcap", "rib.20260327.0600.unique.rule", 10_000_000),
]


def args_parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mongo-uri", default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"))
    p.add_argument("--db", default="db")
    p.add_argument("--collection", default="simulator_results")
    p.add_argument("--capacity", type=int, default=8192)
    p.add_argument("--way", type=int, default=8)
    p.add_argument("--index-type", type=int, default=5)
    p.add_argument("--flow-root", type=Path, default=DEFAULT_FLOW_ROOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return p.parse_args()


def read_flow_stats(path: Path) -> dict[str, int]:
    flows: set[tuple[str, str, str, str, str]] = set()
    destinations: set[str] = set()
    packets = 0
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["protocol_number"]) not in (6, 17):
                continue
            flows.add((row["protocol_number"], row["src_ip"], row["dst_ip"], row["src_port"], row["dst_port"]))
            destinations.add(row["dst_ip"])
            packets += int(row["packets"])
    return {"tcp_udp_packets_in_flow_rows": packets, "unique_5tuple_flows": len(flows), "unique_dst_ips": len(destinations)}


def decode_counter(doc: dict[str, Any], field: str) -> list[list[int]]:
    rows = int(doc.get("unified_stat_rows") or 0)
    blob = doc.get(field)
    if blob is None:
        stat = doc.get("simulator_result", {}).get("statdetail", {})
        key = {"hit_count_list_compressed": "cachelinehitcount", "first_miss_count_compressed": "cachelinefirstmisscount", "second_miss_count_compressed": "cachelinesecondmisscount"}[field]
        value = stat.get(key, [])
        return [[int(x) for x in row] for row in value]
    raw = gzip.decompress(bytes(blob))
    expected = rows * 32 * 4
    if len(raw) != expected:
        raise ValueError(f"{field}: decoded {len(raw)} bytes; expected {expected}")
    values = struct.unpack(f"<{rows * 32}I", raw)
    return [list(values[i * 32 : (i + 1) * 32]) for i in range(rows)]


def gini(values: list[int]) -> float:
    ordered = sorted(max(0, int(x)) for x in values)
    total = sum(ordered)
    n = len(ordered)
    if not n or not total:
        return 0.0
    return 2 * sum((i + 1) * value for i, value in enumerate(ordered)) / (n * total) - (n + 1) / n


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    x = (len(values) - 1) * q
    lo = int(x)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)


def latest_doc(collection, trace: str, rule: str, processed: int, capacity: int, way: int, index_type: int) -> dict[str, Any]:
    query = {
        "simulator_result.type": "UnifiedCache",
        "trace_file_name": trace,
        "rule_file_name": rule,
        "simulator_result.processed": processed,
        "simulator_result.parameter.size": capacity,
        "simulator_result.parameter.way": way,
        "simulator_result.parameter.cacheindextype": index_type,
    }
    projection = {"timestamp": 1, "simulator_result.hitrate": 1, "simulator_result.parameter": 1, "unified_stat_rows": 1, "hit_count_list_compressed": 1, "first_miss_count_compressed": 1, "second_miss_count_compressed": 1, "simulator_result.statdetail": 1}
    candidates = collection.find(query, projection).sort("timestamp", -1)
    for doc in candidates:
        p = doc["simulator_result"].get("parameter", {})
        raw_tags = p.get("cachetaglength", [])
        tags = [tuple(int(part) for part in pair) for pair in raw_tags if isinstance(pair, (list, tuple))]
        if len(tags) not in (1, way) or len(tags) != len(raw_tags) or any(pair != (9, 24) for pair in tags):
            continue
        if p.get("insertionpolicy") != "exclusive":
            continue
        if p.get("indexpolicy", "fixed") != "fixed":
            continue
        if p.get("setextensionpolicy", "off") != "off":
            continue
        if p.get("lengthawaremultiprobe", False) or p.get("skewedassociative", False):
            continue
        return doc
    raise RuntimeError(f"missing fixed comparable result: trace={trace}, capacity={capacity}, way={way}, index={index_type}, processed={processed}")


def main() -> None:
    args = args_parse()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10_000)
    collection = client[args.db][args.collection]
    summary: list[dict[str, Any]] = []
    set_rows: list[dict[str, Any]] = []
    plot_data: list[tuple[str, list[int], list[float]]] = []
    try:
        for label, dir_name, trace, rule, processed in DATASETS:
            flow = read_flow_stats(args.flow_root / dir_name / "flow_lengths.csv")
            doc = latest_doc(collection, trace, rule, processed, args.capacity, args.way, args.index_type)
            hit_rows = decode_counter(doc, "hit_count_list_compressed")
            first_rows = decode_counter(doc, "first_miss_count_compressed")
            second_rows = decode_counter(doc, "second_miss_count_compressed")
            if not hit_rows or len(hit_rows) != len(first_rows) or len(hit_rows) != len(second_rows):
                raise ValueError(f"per-set counter rows do not match for {label}")
            hits = [sum(row) for row in hit_rows]
            first = [sum(row) for row in first_rows]
            second = [sum(row) for row in second_rows]
            probes = [hits[i] + first[i] + second[i] for i in range(len(hits))]
            rates = [hits[i] / probes[i] * 100 if probes[i] else math.nan for i in range(len(hits))]
            active_rates = [x for x in rates if math.isfinite(x)]
            h = sum(hits)
            a = sum(probes)
            top_n = max(1, math.ceil(len(probes) * 0.125))
            active = sum(x > 0 for x in probes)
            s = {
                "trace_label": label,
                "trace_file_name": trace,
                "processed_packets": processed,
                "cache_capacity": args.capacity,
                "way": args.way,
                "sets": len(hits),
                "cache_index_type": args.index_type,
                "hit_rate_percent": float(doc["simulator_result"]["hitrate"]) * 100,
                "unique_5tuple_flows_tcp_udp": flow["unique_5tuple_flows"],
                "flows_per_million_packets": flow["unique_5tuple_flows"] / flow["tcp_udp_packets_in_flow_rows"] * 1_000_000,
                "unique_dst_ips_tcp_udp": flow["unique_dst_ips"],
                "dst_ips_per_million_packets": flow["unique_dst_ips"] / flow["tcp_udp_packets_in_flow_rows"] * 1_000_000,
                "tcp_udp_packets_in_flow_rows": flow["tcp_udp_packets_in_flow_rows"],
                "set_probe_gini": gini(probes),
                "set_hit_gini": gini(hits),
                "active_sets": active,
                "max_set_probe_share_percent": max(probes, default=0) / a * 100 if a else 0,
                "top_12_5pct_set_probe_share_percent": sum(sorted(probes, reverse=True)[:top_n]) / a * 100 if a else 0,
                "probe_hitrate_percent": h / a * 100 if a else 0,
                "local_hitrate_min_percent": min(active_rates, default=0),
                "local_hitrate_p10_percent": percentile(active_rates, 0.10),
                "local_hitrate_median_percent": percentile(active_rates, 0.50),
                "local_hitrate_p90_percent": percentile(active_rates, 0.90),
                "local_hitrate_max_percent": max(active_rates, default=0),
                "local_hitrate_stddev_point": pstdev(active_rates) if len(active_rates) > 1 else 0,
                "timestamp": str(doc.get("timestamp", "")),
            }
            summary.append(s)
            plot_data.append((label, probes, rates))
            for i in range(len(hits)):
                set_rows.append({"trace_label": label, "set_id": i, "set_probes": probes[i], "probe_share_percent": probes[i] / a * 100 if a else 0, "hits": hits[i], "first_misses": first[i], "second_misses": second[i], "local_hitrate_percent": "" if not math.isfinite(rates[i]) else rates[i]})
    finally:
        client.close()

    for path, rows in ((args.output_dir / "trace_summary.csv", summary), (args.output_dir / "set_detail.csv", set_rows)):
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    configure_font()
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.2), sharex=True)
    colors = ["#D1495B", "#00798C", "#30638E", "#EDAE49", "#6A994E", "#8F5DA2"]
    for (label, accesses, rates), color in zip(plot_data, colors):
        set_ids = list(range(len(accesses)))
        axes[0].plot(set_ids, [x / sum(accesses) * 100 for x in accesses], color=color, linewidth=1, label=label)
        axes[1].plot(set_ids, rates, color=color, linewidth=0.9, label=label)
    axes[0].set_ylabel("Set probe share (%)")
    axes[0].set_title("Set probe distribution and per-set probe hit rate: same 8K-entry, 8-way, index-5 cache", loc="left", weight="bold")
    axes[1].set_ylabel("Local hit rate (%)")
    axes[1].set_xlabel("Set index")
    axes[1].set_ylim(0, 100)
    axes[1].legend(ncol=3, frameon=False, loc="lower right")
    for ax in axes:
        ax.grid(True, axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(args.output_dir / "set_locality.png", dpi=190, facecolor="white")
    plt.close(fig)

    write_report(args.output_dir / "REPORT.md", summary, args)
    print(args.output_dir / "REPORT.md")
    print(args.output_dir / "trace_summary.csv")
    print(args.output_dir / "set_detail.csv")
    print(args.output_dir / "set_locality.png")


def configure_font() -> None:
    candidates = ["Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic", "IPAexGothic"]
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.unicode_minus"] = False


def write_report(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    lines = [
        "# Flow count and set-locality comparison",
        "",
        f"- Cache: UnifiedCache, physical capacity {args.capacity:,}, way {args.way}, {args.capacity // args.way:,} sets, index type {args.index_type}; set extension off, exclusive insertion, fixed index, /9–/24 tags.",
        "- Flow statistics count TCP/UDP only, matching the simulator's cacheable packet path; flow identity is directional IPv4 5-tuple.",
        "- Unique destination IP counts are distinct `dst_ip` values across those flows. They are not flow counts.",
        "- Per-set probes = hits + first misses + second-or-later misses. Local probe hit rate = hits / probes.",
        "- One packet can probe multiple cache lines before it hits or misses, so set probes are not a packet-disjoint split. Their concentration and local probe hit rates are distinct from the DB's packet-level hit rate.",
        "- Set probe Gini measures concentration of indexed cacheline lookups across sets; the distribution of local probe hit rates measures uneven set effectiveness.",
        "- `flows / M packets` and `dst IP / M packets` use the TCP/UDP packet total in the flow table as denominator. The cache's processed-packet count is shown separately because the selected/parsed packet streams differ.",
        "",
        "| trace | simulator packets | TCP/UDP packets in flow table | unique 5-tuple flows | flows / M TCP/UDP packets | unique dst IPs | dst IP / M TCP/UDP packets | overall hit rate | active sets | probe Gini | top 12.5% probe share | local probe hitrate median (p10–p90) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['trace_label']} | {r['processed_packets']:,} | {r['tcp_udp_packets_in_flow_rows']:,} | {r['unique_5tuple_flows_tcp_udp']:,} | {r['flows_per_million_packets']:,.0f} | {r['unique_dst_ips_tcp_udp']:,} | {r['dst_ips_per_million_packets']:,.0f} | {r['hit_rate_percent']:.3f}% | {r['active_sets']}/{r['sets']} | {r['set_probe_gini']:.3f} | {r['top_12_5pct_set_probe_share_percent']:.1f}% | {r['local_hitrate_median_percent']:.1f}% ({r['local_hitrate_p10_percent']:.1f}–{r['local_hitrate_p90_percent']:.1f}%) |"
        )
    nyc = next(r for r in rows if r["trace_label"] == "NYC")
    comparators = [r for r in rows if r["trace_label"] != "NYC"]
    mean_dst = fmean(r["unique_dst_ips_tcp_udp"] for r in comparators)
    mean_dst_rate = fmean(r["dst_ips_per_million_packets"] for r in comparators)
    mean_flow_rate = fmean(r["flows_per_million_packets"] for r in comparators)
    mean_gini = fmean(r["set_probe_gini"] for r in comparators)
    mean_hitrate = fmean(r["hit_rate_percent"] for r in comparators)
    lines.extend(
        [
            "",
            "## Reading the evidence",
            "",
            f"- NYC has {nyc['unique_5tuple_flows_tcp_udp']:,} TCP/UDP 5-tuple flows ({nyc['flows_per_million_packets']:,.0f} per million TCP/UDP packets) and {nyc['unique_dst_ips_tcp_udp']:,} unique destination IPs ({nyc['dst_ips_per_million_packets']:,.0f} per million TCP/UDP packets). The five comparators average {mean_flow_rate:,.0f} flows/M and {mean_dst_rate:,.0f} destination IPs/M; WIDE Mar exceeds NYC on both cardinalities while keeping a much higher hit rate.",
            f"- NYC's overall hit rate is {nyc['hit_rate_percent']:.3f}%, versus {mean_hitrate:.3f}% averaged across the five comparators.",
            f"- NYC set-probe Gini is {nyc['set_probe_gini']:.3f}, versus {mean_gini:.3f} across comparators. Its top 12.5% of sets receive {nyc['top_12_5pct_set_probe_share_percent']:.1f}% of probes (12.5% would be uniform), so probes are flatter than in WIDE but still not uniform.",
            f"- NYC has weaker local probe hit rates across the set distribution (median {nyc['local_hitrate_median_percent']:.1f}%, p10–p90 {nyc['local_hitrate_p10_percent']:.1f}–{nyc['local_hitrate_p90_percent']:.1f}%). WIDE Mar's median is {next(r['local_hitrate_median_percent'] for r in rows if r['trace_label'] == 'WIDE Mar'):.1f}% despite more unique destinations, consistent with its much more concentrated probe pattern.",
            f"- The set-weighted probe hit rate is {nyc['probe_hitrate_percent']:.3f}% for NYC; DB packet-level hit rate is {nyc['hit_rate_percent']:.3f}%. These differ because packets can issue several prefix-cache probes.",
            "- This is cross-trace evidence, not a causal test: routing-table snapshots and traffic composition also differ. Use `set_detail.csv` for per-set inspection; `set_locality.png` plots probe share and local probe hit rate.",
            "",
            "## Files",
            "",
            "- `trace_summary.csv`: flow/destination totals, overall hit rate, set concentration, local-hit-rate spread, result timestamp.",
            "- `set_detail.csv`: cacheline probes, probe share, hits, misses, and local probe hit rate for every set.",
            "- `set_locality.png`: set probe-share and local probe-hit-rate overlays.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
