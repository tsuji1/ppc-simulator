#!/usr/bin/env python3
"""Join top flow destinations with PREFIX18 cacheline hot spots.

This is a lightweight check for whether anonymized destination buckets are not
just dense in the rule table, but also land on cache sets with observed second
misses. It uses existing top-flow reports, so it is a representative check over
the top 100 flows rather than a full-packet PCAP scan.
"""

from __future__ import annotations

import argparse
import csv
import struct
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = ROOT_DIR.parent
DEFAULT_RULE = ROOT_DIR / "scripts" / "reports" / "flow_hit_ablation" / "wide-2026-03-27-100k" / "rib.20260327.0600.unique.rule"
DEFAULT_BUCKET_SUMMARY = ROOT_DIR / "scripts" / "reports" / "wide_rule_prefix18_specificity_20260327" / "wide_rule_prefix18_bucket_summary.csv"
DEFAULT_CACHELINE_BY_SET = (
    WORKSPACE_DIR
    / "ppc-result-viewer"
    / "scripts"
    / "reports"
    / "unified_miss_anon_vs_non"
    / "cacheline_prefix18_cap2048"
    / "prefix18_cap2048_cacheline_by_set.csv"
)
DEFAULT_OUTPUT_DIR = ROOT_DIR / "scripts" / "reports" / "anon_flow_destination_hotspots_20260327"

TRACE_REPORTS = (
    (
        "2026-03",
        "anon",
        ROOT_DIR / "scripts" / "reports" / "flow_stats_wide_same_date" / "2026-03-27-anon" / "top_flows.csv",
    ),
    (
        "2026-03",
        "non",
        ROOT_DIR / "scripts" / "reports" / "flow_stats_wide_same_date" / "2026-03-27-nonanon" / "top_flows.csv",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule", default=str(DEFAULT_RULE))
    parser.add_argument("--bucket-summary", default=str(DEFAULT_BUCKET_SUMMARY))
    parser.add_argument("--cacheline-by-set", default=str(DEFAULT_CACHELINE_BY_SET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def ip_to_int(text: str) -> int:
    value = 0
    for part in text.split("."):
        value = (value << 8) | int(part)
    return value


def int_to_ip(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def network_mask(prefix_len: int) -> int:
    if prefix_len == 0:
        return 0
    return (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF


def prefix18_bucket(ip_text: str) -> int:
    return ip_to_int(ip_text) >> 14


def prefix18_cidr_from_bucket(bucket: int) -> str:
    return f"{int_to_ip(bucket << 14)}/18"


def prefix18_set_idx(ip_text: str, set_count: int = 256) -> int:
    prefix_value = prefix18_bucket(ip_text)
    return (zlib.crc32(struct.pack(">I", prefix_value)) & 0xFFFFFFFF) % set_count


def load_rule_prefixes(path: Path) -> list[set[int]]:
    prefixes = [set() for _ in range(33)]
    with path.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            prefix_len = int(parts[1])
            network = ip_to_int(parts[0]) & network_mask(prefix_len)
            prefixes[prefix_len].add(network)
    return prefixes


def longest_prefix(prefixes: list[set[int]], ip_text: str) -> tuple[str, int]:
    ip_value = ip_to_int(ip_text)
    for prefix_len in range(32, -1, -1):
        network = ip_value & network_mask(prefix_len)
        if network in prefixes[prefix_len]:
            return f"{int_to_ip(network)}/{prefix_len}", prefix_len
    return "0.0.0.0/0", 0


def read_dict_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_dict_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_bucket_summary(path: Path) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    for row in read_dict_csv(path):
        rows[int(row["bucket"])] = row
    return rows


def load_cacheline_rows(path: Path) -> dict[tuple[str, str, int], dict[str, str]]:
    rows: dict[tuple[str, str, int], dict[str, str]] = {}
    for row in read_dict_csv(path):
        rows[(row["pair_month"], row["privacy"], int(row["set_idx"]))] = row
    return rows


def analyze_flows(
    *,
    pair_month: str,
    privacy: str,
    flow_path: Path,
    prefixes: list[set[int]],
    buckets: dict[int, dict[str, str]],
    cachelines: dict[tuple[str, str, int], dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flow_rows: list[dict[str, Any]] = []
    by_set: dict[int, dict[str, Any]] = {}

    for row in read_dict_csv(flow_path):
        packets = int(row["packets"])
        dst_ip = row["dst_ip"]
        set_idx = prefix18_set_idx(dst_ip)
        bucket = prefix18_bucket(dst_ip)
        bucket_row = buckets[bucket]
        lpm_prefix, lpm_len = longest_prefix(prefixes, dst_ip)
        cacheline = cachelines.get((pair_month, privacy, set_idx), {})
        flow_record = {
            "pair_month": pair_month,
            "privacy": privacy,
            "flow_rank": row["rank"],
            "dst_ip": dst_ip,
            "packets": packets,
            "prefix18": prefix18_cidr_from_bucket(bucket),
            "set_idx": set_idx,
            "lpm_prefix": lpm_prefix,
            "lpm_len": lpm_len,
            "rule_unique_gt18_count": bucket_row["unique_gt18_count"],
            "rule_unique_19_24_count": bucket_row["unique_19_24_count"],
            "rule_best_le18_len": bucket_row["unique_best_le18_len"],
            "cacheline_second_miss": cacheline.get("cacheline_second_miss", "0"),
            "cacheline_est_hitrate_percent": cacheline.get("cacheline_est_hitrate_percent", ""),
            "cacheline_dominant_second_prefix_len": cacheline.get("dominant_second_prefix_len", ""),
            "cacheline_l22_24_second_share_percent": cacheline.get("second_miss_l22_24_share_percent", ""),
        }
        flow_rows.append(flow_record)

        set_record = by_set.setdefault(
            set_idx,
            {
                "pair_month": pair_month,
                "privacy": privacy,
                "set_idx": set_idx,
                "top100_dst_packets": 0,
                "top100_flow_count": 0,
                "top100_lpm_prefixes": set(),
                "top100_prefix18_buckets": defaultdict(int),
                "top100_dst_ips": defaultdict(int),
            },
        )
        set_record["top100_dst_packets"] += packets
        set_record["top100_flow_count"] += 1
        set_record["top100_lpm_prefixes"].add(lpm_prefix)
        set_record["top100_prefix18_buckets"][prefix18_cidr_from_bucket(bucket)] += packets
        set_record["top100_dst_ips"][dst_ip] += packets

    set_rows: list[dict[str, Any]] = []
    for set_idx, row in by_set.items():
        cacheline = cachelines.get((pair_month, privacy, set_idx), {})
        top_bucket, top_bucket_packets = max(row["top100_prefix18_buckets"].items(), key=lambda item: item[1])
        top_ip, top_ip_packets = max(row["top100_dst_ips"].items(), key=lambda item: item[1])
        bucket_id = ip_to_int(top_bucket.split("/")[0]) >> 14
        bucket_row = buckets[bucket_id]
        set_rows.append(
            {
                "pair_month": pair_month,
                "privacy": privacy,
                "set_idx": set_idx,
                "top100_dst_packets": row["top100_dst_packets"],
                "top100_flow_count": row["top100_flow_count"],
                "top100_active_lpm_prefix_count": len(row["top100_lpm_prefixes"]),
                "top_prefix18": top_bucket,
                "top_prefix18_packets": top_bucket_packets,
                "top_dst_ip": top_ip,
                "top_dst_ip_packets": top_ip_packets,
                "rule_unique_gt18_count_for_top_prefix18": bucket_row["unique_gt18_count"],
                "rule_unique_19_24_count_for_top_prefix18": bucket_row["unique_19_24_count"],
                "rule_best_le18_len_for_top_prefix18": bucket_row["unique_best_le18_len"],
                "cacheline_second_miss": cacheline.get("cacheline_second_miss", "0"),
                "cacheline_est_hitrate_percent": cacheline.get("cacheline_est_hitrate_percent", ""),
                "cacheline_dominant_second_prefix_len": cacheline.get("dominant_second_prefix_len", ""),
                "cacheline_l22_24_second_share_percent": cacheline.get("second_miss_l22_24_share_percent", ""),
                "top_lpm_prefixes": ";".join(sorted(row["top100_lpm_prefixes"])),
            }
        )

    set_rows.sort(key=lambda row: int(row["top100_dst_packets"]), reverse=True)
    return flow_rows, set_rows


def write_report(path: Path, set_rows: list[dict[str, Any]]) -> None:
    anon_rows = [row for row in set_rows if row["privacy"] == "anon"]
    non_rows = [row for row in set_rows if row["privacy"] == "non"]
    anon_by_second = sorted(anon_rows, key=lambda row: int(row["cacheline_second_miss"] or 0), reverse=True)
    anon_by_packets = sorted(anon_rows, key=lambda row: int(row["top100_dst_packets"]), reverse=True)
    non_by_second = sorted(non_rows, key=lambda row: int(row["cacheline_second_miss"] or 0), reverse=True)

    lines = [
        "# 2026-03 anon destination hotspot check",
        "",
        "This report joins top-100 flow destinations with PREFIX18 cacheline counters.",
        "It is not a full-packet PCAP scan; it checks whether representative heavy transformed destinations land on observed miss-hotspot sets.",
        "",
        "## Anon: cacheline hot sets that also appear in top flows",
        "",
        "| set | top100 dst packets | active LPM prefixes | top /18 | rule >18 | second miss | est hitrate | dominant L | L22-24 share | top LPM prefixes |",
        "|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in anon_by_second[:8]:
        if int(row["top100_dst_packets"]) == 0 and int(row["cacheline_second_miss"] or 0) == 0:
            continue
        lines.append(
            f"| {row['set_idx']} | {row['top100_dst_packets']} | {row['top100_active_lpm_prefix_count']} | "
            f"{row['top_prefix18']} | {row['rule_unique_gt18_count_for_top_prefix18']} | "
            f"{row['cacheline_second_miss']} | {row['cacheline_est_hitrate_percent']} | "
            f"{row['cacheline_dominant_second_prefix_len']} | {row['cacheline_l22_24_second_share_percent']} | "
            f"{row['top_lpm_prefixes']} |"
        )

    lines.extend(
        [
            "",
            "## Anon: heavy top-flow destination sets",
            "",
            "| set | top100 dst packets | top /18 | rule >18 | second miss | dominant L | top LPM prefixes |",
            "|---:|---:|---|---:|---:|---:|---|",
        ]
    )
    for row in anon_by_packets[:10]:
        lines.append(
            f"| {row['set_idx']} | {row['top100_dst_packets']} | {row['top_prefix18']} | "
            f"{row['rule_unique_gt18_count_for_top_prefix18']} | {row['cacheline_second_miss']} | "
            f"{row['cacheline_dominant_second_prefix_len']} | {row['top_lpm_prefixes']} |"
        )

    lines.extend(
        [
            "",
            "## Non-anon: cacheline hot sets in top flows",
            "",
            "| set | top100 dst packets | active LPM prefixes | top /18 | rule >18 | second miss | est hitrate | dominant L | top LPM prefixes |",
            "|---:|---:|---:|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in non_by_second[:8]:
        lines.append(
            f"| {row['set_idx']} | {row['top100_dst_packets']} | {row['top100_active_lpm_prefix_count']} | "
            f"{row['top_prefix18']} | {row['rule_unique_gt18_count_for_top_prefix18']} | "
            f"{row['cacheline_second_miss']} | {row['cacheline_est_hitrate_percent']} | "
            f"{row['cacheline_dominant_second_prefix_len']} | {row['top_lpm_prefixes']} |"
        )

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    prefixes = load_rule_prefixes(Path(args.rule))
    buckets = load_bucket_summary(Path(args.bucket_summary))
    cachelines = load_cacheline_rows(Path(args.cacheline_by_set))

    all_flow_rows: list[dict[str, Any]] = []
    all_set_rows: list[dict[str, Any]] = []
    for pair_month, privacy, flow_path in TRACE_REPORTS:
        flow_rows, set_rows = analyze_flows(
            pair_month=pair_month,
            privacy=privacy,
            flow_path=flow_path,
            prefixes=prefixes,
            buckets=buckets,
            cachelines=cachelines,
        )
        all_flow_rows.extend(flow_rows)
        all_set_rows.extend(set_rows)

    write_dict_csv(
        output_dir / "top_flow_destination_prefix18_rows.csv",
        all_flow_rows,
        [
            "pair_month",
            "privacy",
            "flow_rank",
            "dst_ip",
            "packets",
            "prefix18",
            "set_idx",
            "lpm_prefix",
            "lpm_len",
            "rule_unique_gt18_count",
            "rule_unique_19_24_count",
            "rule_best_le18_len",
            "cacheline_second_miss",
            "cacheline_est_hitrate_percent",
            "cacheline_dominant_second_prefix_len",
            "cacheline_l22_24_second_share_percent",
        ],
    )
    write_dict_csv(
        output_dir / "top_flow_destination_set_summary.csv",
        all_set_rows,
        [
            "pair_month",
            "privacy",
            "set_idx",
            "top100_dst_packets",
            "top100_flow_count",
            "top100_active_lpm_prefix_count",
            "top_prefix18",
            "top_prefix18_packets",
            "top_dst_ip",
            "top_dst_ip_packets",
            "rule_unique_gt18_count_for_top_prefix18",
            "rule_unique_19_24_count_for_top_prefix18",
            "rule_best_le18_len_for_top_prefix18",
            "cacheline_second_miss",
            "cacheline_est_hitrate_percent",
            "cacheline_dominant_second_prefix_len",
            "cacheline_l22_24_second_share_percent",
            "top_lpm_prefixes",
        ],
    )
    write_report(output_dir / "REPORT.md", all_set_rows)
    print(f"wrote {output_dir / 'top_flow_destination_prefix18_rows.csv'}")
    print(f"wrote {output_dir / 'top_flow_destination_set_summary.csv'}")
    print(f"wrote {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
