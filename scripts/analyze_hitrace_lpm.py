#!/usr/bin/env python3
"""Aggregate cache hit/miss trace lines by routing-rule LPM prefix length.

Input hit trace format is the simulator's record-cache-hit output:

    hit 203.0.113.1
    miss 198.51.100.9

The script computes the longest matching prefix length for each destination IP
using a rule file in the simulator's whitespace-separated format:

    prefix_ip prefix_len next_hop
"""

from __future__ import annotations

import argparse
import bisect
import csv
import sys
from array import array
from collections import Counter
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Group record-cache-hit output by routing-rule LPM prefix length."
    )
    parser.add_argument("--rulefile", required=True, help="Rule file used by the simulator.")
    parser.add_argument("--hit-trace", required=True, help="cachehitrace/*.txt or copied hit trace.")
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/hitrace_lpm",
        help="Directory for CSV and Markdown outputs.",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Output filename label. Defaults to hit trace stem.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=1_000_000,
        help="Print progress every N hit trace rows; 0 disables progress.",
    )
    return parser.parse_args()


def parse_ipv4_u32(text: str) -> int:
    parts = text.strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"invalid IPv4 address: {text!r}")
    value = 0
    for part in parts:
        octet = int(part)
        if octet < 0 or octet > 255:
            raise ValueError(f"invalid IPv4 address: {text!r}")
        value = (value << 8) | octet
    return value


def mask_for(prefix_len: int) -> int:
    if prefix_len == 0:
        return 0
    return (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF


MASKS = [mask_for(length) for length in range(33)]


def load_rule_prefixes(path: Path) -> list[array]:
    """Return sorted unique network integers grouped by prefix length."""
    by_len = [array("I") for _ in range(33)]
    with path.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 2:
                raise SystemExit(f"{path}:{line_number}: expected at least 2 fields")
            prefix_len = int(fields[1])
            if prefix_len < 0 or prefix_len > 32:
                raise SystemExit(f"{path}:{line_number}: prefix length out of range: {prefix_len}")
            ip = parse_ipv4_u32(fields[0])
            by_len[prefix_len].append(ip & MASKS[prefix_len])

    unique_by_len = [array("I") for _ in range(33)]
    for prefix_len, values in enumerate(by_len):
        if not values:
            continue
        previous = None
        for value in sorted(values):
            if previous is None or value != previous:
                unique_by_len[prefix_len].append(value)
                previous = value
    return unique_by_len


def lpm_prefix_len(ip: int, prefixes_by_len: list[array], cache: dict[int, int]) -> int:
    cached = cache.get(ip)
    if cached is not None:
        return cached
    for prefix_len in range(32, -1, -1):
        prefixes = prefixes_by_len[prefix_len]
        if not prefixes:
            continue
        network = ip & MASKS[prefix_len]
        idx = bisect.bisect_left(prefixes, network)
        if idx < len(prefixes) and prefixes[idx] == network:
            cache[ip] = prefix_len
            return prefix_len
    cache[ip] = -1
    return -1


def analyze_hit_trace(path: Path, prefixes_by_len: list[array], progress_interval: int) -> tuple[Counter, Counter]:
    hits: Counter[int] = Counter()
    misses: Counter[int] = Counter()
    cache: dict[int, int] = {}
    with path.open() as handle:
        for row_number, line in enumerate(handle, start=1):
            fields = line.split()
            if not fields:
                continue
            if len(fields) < 2:
                raise SystemExit(f"{path}:{row_number}: expected '<hit|miss> <dst_ip>'")
            state = fields[0].lower()
            if state not in {"hit", "miss"}:
                raise SystemExit(f"{path}:{row_number}: unknown state: {fields[0]!r}")
            ip = parse_ipv4_u32(fields[1])
            prefix_len = lpm_prefix_len(ip, prefixes_by_len, cache)
            if state == "hit":
                hits[prefix_len] += 1
            else:
                misses[prefix_len] += 1
            if progress_interval and row_number % progress_interval == 0:
                print(
                    f"processed {row_number:,} rows; unique dst IPs {len(cache):,}",
                    file=sys.stderr,
                )
    return hits, misses


def ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else float(numerator) / float(denominator)


def output_rows(hits: Counter[int], misses: Counter[int]) -> list[dict[str, object]]:
    total_hits = sum(hits.values())
    total_misses = sum(misses.values())
    total_packets = total_hits + total_misses
    rows = []
    for prefix_len in range(-1, 33):
        hit_count = hits[prefix_len]
        miss_count = misses[prefix_len]
        packets = hit_count + miss_count
        if packets == 0:
            continue
        rows.append(
            {
                "lpm_prefix_len": prefix_len,
                "packets": packets,
                "hits": hit_count,
                "misses": miss_count,
                "hit_rate": ratio(hit_count, packets),
                "packet_share": ratio(packets, total_packets),
                "hit_share": ratio(hit_count, total_hits),
                "miss_share": ratio(miss_count, total_misses),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def write_summary(path: Path, label: str, rows: list[dict[str, object]], hit_trace: Path, rulefile: Path) -> None:
    total_packets = sum(int(row["packets"]) for row in rows)
    total_hits = sum(int(row["hits"]) for row in rows)
    total_misses = sum(int(row["misses"]) for row in rows)
    top_hit_rows = sorted(rows, key=lambda row: int(row["hits"]), reverse=True)[:12]
    top_packet_rows = sorted(rows, key=lambda row: int(row["packets"]), reverse=True)[:12]

    lines = [
        f"# Hitrace LPM analysis: {label}",
        "",
        f"- hit_trace: `{hit_trace}`",
        f"- rulefile: `{rulefile}`",
        f"- packets: `{total_packets:,}`",
        f"- hits: `{total_hits:,}`",
        f"- misses: `{total_misses:,}`",
        f"- hit_rate: `{ratio(total_hits, total_packets) * 100:.4f}%`",
        "",
        "## Top hit LPM lengths",
        "",
        "| LPM length | hits | hit share | packets | hit rate |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in top_hit_rows:
        lines.append(
            "| /{lpm} | {hits:,} | {hit_share:.2%} | {packets:,} | {hit_rate:.2%} |".format(
                lpm=int(row["lpm_prefix_len"]),
                hits=int(row["hits"]),
                hit_share=float(row["hit_share"]),
                packets=int(row["packets"]),
                hit_rate=float(row["hit_rate"]),
            )
        )

    lines.extend(
        [
            "",
            "## Top packet LPM lengths",
            "",
            "| LPM length | packets | packet share | hits | misses | hit rate |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in top_packet_rows:
        lines.append(
            "| /{lpm} | {packets:,} | {packet_share:.2%} | {hits:,} | {misses:,} | {hit_rate:.2%} |".format(
                lpm=int(row["lpm_prefix_len"]),
                packets=int(row["packets"]),
                packet_share=float(row["packet_share"]),
                hits=int(row["hits"]),
                misses=int(row["misses"]),
                hit_rate=float(row["hit_rate"]),
            )
        )

    path.write_text("\n".join(lines) + "\n")


def safe_label(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)


def main() -> int:
    args = parse_args()
    rulefile = Path(args.rulefile)
    hit_trace = Path(args.hit_trace)
    if not rulefile.exists():
        raise SystemExit(f"rulefile not found: {rulefile}")
    if not hit_trace.exists():
        raise SystemExit(f"hit trace not found: {hit_trace}")

    label = safe_label(args.label or hit_trace.stem)
    output_dir = Path(args.output_dir)
    print(f"loading rule prefixes from {rulefile}", file=sys.stderr)
    prefixes_by_len = load_rule_prefixes(rulefile)
    prefix_count = sum(len(values) for values in prefixes_by_len)
    print(f"loaded {prefix_count:,} unique prefixes", file=sys.stderr)

    hits, misses = analyze_hit_trace(hit_trace, prefixes_by_len, args.progress_interval)
    rows = output_rows(hits, misses)
    csv_path = output_dir / f"{label}_lpm_by_hit_state.csv"
    md_path = output_dir / f"{label}_lpm_report.md"
    write_csv(csv_path, rows)
    write_summary(md_path, label, rows, hit_trace, rulefile)
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
