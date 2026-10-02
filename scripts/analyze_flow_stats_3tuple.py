#!/usr/bin/env python3
"""Aggregate existing flow_lengths.csv files by directional IPv4 3-tuples."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


TRACE_ORDER = {
    "2025-09-27": 0,
    "2025-12-27": 1,
    "2026-03-27": 2,
    "equinix-chicago-20140320": 3,
}

SUMMARY_FIELDS = [
    "trace",
    "mode",
    "source_ipv4_packets",
    "included_packets",
    "source_5tuple_flow_count",
    "flow_count",
    "flow_count_ratio_vs_5tuple",
    "flows_per_million_packets",
    "packets_per_flow",
    "one_packet_flow_count",
    "one_packet_flow_ratio",
    "single_packet_packet_share",
    "top1_packet_share",
    "top10_packet_share",
    "top100_packet_share",
    "p50_packets_per_flow",
    "p90_packets_per_flow",
    "p99_packets_per_flow",
    "max_packets_per_flow",
    "cutoff99_flow_count_bin",
    "cutoff995_flow_count_bin",
    "cutoff999_flow_count_bin",
    "ge1024_flow_count",
    "ge1024_flow_ratio",
    "ge1024_packet_share",
    "ge8192_flow_count",
    "ge8192_flow_ratio",
    "ge8192_packet_share",
    "max_nonempty_bin",
    "top_flow",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reaggregate flow stats by protocol/src_ip/dst_ip."
    )
    parser.add_argument("--input-root", default="scripts/reports/flow_stats")
    parser.add_argument("--output-root", default="scripts/reports/flow_stats_3tuple")
    parser.add_argument("--top-n", type=int, default=100)
    return parser.parse_args()


def read_metric_csv(path: Path) -> dict[str, str]:
    with path.open(newline="") as f:
        return {row["metric"]: row["value"] for row in csv.DictReader(f)}


def parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def packet_bin(packets: int) -> tuple[int, int]:
    if packets <= 1:
        return 1, 1
    lower = 1 << (packets.bit_length() - 1)
    return lower, (lower << 1) - 1


def format_bin(lower: int, upper: int) -> str:
    if lower == upper:
        return f"{lower:,}"
    return f"{lower:,}-{upper:,}"


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    pos = int(round((len(sorted_values) - 1) * q))
    pos = max(0, min(pos, len(sorted_values) - 1))
    return sorted_values[pos]


def aggregate_trace(trace_dir: Path, exclude_icmp: bool, top_n: int) -> dict[str, object]:
    source_summary = read_metric_csv(trace_dir / "flow_summary.csv")
    source_ipv4_packets = int(source_summary["ipv4_packets"])

    aggregates: dict[tuple[int, str, str], dict[str, object]] = {}
    source_5tuple_flow_count = 0

    with (trace_dir / "flow_lengths.csv").open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_5tuple_flow_count += 1
            protocol_number = int(row["protocol_number"])
            if exclude_icmp and protocol_number == 1:
                continue

            key = (protocol_number, row["src_ip"], row["dst_ip"])
            packets = int(row["packets"])
            bytes_ = int(row["bytes"])
            first_seen = parse_time(row["first_seen"])
            last_seen = parse_time(row["last_seen"])
            item = aggregates.get(key)
            if item is None:
                aggregates[key] = {
                    "protocol_number": protocol_number,
                    "protocol": row["protocol"],
                    "src_ip": row["src_ip"],
                    "dst_ip": row["dst_ip"],
                    "packets": packets,
                    "bytes": bytes_,
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    "merged_5tuple_flows": 1,
                }
                continue

            item["packets"] = int(item["packets"]) + packets
            item["bytes"] = int(item["bytes"]) + bytes_
            item["first_seen"] = min(item["first_seen"], first_seen)
            item["last_seen"] = max(item["last_seen"], last_seen)
            item["merged_5tuple_flows"] = int(item["merged_5tuple_flows"]) + 1

    flows = sorted(
        aggregates.values(),
        key=lambda item: (
            -int(item["packets"]),
            int(item["protocol_number"]),
            str(item["src_ip"]),
            str(item["dst_ip"]),
        ),
    )
    included_packets = sum(int(item["packets"]) for item in flows)
    included_bytes = sum(int(item["bytes"]) for item in flows)
    flow_count = len(flows)

    packets_values = sorted(int(item["packets"]) for item in flows)
    one_packet_flow_count = sum(1 for value in packets_values if value == 1)
    top1 = sum(int(item["packets"]) for item in flows[:1])
    top10 = sum(int(item["packets"]) for item in flows[:10])
    top100 = sum(int(item["packets"]) for item in flows[:top_n])

    bins: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"flows": 0, "packets": 0, "bytes": 0}
    )
    for item in flows:
        lower, upper = packet_bin(int(item["packets"]))
        bins[(lower, upper)]["flows"] += 1
        bins[(lower, upper)]["packets"] += int(item["packets"])
        bins[(lower, upper)]["bytes"] += int(item["bytes"])

    bin_rows = build_bin_rows(bins, flow_count, included_packets, included_bytes)
    ge1024 = sum_tail(bin_rows, 1024)
    ge8192 = sum_tail(bin_rows, 8192)

    summary = {
        "trace": trace_dir.name,
        "mode": "3tuple_no_icmp" if exclude_icmp else "3tuple_all_ipv4",
        "source_ipv4_packets": source_ipv4_packets,
        "included_packets": included_packets,
        "source_5tuple_flow_count": source_5tuple_flow_count,
        "flow_count": flow_count,
        "flow_count_ratio_vs_5tuple": ratio(flow_count, source_5tuple_flow_count),
        "flows_per_million_packets": ratio(flow_count * 1_000_000, included_packets),
        "packets_per_flow": ratio(included_packets, flow_count),
        "one_packet_flow_count": one_packet_flow_count,
        "one_packet_flow_ratio": ratio(one_packet_flow_count, flow_count),
        "single_packet_packet_share": ratio(one_packet_flow_count, included_packets),
        "top1_packet_share": ratio(top1, included_packets),
        "top10_packet_share": ratio(top10, included_packets),
        "top100_packet_share": ratio(top100, included_packets),
        "p50_packets_per_flow": percentile(packets_values, 0.50),
        "p90_packets_per_flow": percentile(packets_values, 0.90),
        "p99_packets_per_flow": percentile(packets_values, 0.99),
        "max_packets_per_flow": packets_values[-1] if packets_values else 0,
        "cutoff99_flow_count_bin": cutoff_bin(bin_rows, 0.99),
        "cutoff995_flow_count_bin": cutoff_bin(bin_rows, 0.995),
        "cutoff999_flow_count_bin": cutoff_bin(bin_rows, 0.999),
        "ge1024_flow_count": ge1024["flows"],
        "ge1024_flow_ratio": ge1024["flow_ratio"],
        "ge1024_packet_share": ge1024["packet_ratio"],
        "ge8192_flow_count": ge8192["flows"],
        "ge8192_flow_ratio": ge8192["flow_ratio"],
        "ge8192_packet_share": ge8192["packet_ratio"],
        "max_nonempty_bin": format_bin(bin_rows[-1]["lower"], bin_rows[-1]["upper"]) if bin_rows else "",
        "top_flow": format_flow(flows[0]) if flows else "",
    }

    out_dir = Path(args.output_root) / trace_dir.name / summary["mode"]
    out_dir.mkdir(parents=True, exist_ok=True)
    write_top_flows(out_dir / "top_flows.csv", flows[:top_n])
    write_bin_csv(out_dir / "flow_length_bins.csv", bin_rows)
    write_metric_csv(out_dir / "flow_summary.csv", summary)
    return summary


def build_bin_rows(
    bins: dict[tuple[int, int], dict[str, float]],
    flow_count: int,
    packet_count: int,
    byte_count: int,
) -> list[dict[str, object]]:
    rows = []
    cumulative_flows = 0
    cumulative_packets = 0
    for lower, upper in sorted(bins):
        flows = int(bins[(lower, upper)]["flows"])
        packets = int(bins[(lower, upper)]["packets"])
        bytes_ = int(bins[(lower, upper)]["bytes"])
        cumulative_flows += flows
        cumulative_packets += packets
        rows.append(
            {
                "bin": format_bin(lower, upper),
                "lower": lower,
                "upper": upper,
                "flows": flows,
                "flow_ratio": ratio(flows, flow_count),
                "cumulative_flow_ratio": ratio(cumulative_flows, flow_count),
                "packets": packets,
                "packet_ratio": ratio(packets, packet_count),
                "cumulative_packet_ratio": ratio(cumulative_packets, packet_count),
                "bytes": bytes_,
                "byte_ratio": ratio(bytes_, byte_count),
            }
        )
    return rows


def cutoff_bin(bin_rows: list[dict[str, object]], threshold: float) -> str:
    for row in bin_rows:
        if float(row["cumulative_flow_ratio"]) >= threshold:
            return str(row["bin"])
    return str(bin_rows[-1]["bin"]) if bin_rows else ""


def sum_tail(bin_rows: list[dict[str, object]], lower_bound: int) -> dict[str, float]:
    flows = sum(int(row["flows"]) for row in bin_rows if int(row["lower"]) >= lower_bound)
    packets = sum(int(row["packets"]) for row in bin_rows if int(row["lower"]) >= lower_bound)
    total_flows = sum(int(row["flows"]) for row in bin_rows)
    total_packets = sum(int(row["packets"]) for row in bin_rows)
    return {
        "flows": flows,
        "flow_ratio": ratio(flows, total_flows),
        "packet_ratio": ratio(packets, total_packets),
    }


def format_flow(item: dict[str, object]) -> str:
    duration = (item["last_seen"] - item["first_seen"]).total_seconds()
    merged = int(item["merged_5tuple_flows"])
    return (
        f"{item['protocol']} {item['src_ip']} -> {item['dst_ip']} "
        f"({int(item['packets']):,} pkts, {duration:.1f}s, merged {merged:,} 5-tuples)"
    )


def write_top_flows(path: Path, flows: list[dict[str, object]]) -> None:
    fields = [
        "rank",
        "protocol_number",
        "protocol",
        "src_ip",
        "dst_ip",
        "packets",
        "bytes",
        "duration_seconds",
        "first_seen",
        "last_seen",
        "merged_5tuple_flows",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rank, item in enumerate(flows, start=1):
            first_seen = item["first_seen"]
            last_seen = item["last_seen"]
            writer.writerow(
                {
                    "rank": rank,
                    "protocol_number": item["protocol_number"],
                    "protocol": item["protocol"],
                    "src_ip": item["src_ip"],
                    "dst_ip": item["dst_ip"],
                    "packets": item["packets"],
                    "bytes": item["bytes"],
                    "duration_seconds": f"{(last_seen - first_seen).total_seconds():.12f}",
                    "first_seen": format_time(first_seen),
                    "last_seen": format_time(last_seen),
                    "merged_5tuple_flows": item["merged_5tuple_flows"],
                }
            )


def write_bin_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "bin",
        "lower",
        "upper",
        "flows",
        "flow_ratio",
        "cumulative_flow_ratio",
        "packets",
        "packet_ratio",
        "cumulative_packet_ratio",
        "bytes",
        "byte_ratio",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_metric_csv(path: Path, summary: dict[str, object]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for field in SUMMARY_FIELDS:
            writer.writerow([field, summary[field]])


def write_summary_csv(path: Path, summaries: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summaries)


def pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%"


def write_markdown(path: Path, summaries: list[dict[str, object]]) -> None:
    all_ipv4 = [row for row in summaries if row["mode"] == "3tuple_all_ipv4"]
    no_icmp = [row for row in summaries if row["mode"] == "3tuple_no_icmp"]
    with path.open("w") as f:
        f.write("# Directional IPv4 3-tuple flow analysis\n\n")
        f.write("Flow key: `protocol_number`, `src_ip`, `dst_ip`. Ports are ignored.\n\n")
        for title, rows in [("All IPv4", all_ipv4), ("Excluding ICMP", no_icmp)]:
            f.write(f"## {title}\n\n")
            f.write("| trace | flows | flows / 1M pkts | pkts / flow | 1-pkt ratio | top100 pkt share | 8192+ pkt share | 99% cutoff | top flow |\n")
            f.write("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n")
            for row in rows:
                f.write(
                    "| {trace} | {flows:,} | {density:,.0f} | {ppf:.2f} | {one} | {top100} | {tail8192} | {cutoff} | {top} |\n".format(
                        trace=row["trace"],
                        flows=int(row["flow_count"]),
                        density=float(row["flows_per_million_packets"]),
                        ppf=float(row["packets_per_flow"]),
                        one=pct(row["one_packet_flow_ratio"]),
                        top100=pct(row["top100_packet_share"]),
                        tail8192=pct(row["ge8192_packet_share"]),
                        cutoff=row["cutoff99_flow_count_bin"],
                        top=row["top_flow"],
                    )
                )
            f.write("\n")


def main() -> None:
    global args
    args = parse_args()
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    trace_dirs = [
        path
        for path in sorted(input_root.iterdir(), key=lambda p: (TRACE_ORDER.get(p.name, 100), p.name))
        if path.is_dir() and (path / "flow_lengths.csv").exists()
    ]
    summaries = []
    for trace_dir in trace_dirs:
        summaries.append(aggregate_trace(trace_dir, exclude_icmp=False, top_n=args.top_n))
        summaries.append(aggregate_trace(trace_dir, exclude_icmp=True, top_n=args.top_n))
    write_summary_csv(output_root / "flow_trace_summary_3tuple.csv", summaries)
    write_markdown(output_root / "flow_count_length_3tuple.md", summaries)


if __name__ == "__main__":
    main()
