#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["matplotlib>=3.7", "pymongo>=4.6"]
# ///
"""Compare NYC and WIDE Mar per-set miss rates against unique routed/cache prefixes."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
import gzip
import ipaddress
import math
import os
import struct
from array import array
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any
import zlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pymongo import MongoClient


ROOT = Path(__file__).resolve().parents[1]
FLOW_ROOT = ROOT / "scripts/reports/flow_stats"
OUTPUT = ROOT / "scripts/reports/nyc_wide_mar_set_prefix_miss_20260929"
SET_COUNT = 1024
WAY = 8
CAPACITY = SET_COUNT * WAY
INDEX_TYPE = 5  # CRC32 over destination /18, modulo 1024.
DATASETS = (
    {
        "label": "NYC",
        "trace_dir": "equinix-nyc-20190117",
        "trace": "equinix-nyc.dirB.20190117-135900.UTC.anon.pcap",
        "rule": "/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule",
        "processed": 10_000_000,
    },
    {
        "label": "WIDE Mar",
        "trace_dir": "2026-03-27",
        "trace": "2026-03-27.pcap",
        "rule": "/home/yuzugon/rules/rib.20260327.0600.unique.rule",
        "processed": 10_000_000,
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongo-uri", default=os.environ.get("DATABASE_URL", "mongodb://localhost:27017/"))
    parser.add_argument("--db", default="db")
    parser.add_argument("--collection", default="simulator_results")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    return parser.parse_args()


def ip_int(value: str) -> int:
    return int(ipaddress.IPv4Address(value))


def read_flow_destinations(path: Path) -> dict[int, int]:
    packets_by_dst: dict[int, int] = defaultdict(int)
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["protocol_number"]) in (6, 17):
                packets_by_dst[ip_int(row["dst_ip"])] += int(row["packets"])
    return packets_by_dst


def read_rules(path: Path) -> tuple[list[set[int]], array, bytearray, bytearray]:
    prefixes = [set() for _ in range(33)]
    routes: list[tuple[int, int]] = []
    with path.open() as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 2:
                continue
            length = int(fields[1])
            value = ip_int(fields[0])
            mask = 0 if length == 0 else ((0xFFFFFFFF << (32 - length)) & 0xFFFFFFFF)
            network = value & mask
            prefixes[length].add(network)
            routes.append((network, length))
    routes = sorted(set(routes))
    starts = array("I", (network for network, _ in routes))
    lengths = bytearray(length for _, length in routes)
    # Iterative range-maximum tree over route lengths sorted by network start.
    tree = bytearray(2 * len(lengths))
    for i, length in enumerate(lengths):
        tree[len(lengths) + i] = length
    for i in range(len(lengths) - 1, 0, -1):
        tree[i] = max(tree[i * 2], tree[i * 2 + 1])
    return prefixes, starts, lengths, tree


def lpm_prefix(prefixes: list[set[int]], dst: int) -> tuple[int, int]:
    for length in range(32, -1, -1):
        mask = 0 if length == 0 else ((0xFFFFFFFF << (32 - length)) & 0xFFFFFFFF)
        network = dst & mask
        if network in prefixes[length]:
            return network, length
    return 0, 0


def max_route_length(tree: bytearray, size: int, left: int, right: int) -> int:
    result = 0
    left += size
    right += size
    while left < right:
        if left & 1:
            result = max(result, tree[left])
            left += 1
        if right & 1:
            right -= 1
            result = max(result, tree[right])
        left //= 2
        right //= 2
    return result


def leaf_index(dst: int, starts: array, lengths: bytearray, tree: bytearray) -> int:
    """Match RoutingTable.IsLeaf: first prefix length with no descendant route."""
    size = len(lengths)
    low, high = 0, 32
    while low < high:
        length = (low + high) // 2
        mask = 0 if length == 0 else ((0xFFFFFFFF << (32 - length)) & 0xFFFFFFFF)
        network = dst & mask
        end = network + (1 << (32 - length)) if length else 1 << 32
        left = bisect_left(starts, network)
        right = bisect_left(starts, end)
        has_descendant = max_route_length(tree, size, left, right) > length
        if has_descendant:
            low = length + 1
        else:
            high = length
    return low


def set_index(dst: int) -> int:
    dst18 = dst >> 14
    return (zlib.crc32(struct.pack(">I", dst18)) & 0xFFFFFFFF) % SET_COUNT


def unique_prefix_stats(
    destinations: dict[int, int], prefixes: list[set[int]], starts: array, lengths: bytearray, tree: bytearray
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    lpm_keys = [set() for _ in range(SET_COUNT)]
    effective_prefixes = [set() for _ in range(SET_COUNT)]
    cache_keys = [set() for _ in range(SET_COUNT)]
    packets = [0] * SET_COUNT
    cacheable_packets = [0] * SET_COUNT
    noncacheable_leaf_packets: dict[int, int] = defaultdict(int)
    for dst, count in destinations.items():
        set_id = set_index(dst)
        packets[set_id] += count
        network, length = lpm_prefix(prefixes, dst)
        lpm_keys[set_id].add((network, length))
        effective_length = leaf_index(dst, starts, lengths, tree)
        effective_network = dst >> (32 - effective_length) if effective_length else 0
        effective_prefixes[set_id].add((effective_network, effective_length))
        if effective_length < 9:
            cache_length = 9
        elif effective_length <= 24:
            cache_length = effective_length
        else:
            cache_length = 0  # Exclusive /9..../24 rejects leaves beyond /24.
        if cache_length:
            cache_network = dst >> (32 - cache_length)
            cache_keys[set_id].add((cache_network, cache_length))
            cacheable_packets[set_id] += count
        else:
            noncacheable_leaf_packets[effective_length] += count
    rows = [
        {
            "set_id": i,
            "tcp_udp_packets": packets[i],
            "cacheable_prefix_packets": cacheable_packets[i],
            "unique_lpm_prefixes": len(lpm_keys[i]),
            "unique_effective_prefixes": len(effective_prefixes[i]),
            "unique_cache_keys": len(cache_keys[i]),
        }
        for i in range(SET_COUNT)
    ]
    totals = {
        "tcp_udp_packets": sum(packets),
        "cacheable_prefix_packets": sum(cacheable_packets),
        "unique_lpm_prefixes_across_trace": len(set().union(*lpm_keys)),
        "unique_lpm_prefix_set_pairs": sum(len(x) for x in lpm_keys),
        "unique_effective_prefixes_across_trace": len(set().union(*effective_prefixes)),
        "unique_effective_prefix_set_pairs": sum(len(x) for x in effective_prefixes),
        "unique_cache_keys_across_trace": len(set().union(*cache_keys)),
        "unique_cache_key_set_pairs": sum(len(x) for x in cache_keys),
        "packets_with_leaf_outside_cache_range": sum(noncacheable_leaf_packets.values()),
        "unique_destinations": len(destinations),
    }
    return rows, totals


def decode_rows(doc: dict[str, Any], field: str) -> list[list[int]]:
    rows = int(doc.get("unified_stat_rows") or 0)
    blob = doc.get(field)
    if blob is None:
        stat = doc.get("simulator_result", {}).get("statdetail", {})
        key = {
            "hit_count_list_compressed": "cachelinehitcount",
            "first_miss_count_compressed": "cachelinefirstmisscount",
            "second_miss_count_compressed": "cachelinesecondmisscount",
        }[field]
        return [[int(value) for value in row] for row in stat.get(key, [])]
    raw = gzip.decompress(bytes(blob))
    expected = rows * 32 * 4
    if len(raw) != expected:
        raise ValueError(f"{field}: got {len(raw)} bytes, expected {expected}")
    values = struct.unpack(f"<{rows * 32}I", raw)
    return [list(values[i * 32 : (i + 1) * 32]) for i in range(rows)]


def latest_comparable_doc(collection, dataset: dict[str, Any]) -> dict[str, Any]:
    query = {
        "simulator_result.type": "UnifiedCache",
        "trace_file_name": dataset["trace"],
        "rule_file_name": Path(dataset["rule"]).name,
        "simulator_result.processed": dataset["processed"],
        "simulator_result.parameter.size": CAPACITY,
        "simulator_result.parameter.way": WAY,
        "simulator_result.parameter.cacheindextype": INDEX_TYPE,
    }
    projection = {
        "timestamp": 1,
        "simulator_result.hitrate": 1,
        "simulator_result.parameter": 1,
        "unified_stat_rows": 1,
        "hit_count_list_compressed": 1,
        "first_miss_count_compressed": 1,
        "second_miss_count_compressed": 1,
        "simulator_result.statdetail": 1,
    }
    for doc in collection.find(query, projection).sort("timestamp", -1):
        p = doc["simulator_result"].get("parameter", {})
        tags = p.get("cachetaglength", [])
        normalized = [tuple(int(x) for x in pair) for pair in tags if isinstance(pair, (list, tuple))]
        if len(normalized) not in (1, WAY) or len(normalized) != len(tags):
            continue
        if any(pair != (9, 24) for pair in normalized):
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
    raise RuntimeError(f"no matching result for {dataset['label']}")


def ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    output = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][1] == ordered[i][1]:
            j += 1
        rank = (i + 1 + j) / 2
        for k in range(i, j):
            output[ordered[k][0]] = rank
        i = j
    return output


def correlation(xs: list[float], ys: list[float]) -> float:
    mx, my = fmean(xs), fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return cov / denom if denom else float("nan")


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile, matching common spreadsheet defaults."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(rows: list[dict[str, Any]], totals: dict[str, int], doc: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    hit_sum = sum(int(row["hits"]) for row in rows)
    first_sum = sum(int(row["first_misses"]) for row in rows)
    second_sum = sum(int(row["repeat_misses"]) for row in rows)
    misses = first_sum + second_sum
    probes = hit_sum + misses
    return {
        "trace_label": dataset["label"],
        "processed_packets": dataset["processed"],
        **totals,
        "unique_cache_keys_per_set_sum": totals["unique_cache_key_set_pairs"],
        "packet_level_hitrate_percent": 100 * float(doc["simulator_result"]["hitrate"]),
        "probe_weighted_hitrate_percent": 100 * hit_sum / probes if probes else 0,
        "cacheline_hits": hit_sum,
        "first_misses": first_sum,
        "repeat_misses": second_sum,
        "cacheline_misses": misses,
        "cacheline_probes": probes,
        "repeat_miss_share_percent": 100 * second_sum / misses if misses else 0,
        "active_probe_sets": sum(int(row["probes"]) > 0 for row in rows),
        "timestamp": str(doc.get("timestamp", "")),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_results(path: Path, series: dict[str, list[dict[str, Any]]]) -> None:
    colors = {"NYC": "#D1495B", "WIDE Mar": "#00798C"}
    fig, axes = plt.subplots(3, 1, figsize=(13.5, 10), sharex=False)
    for label, rows in series.items():
        color = colors[label]
        x = [int(row["set_id"]) for row in rows]
        miss_rates = [float(row["miss_rate_percent"]) for row in rows]
        axes[0].plot(x, miss_rates, color=color, linewidth=1.1, label=label)
        axes[1].scatter([int(row["unique_cache_keys"]) for row in rows], miss_rates, s=14, alpha=.55, color=color, label=label)
        axes[2].scatter([int(row["unique_lpm_prefixes"]) for row in rows], miss_rates, s=14, alpha=.55, color=color, label=label)
    axes[0].set_ylabel("Set miss rate (%)")
    axes[0].set_title("Per-set cacheline miss rate: NYC vs WIDE Mar", loc="left", weight="bold")
    axes[0].set_xlabel("Set index (0–1023)")
    axes[0].set_ylim(0, 100)
    axes[1].set_ylabel("Set miss rate (%)")
    axes[1].set_xlabel("Unique cache keys per set: (network, tag length)")
    axes[1].set_title("Miss rate vs unique cache-key count", loc="left")
    axes[1].set_ylim(0, 100)
    axes[2].set_ylabel("Set miss rate (%)")
    axes[2].set_xlabel("Unique LPM route prefixes touched in set")
    axes[2].set_title("Miss rate vs unique LPM-prefix count", loc="left")
    axes[2].set_ylim(0, 100)
    for ax in axes:
        ax.grid(True, alpha=.22)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


def write_report(path: Path, summaries: list[dict[str, Any]], rows_by_trace: dict[str, list[dict[str, Any]]]) -> None:
    lines = [
        "# NYC and WIDE Mar: per-set misses and unique prefixes",
        "",
        "- Cache: UnifiedCache, 8,192 entries, way 8, 1,024 sets, index type 5 (CRC32 of destination /18). Exclusive insertion, fixed indexing, set extension off, tag range /9–/24.",
        "- Per-set miss rate = (first misses + repeat misses) / (hits + first misses + repeat misses), using stored cacheline counters.",
        "- Unique LPM prefix = distinct `(LPM network, LPM length)` matched by TCP/UDP destinations mapped to each index set.",
        "- Effective cache prefix = the first destination-prefix depth with no more-specific route below it, matching the simulator's `IsLeafIndex`; it is clamped to /9–/24 for exclusive insertion.",
        "- Unique cache key = distinct `(destination network at selected /9–/24 cache length, cache length)` mapped to each set. This is the closer proxy for cache-entry pressure.",
        "- A prefix can be touched from multiple /18 hash sets, so summed per-set unique-prefix counts can exceed the trace-wide unique count. Full-trace unique counts are not concurrent working-set sizes.",
        "- One packet can probe multiple prefix cache lines. Set-local miss rates are probe-level and are not a packet-disjoint decomposition of the DB hit rate.",
        "",
        "| trace | DB packet hit rate | probe-level hit rate | unique destinations | unique LPM prefixes | unique effective prefixes | unique cache keys | active sets | repeat share of misses |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['trace_label']} | {s['packet_level_hitrate_percent']:.3f}% | {s['probe_weighted_hitrate_percent']:.3f}% | {s['unique_destinations']:,} | {s['unique_lpm_prefixes_across_trace']:,} | {s['unique_effective_prefixes_across_trace']:,} | {s['unique_cache_keys_across_trace']:,} | {s['active_probe_sets']}/1024 | {s['repeat_miss_share_percent']:.2f}% |"
        )
    lines.extend([
        "## Per-set miss-rate distribution",
        "",
        "Percentiles are unweighted across the 1,024 sets. Small and large sets therefore count equally; use the probe-weighted hit rate above for the overall cacheline view.",
        "",
        "| trace | p10 | median | p90 | max | sets with miss rate >=5% | sets with miss rate >=10% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for label, rows in rows_by_trace.items():
        miss = [float(row["miss_rate_percent"]) for row in rows]
        lines.append(
            f"| {label} | {percentile(miss, .1):.2f}% | {percentile(miss, .5):.2f}% | {percentile(miss, .9):.2f}% | {max(miss):.2f}% | {sum(value >= 5 for value in miss)} | {sum(value >= 10 for value in miss)} |"
        )
    lines.extend(["", "## Interpretation", "", "- NYC has fewer unique destination IPs than WIDE Mar (276k vs 357k), but about 6.1x as many distinct LPM route prefixes (39.5k vs 6.5k) and 8.2x as many effective cache keys (55.3k vs 6.75k). Thus unique IP count alone is misleading: NYC destinations fan out across substantially more route/cache prefixes.", "- NYC also has far more repeat misses: 558,858, or 86.6% of misses, compared with 5,646, or 19.8%, for WIDE Mar. This points to temporal reuse/eviction behavior as an important part of the difference, alongside prefix cardinality.", "- Within each trace, the per-set count of unique prefixes/keys is only weakly related to miss rate (Spearman about +0.24 for NYC and -0.21 for WIDE Mar). Per-set packet volume has a stronger negative rank association (-0.74 and -0.90): hotter sets tend to have lower miss rates, consistent with repeated accesses amortizing cold misses. This is an association, not proof that volume itself causes hits.", "- WIDE Mar's median set miss rate is lower (5.73% vs 11.56%), even though its p90 and maximum are higher (25.93%/81.76% vs 23.72%/52.29%). A few WIDE sets have high rates despite little traffic, so the median and overall probe-weighted rate tell different parts of the story.", ""])
    lines.extend(["## Per-set association", "", "Pearson and Spearman values below compare each set's cacheline miss rate with the indicated set-level quantity (n=1,024 sets). These describe association only.", ""])
    lines.append("| trace | quantity | Pearson r | Spearman rho |")
    lines.append("|---|---|---:|---:|")
    for label, rows in rows_by_trace.items():
        miss = [float(row["miss_rate_percent"]) for row in rows]
        for name, key in (("unique cache keys", "unique_cache_keys"), ("unique effective prefixes", "unique_effective_prefixes"), ("unique LPM prefixes", "unique_lpm_prefixes"), ("TCP/UDP packets", "tcp_udp_packets"), ("cacheable-prefix packets", "cacheable_prefix_packets"), ("repeat-miss share", "repeat_miss_share_percent")):
            values = [float(row[key]) for row in rows]
            lines.append(f"| {label} | {name} | {correlation(values, miss):.3f} | {correlation(ranks(values), ranks(miss)):.3f} |")
    lines.extend(["", "## How to read this", "", "- If many distinct cache keys are mapped to a set, the 8-way set has more keys competing over the full trace. That count alone does not say how many keys are simultaneously active.", "- A high repeat-miss share indicates the same cache key has missed before and is missing again; this is consistent with eviction or insufficient temporal reuse. A low first-miss share is not itself a proof of conflict.", "- Compare `per_set.csv` for the actual set-by-set miss rates, unique prefix/key counts, packet volumes, and first/repeat misses. Use `set_miss_prefixes.png` to see the distributions and associations.", "- Cross-trace differences can also come from the different NYC and WIDE routing tables and traffic composition. Per-set correlations do not establish causation.", "", "## Files", "", "- `trace_summary.csv`: trace-wide prefix and miss summary.", "- `per_set.csv`: joined 1,024-set measurements for both traces.", "- `set_miss_prefixes.png`: local miss-rate and unique-prefix comparisons.", ""])
    path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10_000)
    collection = client[args.db][args.collection]
    summaries: list[dict[str, Any]] = []
    joined: list[dict[str, Any]] = []
    rows_by_trace: dict[str, list[dict[str, Any]]] = {}
    try:
        for dataset in DATASETS:
            flow_path = FLOW_ROOT / dataset["trace_dir"] / "flow_lengths.csv"
            destinations = read_flow_destinations(flow_path)
            prefix_sets, route_starts, route_lengths, route_tree = read_rules(Path(dataset["rule"]))
            prefix_rows, totals = unique_prefix_stats(destinations, prefix_sets, route_starts, route_lengths, route_tree)
            doc = latest_comparable_doc(collection, dataset)
            hit_rows = decode_rows(doc, "hit_count_list_compressed")
            first_rows = decode_rows(doc, "first_miss_count_compressed")
            second_rows = decode_rows(doc, "second_miss_count_compressed")
            if any(len(data) != SET_COUNT for data in (hit_rows, first_rows, second_rows)):
                raise ValueError(f"expected {SET_COUNT} counter rows for {dataset['label']}")
            per_set: list[dict[str, Any]] = []
            for i in range(SET_COUNT):
                hits = sum(hit_rows[i])
                first = sum(first_rows[i])
                second = sum(second_rows[i])
                misses = first + second
                probes = hits + misses
                row = {
                    "trace_label": dataset["label"],
                    **prefix_rows[i],
                    "hits": hits,
                    "first_misses": first,
                    "repeat_misses": second,
                    "misses": misses,
                    "probes": probes,
                    "miss_rate_percent": 100 * misses / probes if probes else 0,
                    "repeat_miss_share_percent": 100 * second / misses if misses else 0,
                    "probes_per_cache_key": probes / prefix_rows[i]["unique_cache_keys"] if prefix_rows[i]["unique_cache_keys"] else "",
                    "cache_keys_per_way": prefix_rows[i]["unique_cache_keys"] / WAY,
                }
                per_set.append(row)
                joined.append(row)
            summary = summarize(per_set, totals, doc, dataset)
            summaries.append(summary)
            rows_by_trace[dataset["label"]] = per_set
    finally:
        client.close()
    write_csv(args.output_dir / "trace_summary.csv", summaries)
    write_csv(args.output_dir / "per_set.csv", joined)
    plot_results(args.output_dir / "set_miss_prefixes.png", rows_by_trace)
    write_report(args.output_dir / "REPORT.md", summaries, rows_by_trace)
    for name in ("REPORT.md", "trace_summary.csv", "per_set.csv", "set_miss_prefixes.png"):
        print(args.output_dir / name)


if __name__ == "__main__":
    main()
