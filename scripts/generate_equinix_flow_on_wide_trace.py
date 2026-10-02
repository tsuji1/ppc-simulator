#!/usr/bin/env python3
"""Generate a simulator trace from Equinix flow lengths on WIDE rule prefixes.

The output trace uses the simulator CSV format:

time,len,srcIP,dstIP,proto,srcPort,dstPort

Flow sizes and approximate temporal overlap are taken from an existing
flow_lengths.csv. Destination IPs are remapped into prefixes from a rule file.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import ipaddress
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_FLOW_LENGTHS = (
    Path("scripts")
    / "reports"
    / "flow_stats"
    / "equinix-chicago-20140320"
    / "flow_lengths.csv"
)
DEFAULT_RULE_FILE = Path("rules") / "wide.rib.20240625.1400.unique.rule"
TOP_NS = (1, 5, 10, 50, 100)


@dataclass(frozen=True)
class FlowTemplate:
    index: int
    rank: int
    protocol_number: int
    protocol: str
    original_src_ip: int
    original_dst_ip: int
    src_port: int
    dst_port: int
    packets: int
    bytes: int
    first_offset: float
    duration: float


@dataclass
class LocalityStats:
    previous: int | None = None
    current_run: int = 0
    run_count: int = 0
    run_total: int = 0
    max_run: int = 0

    def add(self, value: int) -> None:
        if self.previous is None:
            self.previous = value
            self.current_run = 1
            return
        if value == self.previous:
            self.current_run += 1
            return
        self.finish_run()
        self.previous = value
        self.current_run = 1

    def finish_run(self) -> None:
        if self.current_run <= 0:
            return
        self.run_count += 1
        self.run_total += self.current_run
        self.max_run = max(self.max_run, self.current_run)
        self.current_run = 0

    def average_run(self) -> float:
        if self.run_count == 0:
            return 0.0
        return self.run_total / self.run_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Equinix-flow-distribution traffic on WIDE rule destination prefixes."
    )
    parser.add_argument("--flow-lengths", default=str(DEFAULT_FLOW_LENGTHS))
    parser.add_argument("--rule-file", default=str(DEFAULT_RULE_FILE))
    parser.add_argument("--count", type=int, required=True, help="Number of packets/rows to emit.")
    parser.add_argument("--output", required=True, help="Output simulator CSV trace path.")
    parser.add_argument("--report-dir", default="", help="Output report directory.")
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=1)
    parser.add_argument("--time-step", type=float, default=0.000001)
    parser.add_argument("--prefix-lengths", default="8,16,18,24,32")
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument(
        "--other-proto-mode",
        choices=("udp", "drop"),
        default="udp",
        help="How to handle non-TCP/UDP flow templates in the simulator CSV.",
    )
    parser.add_argument(
        "--schedule",
        choices=("time-merge", "flow-contiguous"),
        default="time-merge",
        help="Packet ordering model. time-merge approximates overlap using first/last seen.",
    )
    parser.add_argument(
        "--dst-locality-mode",
        choices=("spread", "template-prefix-map"),
        default="spread",
        help=(
            "Destination assignment. spread distributes flows over WIDE prefixes; "
            "template-prefix-map maps original Equinix dst prefixes to stable WIDE prefixes."
        ),
    )
    parser.add_argument(
        "--template-prefix-length",
        type=int,
        default=24,
        help="Original Equinix dst prefix length used by --dst-locality-mode template-prefix-map.",
    )
    parser.add_argument(
        "--format",
        choices=("simulator-csv", "dstip"),
        default="simulator-csv",
        help="Output only destination IPs for LPM debugging, or full simulator CSV.",
    )
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    if args.seed == 0:
        parser.error("--seed must be non-zero")
    if args.time_step <= 0:
        parser.error("--time-step must be positive")
    if args.template_prefix_length < 0 or args.template_prefix_length > 32:
        parser.error("--template-prefix-length must be in 0..32")
    if args.top_n <= 0:
        parser.error("--top-n must be positive")
    args.prefix_lengths = parse_prefix_lengths(args.prefix_lengths)
    return args


def parse_prefix_lengths(raw: str) -> list[int]:
    values: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value < 0 or value > 32:
            raise argparse.ArgumentTypeError("prefix lengths must be in 0..32")
        values.add(value)
    if not values:
        raise argparse.ArgumentTypeError("at least one prefix length is required")
    return sorted(values)


def parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def int_to_ipv4(value: int) -> str:
    return str(ipaddress.IPv4Address(value & 0xFFFFFFFF))


def ipv4_to_int(value: str) -> int:
    return int(ipaddress.IPv4Address(value))


def prefix_string(prefix_value: int, prefix_length: int) -> str:
    if prefix_length == 0:
        network = 0
    else:
        network = (prefix_value << (32 - prefix_length)) & 0xFFFFFFFF
    return f"{int_to_ipv4(network)}/{prefix_length}"


def xorshift32(state: int) -> int:
    state &= 0xFFFFFFFF
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


def parse_rule_prefixes(path: Path) -> list[tuple[int, int]]:
    prefixes: list[tuple[int, int]] = []
    with path.open() as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            fields = line.split()
            try:
                if "/" in fields[0]:
                    network = ipaddress.IPv4Network(fields[0], strict=False)
                elif len(fields) >= 2:
                    network = ipaddress.IPv4Network(f"{fields[0]}/{int(fields[1])}", strict=False)
                else:
                    raise ValueError("expected '<ip> <prefix_len>' or '<prefix>/<prefix_len>'")
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid rule prefix: {exc}") from exc
            prefixes.append((int(network.network_address), network.prefixlen))
    if not prefixes:
        raise ValueError(f"no IPv4 prefixes found in {path}")
    return prefixes


def load_templates(path: Path) -> list[FlowTemplate]:
    raw_rows: list[dict[str, str]] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            packets = int(row["packets"])
            if packets <= 0:
                continue
            raw_rows.append(row)
    if not raw_rows:
        raise ValueError(f"no flow templates found in {path}")

    base_time = min(parse_time(row["first_seen"]) for row in raw_rows)
    templates: list[FlowTemplate] = []
    for index, row in enumerate(raw_rows):
        first_seen = parse_time(row["first_seen"])
        last_seen = parse_time(row["last_seen"])
        duration = max(0.0, (last_seen - first_seen).total_seconds())
        templates.append(
            FlowTemplate(
                index=index,
                rank=int(row["rank"]),
                protocol_number=int(row["protocol_number"]),
                protocol=row["protocol"],
                original_src_ip=ipv4_to_int(row["src_ip"]),
                original_dst_ip=ipv4_to_int(row["dst_ip"]),
                src_port=parse_port(row["src_port"]),
                dst_port=parse_port(row["dst_port"]),
                packets=int(row["packets"]),
                bytes=int(row["bytes"]),
                first_offset=max(0.0, (first_seen - base_time).total_seconds()),
                duration=duration,
            )
        )
    return templates


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        return 0
    if port < 0 or port > 65535:
        return 0
    return port


def simulator_proto(template: FlowTemplate, other_proto_mode: str) -> str | None:
    if template.protocol_number == 6:
        return "tcp"
    if template.protocol_number == 17:
        return "udp"
    if other_proto_mode == "drop":
        return None
    return "udp"


def source_ip_for_flow(flow_id: int) -> int:
    host = (flow_id % 0x00FFFFFE) + 1
    return (10 << 24) | host


def destination_for_flow(args: argparse.Namespace, template: FlowTemplate, flow_id: int, prefixes: list[tuple[int, int]]) -> int:
    if args.dst_locality_mode == "template-prefix-map":
        original_key = 0 if args.template_prefix_length == 0 else template.original_dst_ip >> (
            32 - args.template_prefix_length
        )
        prefix_index = mapped_prefix_index(original_key, args.template_prefix_length, prefixes, args.seed)
    else:
        prefix_index = ((flow_id * 1_103_515_245) + args.seed) % len(prefixes)
    network, prefix_length = prefixes[prefix_index]
    host_width = 32 - prefix_length
    if host_width <= 0:
        return network & 0xFFFFFFFF
    host_mask = (1 << host_width) - 1
    state = (
        args.seed
        ^ network
        ^ (prefix_length << 24)
        ^ template.original_dst_ip
        ^ ((flow_id + 1) * 0x9E3779B9)
    ) & 0xFFFFFFFF
    if state == 0:
        state = 1
    host = xorshift32(state) & host_mask
    return (network | host) & 0xFFFFFFFF


def mapped_prefix_index(original_key: int, original_length: int, prefixes: list[tuple[int, int]], seed: int) -> int:
    state = (seed ^ original_key ^ (original_length << 25) ^ 0xA5A5A5A5) & 0xFFFFFFFF
    if state == 0:
        state = 1
    return xorshift32(state) % len(prefixes)


def packet_len(template: FlowTemplate) -> int:
    if template.packets <= 0:
        return 64
    return max(46, min(9000, round(template.bytes / template.packets)))


def packet_byte_count(template: FlowTemplate) -> int:
    return packet_len(template)


def packet_time(template: FlowTemplate, seq: int, cycle_offset: float, time_step: float) -> float:
    if template.packets <= 1 or template.duration <= 0:
        return cycle_offset + template.first_offset + (seq * time_step)
    return cycle_offset + template.first_offset + (template.duration * seq / (template.packets - 1))


def cycle_span(templates: list[FlowTemplate], time_step: float) -> float:
    max_end = 0.0
    for template in templates:
        if template.packets <= 1 or template.duration <= 0:
            end = template.first_offset + ((template.packets - 1) * time_step)
        else:
            end = template.first_offset + template.duration
        max_end = max(max_end, end)
    return max_end + time_step


def write_trace_and_collect(
    args: argparse.Namespace,
    templates: list[FlowTemplate],
    prefixes: list[tuple[int, int]],
) -> dict[str, Any]:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    context: dict[str, Any] = {
        "emitted_packets": 0,
        "dropped_template_packets": 0,
        "template_packets_total": sum(t.packets for t in templates),
        "templates_total": len(templates),
        "prefix_counts": {length: Counter() for length in args.prefix_lengths},
        "destination_counts": Counter(),
        "locality": LocalityStats(),
        "original_protocol_packets": Counter(),
        "simulator_protocol_packets": Counter(),
        "flow_records": {},
        "prefix_source_count": len(prefixes),
        "cycle_count_started": 0,
        "schedule_span_seconds": cycle_span(templates, args.time_step),
    }

    with output.open("w", newline="") as handle:
        writer = csv.writer(handle)
        if args.schedule == "time-merge":
            emit_time_merge(args, templates, prefixes, writer, handle, context)
        else:
            emit_flow_contiguous(args, templates, prefixes, writer, handle, context)
    context["locality"].finish_run()
    return context


def emit_time_merge(
    args: argparse.Namespace,
    templates: list[FlowTemplate],
    prefixes: list[tuple[int, int]],
    writer: csv.writer[Any],
    handle: Any,
    context: dict[str, Any],
) -> None:
    emitted = 0
    cycle_index = 0
    span = float(context["schedule_span_seconds"])
    while emitted < args.count:
        context["cycle_count_started"] += 1
        heap: list[tuple[float, int, int, int]] = []
        cycle_offset = cycle_index * span
        for template in templates:
            sim_proto = simulator_proto(template, args.other_proto_mode)
            if sim_proto is None:
                context["dropped_template_packets"] += template.packets
                continue
            first_time = packet_time(template, 0, cycle_offset, args.time_step)
            heapq.heappush(heap, (first_time, template.index, template.index, 0))
        if not heap:
            raise ValueError("all flow templates were dropped")

        while heap and emitted < args.count:
            timestamp, _order, template_index, seq = heapq.heappop(heap)
            template = templates[template_index]
            flow_id = (cycle_index * len(templates)) + template.index
            sim_proto = simulator_proto(template, args.other_proto_mode)
            if sim_proto is None:
                continue
            emit_packet(args, writer, handle, context, template, flow_id, prefixes, timestamp, sim_proto)
            emitted += 1

            next_seq = seq + 1
            if next_seq < template.packets:
                next_time = packet_time(template, next_seq, cycle_offset, args.time_step)
                heapq.heappush(heap, (next_time, template.index, template.index, next_seq))
        cycle_index += 1


def emit_flow_contiguous(
    args: argparse.Namespace,
    templates: list[FlowTemplate],
    prefixes: list[tuple[int, int]],
    writer: csv.writer[Any],
    handle: Any,
    context: dict[str, Any],
) -> None:
    emitted = 0
    cycle_index = 0
    timestamp = 0.0
    while emitted < args.count:
        context["cycle_count_started"] += 1
        for template in templates:
            sim_proto = simulator_proto(template, args.other_proto_mode)
            if sim_proto is None:
                context["dropped_template_packets"] += template.packets
                continue
            flow_id = (cycle_index * len(templates)) + template.index
            for _seq in range(template.packets):
                if emitted >= args.count:
                    return
                emit_packet(args, writer, handle, context, template, flow_id, prefixes, timestamp, sim_proto)
                emitted += 1
                timestamp += args.time_step
        cycle_index += 1


def emit_packet(
    args: argparse.Namespace,
    writer: csv.writer[Any],
    handle: Any,
    context: dict[str, Any],
    template: FlowTemplate,
    flow_id: int,
    prefixes: list[tuple[int, int]],
    timestamp: float,
    sim_proto: str,
) -> None:
    src = source_ip_for_flow(flow_id)
    dst = destination_for_flow(args, template, flow_id, prefixes)
    pkt_len = packet_len(template)
    src_port = template.src_port if template.protocol_number in (6, 17) else 0
    dst_port = template.dst_port if template.protocol_number in (6, 17) else 0
    if args.format == "dstip":
        handle.write(int_to_ipv4(dst) + "\n")
    else:
        writer.writerow(
            [
                f"{timestamp:.6f}",
                str(pkt_len),
                int_to_ipv4(src),
                int_to_ipv4(dst),
                sim_proto,
                str(src_port),
                str(dst_port),
            ]
        )

    context["emitted_packets"] += 1
    context["destination_counts"][dst] += 1
    context["locality"].add(dst)
    context["original_protocol_packets"][protocol_label(template.protocol_number, template.protocol)] += 1
    context["simulator_protocol_packets"][sim_proto] += 1
    for length in args.prefix_lengths:
        key = 0 if length == 0 else dst >> (32 - length)
        context["prefix_counts"][length][key] += 1

    records: dict[int, dict[str, Any]] = context["flow_records"]
    record = records.get(flow_id)
    if record is None:
        record = {
            "template_rank": template.rank,
            "protocol_number": template.protocol_number,
            "protocol": template.protocol,
            "simulator_protocol": sim_proto,
            "src_ip": int_to_ipv4(src),
            "dst_ip": int_to_ipv4(dst),
            "src_port": src_port,
            "dst_port": dst_port,
            "packets": 0,
            "bytes": 0,
            "first_seen": timestamp,
            "last_seen": timestamp,
        }
        records[flow_id] = record
    record["packets"] += 1
    record["bytes"] += packet_byte_count(template)
    record["last_seen"] = timestamp


def protocol_label(number: int, text: str) -> str:
    if number == 1:
        return "ICMP"
    if number == 6:
        return "TCP"
    if number == 17:
        return "UDP"
    return text or f"IP:{number}"


def concentration_row(length: int, counts: Counter[int], total: int) -> dict[str, object]:
    top_counts = sorted(counts.values(), reverse=True)
    row: dict[str, object] = {
        "prefix_length": length,
        "unique_prefixes": len(counts),
    }
    for top_n in TOP_NS:
        top_count = sum(top_counts[:top_n])
        row[f"top{top_n}_count"] = top_count
        row[f"top{top_n}_ratio"] = (top_count / total) if total else 0.0
    return row


def packet_bin(packets: int) -> tuple[int, int]:
    if packets <= 1:
        return 1, 1
    lower = 1 << (packets.bit_length() - 1)
    return lower, (lower << 1) - 1


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def percentile(sorted_values: list[int], q: float) -> int:
    if not sorted_values:
        return 0
    pos = int(round((len(sorted_values) - 1) * q))
    pos = max(0, min(pos, len(sorted_values) - 1))
    return sorted_values[pos]


def format_bin(lower: int, upper: int) -> str:
    if lower == upper:
        return f"{lower:,}"
    return f"{lower:,}-{upper:,}"


def write_report(
    args: argparse.Namespace,
    context: dict[str, Any],
) -> None:
    report_dir = Path(args.report_dir) if args.report_dir else Path(args.output).with_suffix("").parent / (
        Path(args.output).stem + "_report"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    total = int(context["emitted_packets"])
    prefix_counts: dict[int, Counter[int]] = context["prefix_counts"]
    destination_counts: Counter[int] = context["destination_counts"]
    locality: LocalityStats = context["locality"]
    flow_records: dict[int, dict[str, Any]] = context["flow_records"]
    flows = sorted(
        flow_records.values(),
        key=lambda row: (
            -int(row["packets"]),
            int(row["protocol_number"]),
            str(row["src_ip"]),
            str(row["dst_ip"]),
        ),
    )
    packets_values = sorted(int(row["packets"]) for row in flows)
    flow_count = len(flows)
    one_packet_flow_count = sum(1 for value in packets_values if value == 1)
    top1 = sum(int(row["packets"]) for row in flows[:1])
    top5 = sum(int(row["packets"]) for row in flows[:5])
    top10 = sum(int(row["packets"]) for row in flows[:10])
    top50 = sum(int(row["packets"]) for row in flows[:50])
    top100 = sum(int(row["packets"]) for row in flows[: args.top_n])

    bin_counts: dict[tuple[int, int], dict[str, int]] = {}
    for row in flows:
        lower, upper = packet_bin(int(row["packets"]))
        item = bin_counts.setdefault((lower, upper), {"flows": 0, "packets": 0, "bytes": 0})
        item["flows"] += 1
        item["packets"] += int(row["packets"])
        item["bytes"] += int(row["bytes"])

    bin_rows = []
    for lower, upper in sorted(bin_counts):
        item = bin_counts[(lower, upper)]
        bin_rows.append(
            {
                "packet_count_lower": lower,
                "packet_count_upper": upper,
                "flow_count": item["flows"],
                "flow_ratio": ratio(item["flows"], flow_count),
                "packet_sum": item["packets"],
                "packet_ratio": ratio(item["packets"], total),
                "byte_sum": item["bytes"],
                "byte_ratio": ratio(item["bytes"], sum(int(row["bytes"]) for row in flows)),
            }
        )

    for length, counts in prefix_counts.items():
        rows = counts.most_common()
        rows.sort(key=lambda kv: (-kv[1], kv[0]))
        with (report_dir / f"prefix_{length}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["rank", "prefix_length", "prefix", "count", "ratio"])
            for rank, (prefix_value, count) in enumerate(rows, start=1):
                writer.writerow(
                    [
                        rank,
                        length,
                        prefix_string(prefix_value, length),
                        count,
                        f"{ratio(count, total):.12f}",
                    ]
                )

    with (report_dir / "concentration.csv").open("w", newline="") as handle:
        fields = ["prefix_length", "unique_prefixes"]
        for top_n in TOP_NS:
            fields.extend([f"top{top_n}_count", f"top{top_n}_ratio"])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for length in sorted(prefix_counts):
            writer.writerow(concentration_row(length, prefix_counts[length], total))

    with (report_dir / "top_destinations.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rank", "destination", "count", "ratio"])
        for rank, (dst, count) in enumerate(destination_counts.most_common(args.top_n), start=1):
            writer.writerow([rank, int_to_ipv4(dst), count, f"{ratio(count, total):.12f}"])

    write_flow_outputs(report_dir, flows, bin_rows, context, total, flow_count, one_packet_flow_count)
    write_protocol_outputs(report_dir, context, total, flow_count)
    write_summary_outputs(
        report_dir,
        args,
        context,
        total,
        flow_count,
        one_packet_flow_count,
        top1,
        top5,
        top10,
        top50,
        top100,
        packets_values,
        bin_rows,
        generated_at,
    )


def write_flow_outputs(
    report_dir: Path,
    flows: list[dict[str, Any]],
    bin_rows: list[dict[str, Any]],
    context: dict[str, Any],
    total: int,
    flow_count: int,
    one_packet_flow_count: int,
) -> None:
    with (report_dir / "flow_lengths.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "template_rank",
                "protocol_number",
                "protocol",
                "simulator_protocol",
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
        for rank, row in enumerate(flows, start=1):
            writer.writerow(
                [
                    rank,
                    row["template_rank"],
                    row["protocol_number"],
                    row["protocol"],
                    row["simulator_protocol"],
                    row["src_ip"],
                    row["dst_ip"],
                    row["src_port"],
                    row["dst_port"],
                    row["packets"],
                    row["bytes"],
                    f"{(float(row['last_seen']) - float(row['first_seen'])):.12f}",
                    f"{float(row['first_seen']):.6f}",
                    f"{float(row['last_seen']):.6f}",
                ]
            )

    with (report_dir / "top_flows.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rank",
                "protocol_number",
                "protocol",
                "simulator_protocol",
                "src_ip",
                "dst_ip",
                "src_port",
                "dst_port",
                "packets",
                "packet_share",
            ]
        )
        for rank, row in enumerate(flows[:100], start=1):
            writer.writerow(
                [
                    rank,
                    row["protocol_number"],
                    row["protocol"],
                    row["simulator_protocol"],
                    row["src_ip"],
                    row["dst_ip"],
                    row["src_port"],
                    row["dst_port"],
                    row["packets"],
                    f"{ratio(int(row['packets']), total):.12f}",
                ]
            )

    with (report_dir / "flow_length_bins.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "packet_count_lower",
                "packet_count_upper",
                "flow_count",
                "flow_ratio",
                "packet_sum",
                "packet_ratio",
                "byte_sum",
                "byte_ratio",
            ],
        )
        writer.writeheader()
        for row in bin_rows:
            writer.writerow(row)

    with (report_dir / "flow_shape_summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerow(["emitted_packets", total])
        writer.writerow(["emitted_flows", flow_count])
        writer.writerow(["one_packet_flow_count", one_packet_flow_count])
        writer.writerow(["one_packet_flow_ratio", f"{ratio(one_packet_flow_count, flow_count):.12f}"])
        writer.writerow(["packets_per_flow", f"{ratio(total, flow_count):.6f}"])
        writer.writerow(["max_packets_per_flow", max((int(row["packets"]) for row in flows), default=0)])
        writer.writerow(["distinct_destinations", len(context["destination_counts"])])


def write_protocol_outputs(report_dir: Path, context: dict[str, Any], total: int, flow_count: int) -> None:
    flow_protocols = Counter(str(row["protocol"]) for row in context["flow_records"].values())
    sim_flow_protocols = Counter(str(row["simulator_protocol"]) for row in context["flow_records"].values())
    with (report_dir / "protocol_counts.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["protocol", "packet_count", "packet_ratio", "flow_count", "flow_ratio"])
        for proto, count in sorted(context["original_protocol_packets"].items(), key=lambda kv: (-kv[1], kv[0])):
            writer.writerow(
                [
                    proto,
                    count,
                    f"{ratio(count, total):.12f}",
                    flow_protocols.get(proto, 0),
                    f"{ratio(flow_protocols.get(proto, 0), flow_count):.12f}",
                ]
            )
    with (report_dir / "simulator_protocol_counts.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["simulator_protocol", "packet_count", "packet_ratio", "flow_count", "flow_ratio"])
        for proto, count in sorted(context["simulator_protocol_packets"].items(), key=lambda kv: (-kv[1], kv[0])):
            writer.writerow(
                [
                    proto,
                    count,
                    f"{ratio(count, total):.12f}",
                    sim_flow_protocols.get(proto, 0),
                    f"{ratio(sim_flow_protocols.get(proto, 0), flow_count):.12f}",
                ]
            )


def write_summary_outputs(
    report_dir: Path,
    args: argparse.Namespace,
    context: dict[str, Any],
    total: int,
    flow_count: int,
    one_packet_flow_count: int,
    top1: int,
    top5: int,
    top10: int,
    top50: int,
    top100: int,
    packets_values: list[int],
    bin_rows: list[dict[str, Any]],
    generated_at: str,
) -> None:
    locality: LocalityStats = context["locality"]
    ge8192 = sum_tail(bin_rows, 8192)
    ge1024 = sum_tail(bin_rows, 1024)
    summary_rows = [
        ("trace", args.output),
        ("format", args.format),
        ("synthetic_family", "equinix-flow-on-wide-rule"),
        ("flow_template", args.flow_lengths),
        ("rule_file", args.rule_file),
        ("schedule", args.schedule),
        ("dst_locality_mode", args.dst_locality_mode),
        (
            "template_prefix_length",
            args.template_prefix_length if args.dst_locality_mode == "template-prefix-map" else "",
        ),
        ("seed", args.seed),
        ("count", args.count),
        ("emitted_packets", total),
        ("emitted_flows", flow_count),
        ("template_flows_total", context["templates_total"]),
        ("template_packets_total", context["template_packets_total"]),
        ("cycle_count_started", context["cycle_count_started"]),
        ("prefix_source_count", context["prefix_source_count"]),
        ("other_proto_mode", args.other_proto_mode),
        ("dropped_template_packets", context["dropped_template_packets"]),
        ("prefix_lengths", ",".join(str(v) for v in args.prefix_lengths)),
        ("distinct_destinations", len(context["destination_counts"])),
        ("run_count", locality.run_count),
        ("max_run_length", locality.max_run),
        ("average_run_length", f"{locality.average_run():.6f}"),
        ("flows_per_million_packets", f"{ratio(flow_count * 1_000_000, total):.6f}"),
        ("packets_per_flow", f"{ratio(total, flow_count):.6f}"),
        ("one_packet_flow_count", one_packet_flow_count),
        ("one_packet_flow_ratio", f"{ratio(one_packet_flow_count, flow_count):.12f}"),
        ("single_packet_packet_share", f"{ratio(one_packet_flow_count, total):.12f}"),
        ("top1_flow_packet_count", top1),
        ("top1_flow_packet_share", f"{ratio(top1, total):.12f}"),
        ("top5_flow_packet_count", top5),
        ("top5_flow_packet_share", f"{ratio(top5, total):.12f}"),
        ("top10_flow_packet_count", top10),
        ("top10_flow_packet_share", f"{ratio(top10, total):.12f}"),
        ("top50_flow_packet_count", top50),
        ("top50_flow_packet_share", f"{ratio(top50, total):.12f}"),
        ("top100_flow_packet_count", top100),
        ("top100_flow_packet_share", f"{ratio(top100, total):.12f}"),
        ("p50_packets_per_flow", percentile(packets_values, 0.50)),
        ("p90_packets_per_flow", percentile(packets_values, 0.90)),
        ("p99_packets_per_flow", percentile(packets_values, 0.99)),
        ("max_packets_per_flow", packets_values[-1] if packets_values else 0),
        ("cutoff99_flow_count_bin", cutoff_bin(bin_rows, 0.99)),
        ("ge1024_flow_count", ge1024["flows"]),
        ("ge1024_packet_share", f"{ge1024['packet_ratio']:.12f}"),
        ("ge8192_flow_count", ge8192["flows"]),
        ("ge8192_packet_share", f"{ge8192['packet_ratio']:.12f}"),
    ]
    with (report_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerows(summary_rows)

    lines = [
        f"# Equinix Flow on WIDE Rule Trace: {Path(args.output).name}",
        "",
        f"Generated at `{generated_at}`.",
        "",
        "## Input",
        "",
        f"- flow template: `{args.flow_lengths}`",
        f"- rule file: `{args.rule_file}`",
        f"- output trace: `{args.output}`",
        f"- packets: `{total:,}`",
        f"- schedule: `{args.schedule}`",
        f"- dst locality mode: `{args.dst_locality_mode}`",
        f"- template prefix length: `{args.template_prefix_length if args.dst_locality_mode == 'template-prefix-map' else ''}`",
        f"- non-TCP/UDP handling: `{args.other_proto_mode}`",
        "",
        "## Flow Shape",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| emitted flows | {flow_count:,} |",
        f"| flows / 1M packets | {ratio(flow_count * 1_000_000, total):,.0f} |",
        f"| packets / flow | {ratio(total, flow_count):.2f} |",
        f"| one-packet flow ratio | {ratio(one_packet_flow_count, flow_count):.4f} |",
        f"| top100 packet share | {ratio(top100, total):.4f} |",
        f"| >=8192 packet share | {ge8192['packet_ratio']:.4f} |",
        f"| p99 packets/flow | {percentile(packets_values, 0.99)} |",
        "",
        "## Destination Locality",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| distinct destinations | {len(context['destination_counts']):,} |",
        f"| run count | {locality.run_count:,} |",
        f"| max run length | {locality.max_run:,} |",
        f"| average run length | {locality.average_run():.6f} |",
        "",
        "## Prefix Concentration",
        "",
        "| prefix length | unique prefixes | top1 | top5 | top10 | top50 | top100 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    prefix_counts: dict[int, Counter[int]] = context["prefix_counts"]
    for length in sorted(prefix_counts):
        row = concentration_row(length, prefix_counts[length], total)
        lines.append(
            "| "
            + " | ".join(
                [
                    str(length),
                    str(row["unique_prefixes"]),
                    f"{float(row['top1_ratio']):.4f}",
                    f"{float(row['top5_ratio']):.4f}",
                    f"{float(row['top10_ratio']):.4f}",
                    f"{float(row['top50_ratio']):.4f}",
                    f"{float(row['top100_ratio']):.4f}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Flow lengths come from Equinix Chicago 2014-03-20.",
            "- Destination IPs are generated inside prefixes listed in the WIDE rule file.",
            "- `template-prefix-map` preserves Equinix destination-prefix temporal locality by mapping original Equinix dst prefixes to stable WIDE prefixes.",
            "- The simulator currently keys `MinPacket` by protocol, source IP, destination IP; ports are present in CSV but not used by the cache path.",
            "- Original ICMP/ESP/other protocol counts are preserved in `protocol_counts.csv`; simulator CSV normalizes non-TCP/UDP according to `other_proto_mode`.",
            "",
            "## Files",
            "",
            "- `summary.csv`",
            "- `flow_lengths.csv`",
            "- `flow_length_bins.csv`",
            "- `protocol_counts.csv`",
            "- `simulator_protocol_counts.csv`",
            "- `concentration.csv`",
            "- `top_destinations.csv`",
        ]
    )
    for length in sorted(prefix_counts):
        lines.append(f"- `prefix_{length}.csv`")
    lines.extend(
        [
            "",
            "## Rerun",
            "",
            "```bash",
            "cd /home/yuzugon/osada-ppc-simulator",
            "python3 scripts/generate_equinix_flow_on_wide_trace.py \\",
            f"  --flow-lengths {args.flow_lengths} \\",
            f"  --rule-file {args.rule_file} \\",
            f"  --count {args.count} \\",
            f"  --output {args.output} \\",
            f"  --report-dir {report_dir}",
            "```",
            "",
        ]
    )
    (report_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def sum_tail(bin_rows: list[dict[str, Any]], threshold: int) -> dict[str, float]:
    flows = 0
    flow_ratio = 0.0
    packets = 0
    packet_ratio = 0.0
    for row in bin_rows:
        if int(row["packet_count_lower"]) >= threshold:
            flows += int(row["flow_count"])
            flow_ratio += float(row["flow_ratio"])
            packets += int(row["packet_sum"])
            packet_ratio += float(row["packet_ratio"])
    return {"flows": flows, "flow_ratio": flow_ratio, "packets": packets, "packet_ratio": packet_ratio}


def cutoff_bin(bin_rows: list[dict[str, Any]], threshold: float) -> str:
    cumulative = 0.0
    for row in bin_rows:
        cumulative += float(row["flow_ratio"])
        if cumulative >= threshold:
            return format_bin(int(row["packet_count_lower"]), int(row["packet_count_upper"]))
    if not bin_rows:
        return ""
    row = bin_rows[-1]
    return format_bin(int(row["packet_count_lower"]), int(row["packet_count_upper"]))


def main() -> None:
    args = parse_args()
    templates = load_templates(Path(args.flow_lengths))
    prefixes = parse_rule_prefixes(Path(args.rule_file))
    context = write_trace_and_collect(args, templates, prefixes)
    write_report(args, context)


if __name__ == "__main__":
    main()
