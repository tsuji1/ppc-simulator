#!/usr/bin/env python3
"""Generate flow-ablation simulator CSV traces from a pcap.

The simulator CSV format is headerless:

time,len,srcIP,dstIP,proto,srcPort,dstPort

This tool keeps only TCP/UDP packets because the simulator's MinPacket path
turns only TCP/UDP into FiveTuple entries. Flow analysis for ranking uses a
directional IPv4 5-tuple.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import random
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable


DEFAULT_VARIANTS = (
    "baseline",
    "remove-top1",
    "remove-top10",
    "remove-top100",
    "cap8192",
    "cap1024",
    "shuffle-global",
    "shuffle-window",
)


@dataclass(frozen=True)
class PacketRecord:
    seq: int
    timestamp: float
    length: int
    proto: str
    proto_num: int
    src_ip: int
    dst_ip: int
    src_port: int
    dst_port: int

    @property
    def flow_key(self) -> tuple[int, int, int, int, int]:
        return (self.proto_num, self.src_ip, self.dst_ip, self.src_port, self.dst_port)


@dataclass(frozen=True)
class FlowInfo:
    flow_id: int
    rank: int
    key: tuple[int, int, int, int, int]
    packets: int
    first_seq: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create baseline/remove-top/cap/shuffle TCP+UDP simulator CSV traces from pcap."
    )
    parser.add_argument("--trace", required=True, help="Input pcap path.")
    parser.add_argument("--label", default="", help="Trace label used for output filenames.")
    parser.add_argument("--output-dir", required=True, help="Output directory.")
    parser.add_argument(
        "--max-packets",
        type=int,
        default=100_000,
        help="Number of TCP/UDP packets to load from the source window. 0 means all.",
    )
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help=f"Comma-separated variants. Defaults to {','.join(DEFAULT_VARIANTS)}.",
    )
    parser.add_argument("--cap-values", default="8192,1024", help="Comma-separated capN values to support.")
    parser.add_argument("--remove-top-values", default="1,10,100", help="Comma-separated remove-topN values.")
    parser.add_argument("--shuffle-window-size", type=int, default=1000, help="Packets per shuffle-window chunk.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--time-step", type=float, default=0.000001)
    parser.add_argument("--progress-interval", type=int, default=1_000_000)
    args = parser.parse_args()
    if args.max_packets < 0:
        parser.error("--max-packets must be >= 0")
    if args.shuffle_window_size <= 0:
        parser.error("--shuffle-window-size must be > 0")
    if args.time_step <= 0:
        parser.error("--time-step must be > 0")
    args.variants = parse_csv_items(args.variants)
    args.cap_values = parse_int_items(args.cap_values)
    args.remove_top_values = parse_int_items(args.remove_top_values)
    validate_variants(args)
    if not args.label:
        args.label = Path(args.trace).stem
    return args


def parse_csv_items(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_int_items(raw: str) -> list[int]:
    values = []
    for item in parse_csv_items(raw):
        value = int(item)
        if value <= 0:
            raise argparse.ArgumentTypeError("values must be positive")
        values.append(value)
    return values


def validate_variants(args: argparse.Namespace) -> None:
    allowed = {"baseline", "shuffle-global", "shuffle-window"}
    allowed.update(f"remove-top{value}" for value in args.remove_top_values)
    allowed.update(f"cap{value}" for value in args.cap_values)
    unknown = sorted(set(args.variants) - allowed)
    if unknown:
        raise SystemExit(f"unknown variants: {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}")


def int_to_ipv4(value: int) -> str:
    return str(ipaddress.IPv4Address(value & 0xFFFFFFFF))


def packet_bin(value: int) -> tuple[int, int]:
    if value <= 1:
        return (1, 1)
    lower = 1 << (value.bit_length() - 1)
    upper = (lower << 1) - 1
    return (lower, upper)


def format_bin(value: int) -> str:
    lower, upper = packet_bin(value)
    if lower == upper:
        return str(lower)
    return f"{lower:,}-{upper:,}"


def ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else float(numerator) / float(denominator)


def read_pcap_packets(path: Path, max_packets: int, progress_interval: int) -> list[PacketRecord]:
    records: list[PacketRecord] = []
    total_frames = 0
    with path.open("rb") as handle:
        endian, time_scale, linktype = read_pcap_global_header(handle)
        packet_header = endian + "IIII"
        packet_header_size = struct.calcsize(packet_header)
        while True:
            raw_header = handle.read(packet_header_size)
            if not raw_header:
                break
            if len(raw_header) != packet_header_size:
                raise ValueError("truncated pcap packet header")
            ts_sec, ts_frac, incl_len, _orig_len = struct.unpack(packet_header, raw_header)
            payload = handle.read(incl_len)
            if len(payload) != incl_len:
                raise ValueError("truncated pcap packet payload")
            total_frames += 1
            parsed = parse_ipv4_tcp_udp(payload, linktype)
            if parsed is not None:
                proto, proto_num, src, dst, src_port, dst_port, length = parsed
                records.append(
                    PacketRecord(
                        seq=len(records),
                        timestamp=float(ts_sec) + (float(ts_frac) / time_scale),
                        length=length,
                        proto=proto,
                        proto_num=proto_num,
                        src_ip=src,
                        dst_ip=dst,
                        src_port=src_port,
                        dst_port=dst_port,
                    )
                )
                if max_packets and len(records) >= max_packets:
                    break
            if progress_interval and total_frames % progress_interval == 0:
                print(
                    f"read {total_frames:,} pcap frames; kept {len(records):,} TCP/UDP packets",
                    file=sys.stderr,
                )
    if not records:
        raise ValueError(f"no TCP/UDP IPv4 packets found in {path}")
    return records


def read_pcap_global_header(handle: BinaryIO) -> tuple[str, float, int]:
    header = handle.read(24)
    if len(header) != 24:
        raise ValueError("pcap global header is too short")
    magic = header[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian, time_scale = "<", 1_000_000.0
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian, time_scale = ">", 1_000_000.0
    elif magic == b"\x4d\x3c\xb2\xa1":
        endian, time_scale = "<", 1_000_000_000.0
    elif magic == b"\xa1\xb2\x3c\x4d":
        endian, time_scale = ">", 1_000_000_000.0
    else:
        raise ValueError(f"unsupported pcap magic: {magic.hex()}")
    linktype = struct.unpack(endian + "I", header[20:24])[0]
    return endian, time_scale, linktype


def parse_ipv4_tcp_udp(payload: bytes, linktype: int) -> tuple[str, int, int, int, int, int, int] | None:
    offset = ipv4_offset(payload, linktype)
    if offset is None or len(payload) < offset + 20:
        return None
    first = payload[offset]
    if first >> 4 != 4:
        return None
    ihl = (first & 0x0F) * 4
    if ihl < 20 or len(payload) < offset + ihl:
        return None
    total_length = struct.unpack("!H", payload[offset + 2 : offset + 4])[0]
    protocol = payload[offset + 9]
    flags_fragment = struct.unpack("!H", payload[offset + 6 : offset + 8])[0]
    fragment_offset = flags_fragment & 0x1FFF
    if fragment_offset != 0:
        return None
    if protocol not in (6, 17):
        return None
    transport = offset + ihl
    if len(payload) < transport + 4:
        return None
    src_port, dst_port = struct.unpack("!HH", payload[transport : transport + 4])
    src = struct.unpack("!I", payload[offset + 12 : offset + 16])[0]
    dst = struct.unpack("!I", payload[offset + 16 : offset + 20])[0]
    proto = "tcp" if protocol == 6 else "udp"
    length = total_length if total_length > 0 else max(0, len(payload) - offset)
    return proto, protocol, src, dst, src_port, dst_port, length


def ipv4_offset(payload: bytes, linktype: int) -> int | None:
    # DLT_RAW
    if linktype in (101, 228):
        return 0
    # Ethernet
    if linktype == 1:
        if len(payload) < 14:
            return None
        offset = 14
        ether_type = struct.unpack("!H", payload[12:14])[0]
        while ether_type in (0x8100, 0x88A8, 0x9100):
            if len(payload) < offset + 4:
                return None
            ether_type = struct.unpack("!H", payload[offset + 2 : offset + 4])[0]
            offset += 4
        if ether_type != 0x0800:
            return None
        return offset
    # Linux cooked capture v1
    if linktype == 113:
        if len(payload) < 16:
            return None
        protocol = struct.unpack("!H", payload[14:16])[0]
        return 16 if protocol == 0x0800 else None
    return 0 if payload and payload[0] >> 4 == 4 else None


def build_flow_info(records: list[PacketRecord]) -> dict[tuple[int, int, int, int, int], FlowInfo]:
    counts: Counter[tuple[int, int, int, int, int]] = Counter(record.flow_key for record in records)
    first_seq: dict[tuple[int, int, int, int, int], int] = {}
    for record in records:
        first_seq.setdefault(record.flow_key, record.seq)
    sorted_flows = sorted(counts, key=lambda key: (-counts[key], first_seq[key], key))
    return {
        key: FlowInfo(flow_id=index + 1, rank=index + 1, key=key, packets=counts[key], first_seq=first_seq[key])
        for index, key in enumerate(sorted_flows)
    }


def top_flow_keys(flow_info: dict[tuple[int, int, int, int, int], FlowInfo], n: int) -> set[tuple[int, int, int, int, int]]:
    return {info.key for info in sorted(flow_info.values(), key=lambda item: item.rank)[:n]}


def materialize_variant(
    variant: str,
    records: list[PacketRecord],
    flow_info: dict[tuple[int, int, int, int, int], FlowInfo],
    args: argparse.Namespace,
) -> list[PacketRecord]:
    if variant == "baseline":
        return list(records)
    if variant.startswith("remove-top"):
        n = int(variant.removeprefix("remove-top"))
        remove = top_flow_keys(flow_info, n)
        return [record for record in records if record.flow_key not in remove]
    if variant.startswith("cap"):
        cap = int(variant.removeprefix("cap"))
        seen: Counter[tuple[int, int, int, int, int]] = Counter()
        out: list[PacketRecord] = []
        for record in records:
            seen[record.flow_key] += 1
            if seen[record.flow_key] <= cap:
                out.append(record)
        return out
    if variant == "shuffle-global":
        out = list(records)
        random.Random(args.seed).shuffle(out)
        return out
    if variant == "shuffle-window":
        rng = random.Random(args.seed)
        out = []
        for start in range(0, len(records), args.shuffle_window_size):
            chunk = list(records[start : start + args.shuffle_window_size])
            rng.shuffle(chunk)
            out.extend(chunk)
        return out
    raise ValueError(f"unsupported variant: {variant}")


def write_outputs(records: list[PacketRecord], flow_info: dict[tuple[int, int, int, int, int], FlowInfo], args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    trace_dir = output_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    packet_map_path = output_dir / "packet_flow_map.csv"
    with packet_map_path.open("w", newline="") as map_handle:
        map_writer = csv.writer(map_handle)
        map_writer.writerow(
            [
                "variant",
                "row_index",
                "source_seq",
                "flow_id",
                "flow_rank",
                "variant_flow_packets",
                "baseline_flow_packets",
                "variant_flow_bin",
                "baseline_flow_bin",
                "proto",
                "src_ip",
                "src_port",
                "dst_ip",
                "dst_port",
            ]
        )
        for variant in args.variants:
            variant_records = materialize_variant(variant, records, flow_info, args)
            variant_counts: Counter[tuple[int, int, int, int, int]] = Counter(record.flow_key for record in variant_records)
            trace_path = trace_dir / f"{args.label}__{variant}.csv"
            write_trace_csv(trace_path, variant_records, args.time_step)
            for index, record in enumerate(variant_records):
                info = flow_info[record.flow_key]
                variant_packets = variant_counts[record.flow_key]
                map_writer.writerow(
                    [
                        variant,
                        index,
                        record.seq,
                        info.flow_id,
                        info.rank,
                        variant_packets,
                        info.packets,
                        format_bin(variant_packets),
                        format_bin(info.packets),
                        record.proto,
                        int_to_ipv4(record.src_ip),
                        record.src_port,
                        int_to_ipv4(record.dst_ip),
                        record.dst_port,
                    ]
                )
            summary = summarize_variant(variant, trace_path, variant_records, flow_info)
            summary_rows.append(summary)
    write_variant_summary(output_dir / "variant_summary.csv", summary_rows)
    write_top_flows(output_dir / "top_tcpudp_flows.csv", flow_info)
    write_report(output_dir / "README.md", args, len(records), summary_rows)


def write_trace_csv(path: Path, records: list[PacketRecord], time_step: float) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        for index, record in enumerate(records):
            writer.writerow(
                [
                    f"{index * time_step:.9f}",
                    record.length,
                    int_to_ipv4(record.src_ip),
                    int_to_ipv4(record.dst_ip),
                    record.proto,
                    record.src_port,
                    record.dst_port,
                ]
            )


def summarize_variant(
    variant: str,
    trace_path: Path,
    records: list[PacketRecord],
    baseline_flow_info: dict[tuple[int, int, int, int, int], FlowInfo],
) -> dict[str, object]:
    counts: Counter[tuple[int, int, int, int, int]] = Counter(record.flow_key for record in records)
    packet_count = len(records)
    flow_lengths = sorted(counts.values(), reverse=True)
    top = lambda n: sum(flow_lengths[:n])
    ge8192_flow_count = sum(1 for value in flow_lengths if value >= 8192)
    ge8192_packet_count = sum(value for value in flow_lengths if value >= 8192)
    ge1024_flow_count = sum(1 for value in flow_lengths if value >= 1024)
    ge1024_packet_count = sum(value for value in flow_lengths if value >= 1024)
    one_packet_flows = sum(1 for value in flow_lengths if value == 1)
    max_flow_packets = flow_lengths[0] if flow_lengths else 0
    top_original_rank = ""
    if records:
        variant_top_key = max(counts, key=lambda key: (counts[key], -baseline_flow_info[key].rank))
        top_original_rank = baseline_flow_info[variant_top_key].rank
    return {
        "variant": variant,
        "trace": str(trace_path),
        "packets": packet_count,
        "flows": len(flow_lengths),
        "packets_per_flow": ratio(packet_count, len(flow_lengths)),
        "one_packet_flow_ratio": ratio(one_packet_flows, len(flow_lengths)),
        "top1_packet_share": ratio(top(1), packet_count),
        "top10_packet_share": ratio(top(10), packet_count),
        "top100_packet_share": ratio(top(100), packet_count),
        "ge1024_flow_count": ge1024_flow_count,
        "ge1024_packet_share": ratio(ge1024_packet_count, packet_count),
        "ge8192_flow_count": ge8192_flow_count,
        "ge8192_packet_share": ratio(ge8192_packet_count, packet_count),
        "max_flow_packets": max_flow_packets,
        "max_bin": format_bin(max_flow_packets) if max_flow_packets else "",
        "top_flow_original_rank": top_original_rank,
    }


def write_variant_summary(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "variant",
        "trace",
        "packets",
        "flows",
        "packets_per_flow",
        "one_packet_flow_ratio",
        "top1_packet_share",
        "top10_packet_share",
        "top100_packet_share",
        "ge1024_flow_count",
        "ge1024_packet_share",
        "ge8192_flow_count",
        "ge8192_packet_share",
        "max_flow_packets",
        "max_bin",
        "top_flow_original_rank",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_top_flows(path: Path, flow_info: dict[tuple[int, int, int, int, int], FlowInfo]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rank", "flow_id", "proto", "src_ip", "src_port", "dst_ip", "dst_port", "packets", "baseline_bin"])
        for info in sorted(flow_info.values(), key=lambda item: item.rank):
            proto_num, src, dst, src_port, dst_port = info.key
            proto = "tcp" if proto_num == 6 else "udp" if proto_num == 17 else f"ip:{proto_num}"
            writer.writerow(
                [
                    info.rank,
                    info.flow_id,
                    proto,
                    int_to_ipv4(src),
                    src_port,
                    int_to_ipv4(dst),
                    dst_port,
                    info.packets,
                    format_bin(info.packets),
                ]
            )


def write_report(path: Path, args: argparse.Namespace, source_packets: int, rows: list[dict[str, object]]) -> None:
    lines = [
        f"# Flow ablation trace variants: {args.label}",
        "",
        "## Input",
        "",
        f"- trace: `{args.trace}`",
        f"- loaded TCP/UDP packets: `{source_packets:,}`",
        "- simulator CSV keeps TCP/UDP only, matching the simulator MinPacket path.",
        "- flow ranking uses directional IPv4 5-tuple: protocol, src IP, dst IP, src port, dst port.",
        "",
        "## Variants",
        "",
        "| variant | packets | flows | top100 packet share | 8192+ packet share | max bin |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {variant} | {packets:,} | {flows:,} | {top100:.2%} | {ge8192:.2%} | {max_bin} |".format(
                variant=row["variant"],
                packets=int(row["packets"]),
                flows=int(row["flows"]),
                top100=float(row["top100_packet_share"]),
                ge8192=float(row["ge8192_packet_share"]),
                max_bin=row["max_bin"],
            )
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `traces/*.csv`: headerless simulator CSV traces.",
            "- `variant_summary.csv`: per-variant flow distribution summary.",
            "- `top_tcpudp_flows.csv`: baseline top TCP/UDP flows used by remove-top variants.",
            "- `packet_flow_map.csv`: row-to-flow-bin mapping for hit/miss attribution.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    records = read_pcap_packets(Path(args.trace), args.max_packets, args.progress_interval)
    flow_info = build_flow_info(records)
    write_outputs(records, flow_info, args)
    print(f"wrote flow ablation variants to {args.output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
