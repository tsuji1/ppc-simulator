#!/usr/bin/env python3
"""Analyze space-separated 5tuple text traces into flow_stats-compatible CSVs.

Expected input columns:

time srcIP srcPort dstIP dstPort protocol tos length
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path


SUMMARY_FIELDS = [
    "trace",
    "trace_kind",
    "format",
    "flow_definition",
    "included_non_tcp_udp_icmp_ipv4_in_flow_stats",
    "max_packets",
    "top_n",
    "total_packets",
    "ipv4_packets",
    "non_ipv4_packets",
    "parse_error_packets",
    "read_error_packets",
    "transport_parse_error_packets",
    "ipv4_bytes",
    "tcp_packets",
    "udp_packets",
    "icmp_packets",
    "other_ipv4_packets",
    "unique_flow_count",
    "one_packet_flow_count",
    "one_packet_flow_ratio",
    "top1_flow_packet_count",
    "top1_flow_packet_share",
    "top5_flow_packet_count",
    "top5_flow_packet_share",
    "top10_flow_packet_count",
    "top10_flow_packet_share",
    "top50_flow_packet_count",
    "top50_flow_packet_share",
    "top100_flow_packet_count",
    "top100_flow_packet_share",
    "p50_packets_per_flow",
    "p90_packets_per_flow",
    "p99_packets_per_flow",
    "max_packets_per_flow",
    "p50_bytes_per_flow",
    "p90_bytes_per_flow",
    "p99_bytes_per_flow",
    "max_bytes_per_flow",
    "p50_duration_seconds",
    "p90_duration_seconds",
    "p99_duration_seconds",
    "max_duration_seconds",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze 8-column 5tuple text traces.")
    parser.add_argument("--trace", required=True)
    parser.add_argument("--trace-kind", default="non-anonymized")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-packets", type=int, default=0, help="0 reads the whole trace")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--progress-interval", type=int, default=10_000_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trace = Path(args.trace)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    flows: dict[tuple[int, str, str, int, int], dict[str, object]] = {}
    protocol_packets: dict[int, int] = defaultdict(int)
    protocol_flows: dict[int, int] = defaultdict(int)

    total_packets = 0
    ipv4_packets = 0
    ipv4_bytes = 0
    parse_error_packets = 0
    read_error_packets = 0
    first_trace_time: float | None = None

    with trace.open() as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if args.max_packets and total_packets >= args.max_packets:
                break
            line = raw_line.strip()
            if not line:
                continue
            total_packets += 1
            parts = line.split()
            if len(parts) != 8:
                parse_error_packets += 1
                continue
            try:
                timestamp = float(parts[0])
                src_ip = parts[1]
                src_port = parse_port(parts[2])
                dst_ip = parts[3]
                dst_port = parse_port(parts[4])
                protocol_number, protocol = parse_protocol(parts[5])
                packet_len = int(parts[7])
            except ValueError:
                parse_error_packets += 1
                continue

            if first_trace_time is None:
                first_trace_time = timestamp
            rel_time = timestamp - first_trace_time
            if rel_time < 0:
                rel_time = timestamp

            ipv4_packets += 1
            ipv4_bytes += packet_len
            protocol_packets[protocol_number] += 1

            key = (protocol_number, src_ip, dst_ip, src_port, dst_port)
            flow = flows.get(key)
            if flow is None:
                flow = {
                    "protocol_number": protocol_number,
                    "protocol": protocol,
                    "src_ip": src_ip,
                    "dst_ip": dst_ip,
                    "src_port": src_port,
                    "dst_port": dst_port,
                    "packets": 0,
                    "bytes": 0,
                    "first_seen": rel_time,
                    "last_seen": rel_time,
                }
                flows[key] = flow
            flow["packets"] = int(flow["packets"]) + 1
            flow["bytes"] = int(flow["bytes"]) + packet_len
            if rel_time < float(flow["first_seen"]):
                flow["first_seen"] = rel_time
            if rel_time > float(flow["last_seen"]):
                flow["last_seen"] = rel_time

            if args.progress_interval and total_packets % args.progress_interval == 0:
                print(
                    f"processed {total_packets:,} packets (flows: {len(flows):,})",
                    file=sys.stderr,
                )

    flow_rows = sorted(
        flows.values(),
        key=lambda row: (
            -int(row["packets"]),
            int(row["protocol_number"]),
            str(row["src_ip"]),
            str(row["dst_ip"]),
            int(row["src_port"]),
            int(row["dst_port"]),
        ),
    )
    for row in flow_rows:
        protocol_flows[int(row["protocol_number"])] += 1

    summary = build_summary(args, trace, flow_rows, protocol_packets, total_packets, ipv4_packets, ipv4_bytes, parse_error_packets, read_error_packets)
    write_metric_csv(output_dir / "flow_summary.csv", summary)
    write_flow_lengths_csv(output_dir / "flow_lengths.csv", flow_rows)
    write_top_flows_csv(output_dir / "top_flows.csv", flow_rows[: args.top_n])
    write_bins_csv(output_dir / "flow_length_bins.csv", flow_rows, ipv4_packets, ipv4_bytes)
    write_protocol_csv(output_dir / "protocol_counts.csv", protocol_packets, protocol_flows, ipv4_packets, len(flow_rows))
    write_summary_md(output_dir / "flow_stats_summary.md", trace, args, summary)
    print(f"wrote flow statistics report to {output_dir}", file=sys.stderr)


def parse_port(value: str) -> int:
    port = int(value)
    if port < 0 or port > 65535:
        return 0
    return port


def parse_protocol(value: str) -> tuple[int, str]:
    upper = value.upper()
    if upper == "TCP":
        return 6, "TCP"
    if upper == "UDP":
        return 17, "UDP"
    if upper == "ICMP":
        return 1, "ICMP"
    number = int(value, 0)
    return number, protocol_name(number)


def protocol_name(protocol: int) -> str:
    if protocol == 6:
        return "TCP"
    if protocol == 17:
        return "UDP"
    if protocol == 1:
        return "ICMP"
    return f"IP:{protocol}"


def build_summary(
    args: argparse.Namespace,
    trace: Path,
    rows: list[dict[str, object]],
    protocol_packets: dict[int, int],
    total_packets: int,
    ipv4_packets: int,
    ipv4_bytes: int,
    parse_error_packets: int,
    read_error_packets: int,
) -> dict[str, object]:
    packets_values = sorted(int(row["packets"]) for row in rows)
    bytes_values = sorted(int(row["bytes"]) for row in rows)
    duration_values = sorted(float(row["last_seen"]) - float(row["first_seen"]) for row in rows)
    top = lambda n: sum(int(row["packets"]) for row in rows[:n])
    top1 = top(1)
    top5 = top(5)
    top10 = top(10)
    top50 = top(50)
    top100 = top(100)
    one_packet_flow_count = sum(1 for value in packets_values if value == 1)
    return {
        "trace": str(trace),
        "trace_kind": args.trace_kind,
        "format": "5tuple-text",
        "flow_definition": "directional_ipv4_5_tuple",
        "included_non_tcp_udp_icmp_ipv4_in_flow_stats": "true",
        "max_packets": args.max_packets,
        "top_n": args.top_n,
        "total_packets": total_packets,
        "ipv4_packets": ipv4_packets,
        "non_ipv4_packets": 0,
        "parse_error_packets": parse_error_packets,
        "read_error_packets": read_error_packets,
        "transport_parse_error_packets": 0,
        "ipv4_bytes": ipv4_bytes,
        "tcp_packets": protocol_packets.get(6, 0),
        "udp_packets": protocol_packets.get(17, 0),
        "icmp_packets": protocol_packets.get(1, 0),
        "other_ipv4_packets": sum(count for proto, count in protocol_packets.items() if proto not in (1, 6, 17)),
        "unique_flow_count": len(rows),
        "one_packet_flow_count": one_packet_flow_count,
        "one_packet_flow_ratio": ratio(one_packet_flow_count, len(rows)),
        "top1_flow_packet_count": top1,
        "top1_flow_packet_share": ratio(top1, ipv4_packets),
        "top5_flow_packet_count": top5,
        "top5_flow_packet_share": ratio(top5, ipv4_packets),
        "top10_flow_packet_count": top10,
        "top10_flow_packet_share": ratio(top10, ipv4_packets),
        "top50_flow_packet_count": top50,
        "top50_flow_packet_share": ratio(top50, ipv4_packets),
        "top100_flow_packet_count": top100,
        "top100_flow_packet_share": ratio(top100, ipv4_packets),
        "p50_packets_per_flow": percentile(packets_values, 0.50),
        "p90_packets_per_flow": percentile(packets_values, 0.90),
        "p99_packets_per_flow": percentile(packets_values, 0.99),
        "max_packets_per_flow": packets_values[-1] if packets_values else 0,
        "p50_bytes_per_flow": percentile(bytes_values, 0.50),
        "p90_bytes_per_flow": percentile(bytes_values, 0.90),
        "p99_bytes_per_flow": percentile(bytes_values, 0.99),
        "max_bytes_per_flow": bytes_values[-1] if bytes_values else 0,
        "p50_duration_seconds": percentile(duration_values, 0.50),
        "p90_duration_seconds": percentile(duration_values, 0.90),
        "p99_duration_seconds": percentile(duration_values, 0.99),
        "max_duration_seconds": duration_values[-1] if duration_values else 0.0,
    }


def write_metric_csv(path: Path, summary: dict[str, object]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for field in SUMMARY_FIELDS:
            writer.writerow([field, format_value(summary.get(field, ""))])


def write_flow_lengths_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "protocol_number",
                "protocol",
                "src_ip",
                "dst_ip",
                "src_port",
                "dst_port",
                "packets",
                "bytes",
                "duration_seconds",
                "first_seen",
                "last_seen",
            ]
        )
        for rank, row in enumerate(rows, start=1):
            writer.writerow(flow_csv_row(rank, row))


def write_top_flows_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "protocol_number",
                "protocol",
                "src_ip",
                "dst_ip",
                "src_port",
                "dst_port",
                "packets",
                "bytes",
                "duration_seconds",
                "first_seen",
                "last_seen",
            ]
        )
        for rank, row in enumerate(rows, start=1):
            writer.writerow(flow_csv_row(rank, row))


def flow_csv_row(rank: int, row: dict[str, object]) -> list[object]:
    first = float(row["first_seen"])
    last = float(row["last_seen"])
    return [
        rank,
        row["protocol_number"],
        row["protocol"],
        row["src_ip"],
        row["dst_ip"],
        row["src_port"],
        row["dst_port"],
        row["packets"],
        row["bytes"],
        f"{(last - first):.12f}",
        f"{first:.9f}",
        f"{last:.9f}",
    ]


def write_bins_csv(path: Path, rows: list[dict[str, object]], total_packets: int, total_bytes: int) -> None:
    bins: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"flows": 0, "packets": 0, "bytes": 0})
    for row in rows:
        lower, upper = packet_bin(int(row["packets"]))
        item = bins[(lower, upper)]
        item["flows"] += 1
        item["packets"] += int(row["packets"])
        item["bytes"] += int(row["bytes"])
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "packet_count_lower",
                "packet_count_upper",
                "flow_count",
                "flow_ratio",
                "packet_sum",
                "packet_ratio",
                "byte_sum",
                "byte_ratio",
            ]
        )
        for (lower, upper), item in sorted(bins.items()):
            writer.writerow(
                [
                    lower,
                    upper,
                    item["flows"],
                    f"{ratio(item['flows'], len(rows)):.12f}",
                    item["packets"],
                    f"{ratio(item['packets'], total_packets):.12f}",
                    item["bytes"],
                    f"{ratio(item['bytes'], total_bytes):.12f}",
                ]
            )


def write_protocol_csv(
    path: Path,
    protocol_packets: dict[int, int],
    protocol_flows: dict[int, int],
    total_packets: int,
    total_flows: int,
) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["protocol_number", "protocol_name", "flow_count", "flow_ratio", "packets", "packet_ratio"])
        for proto in sorted(protocol_packets, key=lambda p: (-protocol_packets[p], p)):
            writer.writerow(
                [
                    proto,
                    protocol_name(proto),
                    protocol_flows[proto],
                    f"{ratio(protocol_flows[proto], total_flows):.12f}",
                    protocol_packets[proto],
                    f"{ratio(protocol_packets[proto], total_packets):.12f}",
                ]
            )


def write_summary_md(path: Path, trace: Path, args: argparse.Namespace, summary: dict[str, object]) -> None:
    lines = [
        f"# Flow Statistics: {trace.name}",
        "",
        "| metric | value |",
        "| --- | ---: |",
    ]
    for key in (
        "ipv4_packets",
        "unique_flow_count",
        "one_packet_flow_ratio",
        "top100_flow_packet_share",
        "p99_packets_per_flow",
        "max_packets_per_flow",
    ):
        lines.append(f"| {key} | {format_value(summary[key])} |")
    lines.extend(
        [
            "",
            "## Command",
            "",
            "```bash",
            "python3 scripts/analyze_5tuple_text_flow_stats.py \\",
            f"  --trace {trace} \\",
            f"  --trace-kind {args.trace_kind} \\",
            f"  --max-packets {args.max_packets} \\",
            f"  --output-dir {args.output_dir}",
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def packet_bin(packets: int) -> tuple[int, int]:
    if packets <= 1:
        return 1, 1
    lower = 1 << (packets.bit_length() - 1)
    return lower, (lower << 1) - 1


def percentile(values: list[float] | list[int], q: float):
    if not values:
        return 0
    index = math.ceil(q * len(values)) - 1
    index = max(0, min(index, len(values) - 1))
    return values[index]


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def format_value(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.12f}"
    return value


if __name__ == "__main__":
    main()
