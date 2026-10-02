#!/usr/bin/env python3
"""Generate Poptrie-style synthetic IPv4 destination traces.

The simulator accepts 7-column CSV-like traces:
time,len,srcIP,dstIP,proto,srcPort,dstPort

This script emits that format by default and writes side-car distribution
reports that are compatible with the existing dst_prefix_distribution reports.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


TOP_NS = (1, 5, 10, 50, 100)


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
        description="Generate random, sequential, repeated, or prefix-based synthetic IPv4 destination traces."
    )
    parser.add_argument("--pattern", choices=("random", "sequential", "repeated", "prefix"), required=True)
    parser.add_argument("--count", type=int, required=True, help="Number of packets/rows to emit.")
    parser.add_argument("--output", required=True, help="Output trace path.")
    parser.add_argument("--format", choices=("simulator-csv", "dstip"), default="simulator-csv")
    parser.add_argument("--seed", type=lambda v: int(v, 0), default=1)
    parser.add_argument("--repeat", type=int, default=16, help="Repeat count for repeated pattern.")
    parser.add_argument("--start", default="0.0.0.0", help="Start IPv4 address for sequential pattern.")
    parser.add_argument("--rule-file", default="", help="Rule file used by the prefix pattern.")
    parser.add_argument(
        "--prefix-host-mode",
        choices=("xorshift", "network", "first"),
        default="xorshift",
        help="How to fill host bits for the prefix pattern.",
    )
    parser.add_argument("--src-ip", default="192.0.2.1")
    parser.add_argument("--proto", choices=("tcp", "udp"), default="tcp")
    parser.add_argument("--packet-len", type=int, default=64)
    parser.add_argument("--src-port", type=int, default=12345)
    parser.add_argument("--dst-port", type=int, default=80)
    parser.add_argument("--time-step", type=float, default=0.000001)
    parser.add_argument("--prefix-lengths", default="8,16,18,24,32")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument(
        "--report-dir",
        default="",
        help="Directory for summary.csv, concentration.csv, prefix_*.csv, and summary.md.",
    )
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    if args.count < 0:
        parser.error("--count must be non-negative")
    if args.count == 0:
        parser.error("--count must be positive")
    if args.seed == 0 and args.pattern in ("random", "repeated"):
        parser.error("--seed must be non-zero for xorshift32")
    if args.pattern == "prefix" and not args.rule_file:
        parser.error("--rule-file is required for --pattern prefix")
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    if args.packet_len <= 0:
        parser.error("--packet-len must be positive")
    if args.src_port < 0 or args.src_port > 65535 or args.dst_port < 0 or args.dst_port > 65535:
        parser.error("ports must be in 0..65535")
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


def ipv4_to_int(value: str) -> int:
    return int(ipaddress.IPv4Address(value))


def int_to_ipv4(value: int) -> str:
    return str(ipaddress.IPv4Address(value & 0xFFFFFFFF))


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


def host_bits_for_prefix(args: argparse.Namespace, network: int, prefix_length: int, sequence: int) -> int:
    host_width = 32 - prefix_length
    if host_width <= 0:
        return 0
    host_mask = (1 << host_width) - 1
    if args.prefix_host_mode == "network":
        return 0
    if args.prefix_host_mode == "first":
        return 1 & host_mask
    state = (args.seed ^ network ^ (prefix_length << 24) ^ ((sequence + 1) * 0x9E3779B9)) & 0xFFFFFFFF
    if state == 0:
        state = 1
    return xorshift32(state) & host_mask


def iter_prefix_destinations(args: argparse.Namespace) -> Iterable[int]:
    prefixes = parse_rule_prefixes(Path(args.rule_file))
    args.prefix_source_count = len(prefixes)
    for index in range(args.count):
        if args.count <= len(prefixes):
            prefix_index = (index * len(prefixes)) // args.count
        else:
            prefix_index = index % len(prefixes)
        network, prefix_length = prefixes[prefix_index]
        host = host_bits_for_prefix(args, network, prefix_length, index)
        yield (network | host) & 0xFFFFFFFF


def iter_destinations(args: argparse.Namespace) -> Iterable[int]:
    if args.pattern == "prefix":
        yield from iter_prefix_destinations(args)
        return

    if args.pattern == "sequential":
        start = ipv4_to_int(args.start)
        for i in range(args.count):
            yield (start + i) & 0xFFFFFFFF
        return

    state = args.seed & 0xFFFFFFFF
    emitted = 0
    while emitted < args.count:
        state = xorshift32(state)
        if args.pattern == "random":
            yield state
            emitted += 1
            continue
        for _ in range(min(args.repeat, args.count - emitted)):
            yield state
            emitted += 1


def write_trace_and_collect(args: argparse.Namespace) -> tuple[dict[int, Counter[int]], Counter[int], LocalityStats]:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    prefix_counts = {length: Counter() for length in args.prefix_lengths}
    destination_counts: Counter[int] = Counter()
    locality = LocalityStats()

    with output.open("w", newline="") as handle:
        writer = csv.writer(handle)
        for index, dst in enumerate(iter_destinations(args)):
            if args.format == "dstip":
                handle.write(int_to_ipv4(dst) + "\n")
            else:
                writer.writerow(
                    [
                        f"{index * args.time_step:.6f}",
                        str(args.packet_len),
                        args.src_ip,
                        int_to_ipv4(dst),
                        args.proto,
                        str(args.src_port),
                        str(args.dst_port),
                    ]
                )
            destination_counts[dst] += 1
            locality.add(dst)
            for length in args.prefix_lengths:
                key = 0 if length == 0 else dst >> (32 - length)
                prefix_counts[length][key] += 1
    locality.finish_run()
    return prefix_counts, destination_counts, locality


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


def write_report(
    args: argparse.Namespace,
    prefix_counts: dict[int, Counter[int]],
    destination_counts: Counter[int],
    locality: LocalityStats,
) -> None:
    report_dir = Path(args.report_dir) if args.report_dir else Path(args.output).with_suffix("").parent / (Path(args.output).stem + "_report")
    report_dir.mkdir(parents=True, exist_ok=True)
    total = args.count
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

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
                        f"{(count / total) if total else 0.0:.12f}",
                    ]
                )

    with (report_dir / "concentration.csv").open("w", newline="") as handle:
        fields = ["prefix_length", "unique_prefixes"]
        for top_n in TOP_NS:
            fields.extend([f"top{top_n}_count", f"top{top_n}_ratio"])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for length in sorted(prefix_counts):
            row = concentration_row(length, prefix_counts[length], total)
            writer.writerow(row)

    with (report_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerow(["trace", args.output])
        writer.writerow(["format", args.format])
        writer.writerow(["pattern", args.pattern])
        writer.writerow(["seed", args.seed])
        writer.writerow(["count", args.count])
        writer.writerow(["repeat", args.repeat if args.pattern == "repeated" else ""])
        writer.writerow(["start", args.start if args.pattern == "sequential" else ""])
        writer.writerow(["rule_file", args.rule_file if args.pattern == "prefix" else ""])
        writer.writerow(["prefix_host_mode", args.prefix_host_mode if args.pattern == "prefix" else ""])
        writer.writerow(["prefix_source_count", getattr(args, "prefix_source_count", "")])
        writer.writerow(["prefix_lengths", ",".join(str(v) for v in args.prefix_lengths)])
        writer.writerow(["distinct_destinations", len(destination_counts)])
        writer.writerow(["run_count", locality.run_count])
        writer.writerow(["max_run_length", locality.max_run])
        writer.writerow(["average_run_length", f"{locality.average_run():.6f}"])

    top_dst = destination_counts.most_common(args.top_n)
    with (report_dir / "top_destinations.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rank", "destination", "count", "ratio"])
        for rank, (dst, count) in enumerate(top_dst, start=1):
            writer.writerow([rank, int_to_ipv4(dst), count, f"{(count / total) if total else 0.0:.12f}"])

    input_lines = [
        f"# Poptrie synthetic trace: {Path(args.output).name}",
        "",
        f"Generated at `{generated_at}`.",
        "",
        "## Input",
        "",
        f"- trace: `{args.output}`",
        f"- pattern: `{args.pattern}`",
        f"- format: `{args.format}`",
        f"- count: `{args.count}`",
        f"- seed: `{args.seed}`",
    ]
    if args.pattern == "prefix":
        input_lines.extend(
            [
                f"- rule file: `{args.rule_file}`",
                f"- prefix host mode: `{args.prefix_host_mode}`",
                f"- prefix source count: `{getattr(args, 'prefix_source_count', '')}`",
            ]
        )
    input_lines.extend(
        [
            f"- prefix lengths: `{','.join(str(v) for v in args.prefix_lengths)}`",
            "",
            "## Locality",
            "",
            "| metric | value |",
            "| --- | ---: |",
            f"| distinct destinations | {len(destination_counts)} |",
            f"| run count | {locality.run_count} |",
            f"| max run length | {locality.max_run} |",
            f"| average run length | {locality.average_run():.6f} |",
            "",
            "## Concentration",
            "",
            "| prefix length | unique prefixes | top1 | top5 | top10 | top50 | top100 |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines = input_lines
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
            "## Files",
            "",
            "- `summary.csv`",
            "- `concentration.csv`",
            "- `top_destinations.csv`",
        ]
    )
    for length in sorted(prefix_counts):
        lines.append(f"- `prefix_{length}.csv`")
    rerun_lines = [
        "",
        "## Rerun",
        "",
        "```bash",
        "python3 scripts/generate_poptrie_synthetic_trace.py \\",
        f"  --pattern {args.pattern} \\",
        f"  --seed {args.seed} \\",
        f"  --count {args.count} \\",
    ]
    if args.pattern == "prefix":
        rerun_lines.append(f"  --rule-file {args.rule_file} \\")
    rerun_lines.extend(
        [
            f"  --output {args.output} \\",
            f"  --report-dir {report_dir}",
            "```",
            "",
        ]
    )
    lines.extend(rerun_lines)
    (report_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    prefix_counts, destination_counts, locality = write_trace_and_collect(args)
    if not args.no_report:
        write_report(args, prefix_counts, destination_counts, locality)


if __name__ == "__main__":
    main()
