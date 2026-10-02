#!/usr/bin/env python3
"""Summarize WIDE rule specificity inside /18 buckets.

The cache issue under PREFIX18 is about how many route prefixes fall into the
same top-18-bit bucket. This script counts, for every IPv4 /18 bucket, whether
the WIDE rule table has routes finer than /18 and how dense those buckets are.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Iterable


BUCKET_BITS = 18
HOST_BITS_IN_BUCKET = 32 - BUCKET_BITS
BUCKET_COUNT = 1 << BUCKET_BITS
DEFAULT_THRESHOLDS = (1, 2, 4, 8, 16, 32, 64, 128, 256)


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RULE = ROOT_DIR / "rules" / "wide.rib.20240625.1400.unique.rule"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "scripts" / "reports" / "wide_rule_prefix18_specificity"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule", default=str(DEFAULT_RULE), help="Rule file: '<IPv4> <prefix_len> <id>'.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--top-n", type=int, default=50)
    return parser.parse_args()


def ip_to_int(text: str) -> int:
    parts = text.split(".")
    if len(parts) != 4:
        raise ValueError(f"invalid IPv4 address: {text}")
    value = 0
    for part in parts:
        octet = int(part)
        if not 0 <= octet <= 255:
            raise ValueError(f"invalid IPv4 address: {text}")
        value = (value << 8) | octet
    return value


def int_to_ip(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def network_mask(prefix_len: int) -> int:
    if prefix_len == 0:
        return 0
    return (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF


def bucket_to_cidr(bucket: int) -> str:
    return f"{int_to_ip(bucket << HOST_BITS_IN_BUCKET)}/18"


def percent(part: int, whole: int) -> str:
    if whole == 0:
        return "0.0000"
    return f"{part / whole * 100:.4f}"


class BucketCounters:
    def __init__(self) -> None:
        self.le18_count = [0] * BUCKET_COUNT
        self.gt18_count = [0] * BUCKET_COUNT
        self.ge18_count = [0] * BUCKET_COUNT
        self.count_19_24 = [0] * BUCKET_COUNT
        self.count_gt24 = [0] * BUCKET_COUNT
        self.count_24 = [0] * BUCKET_COUNT
        self.max_gt18_len = [0] * BUCKET_COUNT
        self.best_le18_len = [-1] * BUCKET_COUNT

    def add(self, network_int: int, prefix_len: int) -> None:
        if prefix_len <= BUCKET_BITS:
            start_bucket = network_int >> HOST_BITS_IN_BUCKET
            bucket_span = 1 << (BUCKET_BITS - prefix_len)
            for bucket in range(start_bucket, start_bucket + bucket_span):
                self.le18_count[bucket] += 1
                if prefix_len >= BUCKET_BITS:
                    self.ge18_count[bucket] += 1
                if prefix_len > self.best_le18_len[bucket]:
                    self.best_le18_len[bucket] = prefix_len
            return

        bucket = network_int >> HOST_BITS_IN_BUCKET
        self.gt18_count[bucket] += 1
        self.ge18_count[bucket] += 1
        if 19 <= prefix_len <= 24:
            self.count_19_24[bucket] += 1
        if prefix_len > 24:
            self.count_gt24[bucket] += 1
        if prefix_len == 24:
            self.count_24[bucket] += 1
        if prefix_len > self.max_gt18_len[bucket]:
            self.max_gt18_len[bucket] = prefix_len


def add_summary_row(rows: list[dict[str, str]], metric: str, value: int | str, denominator: int | None = None) -> None:
    row = {"metric": metric, "value": str(value), "denominator": "", "percent": ""}
    if denominator is not None:
        row["denominator"] = str(denominator)
        row["percent"] = percent(int(value), denominator)
    rows.append(row)


def threshold_rows(label: str, values: list[int], thresholds: Iterable[int], denominator: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for threshold in thresholds:
        count = sum(1 for value in values if value >= threshold)
        rows.append(
            {
                "metric": f"buckets_with_{label}_ge_{threshold}",
                "value": str(count),
                "denominator": str(denominator),
                "percent": percent(count, denominator),
            }
        )
    return rows


def build_summary(
    rule_path: Path,
    entry: BucketCounters,
    unique: BucketCounters,
    total_lines: int,
    parsed_lines: int,
    unique_prefixes: int,
    entry_len_counts: Counter[int],
    unique_len_counts: Counter[int],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    add_summary_row(rows, "rule_file", str(rule_path))
    add_summary_row(rows, "total_lines", total_lines)
    add_summary_row(rows, "parsed_route_entries", parsed_lines)
    add_summary_row(rows, "unique_prefixes", unique_prefixes)
    add_summary_row(rows, "prefix18_buckets_total", BUCKET_COUNT)

    for label, counters in (("entry", entry), ("unique", unique)):
        has_le18 = [count > 0 for count in counters.le18_count]
        has_gt18 = [count > 0 for count in counters.gt18_count]
        has_ge18 = [count > 0 for count in counters.ge18_count]
        has_19_24 = [count > 0 for count in counters.count_19_24]
        has_gt24 = [count > 0 for count in counters.count_gt24]
        has_24 = [count > 0 for count in counters.count_24]

        add_summary_row(rows, f"{label}_buckets_with_le18_cover", sum(has_le18), BUCKET_COUNT)
        add_summary_row(rows, f"{label}_buckets_with_ge18_route", sum(has_ge18), BUCKET_COUNT)
        add_summary_row(rows, f"{label}_buckets_with_gt18_more_specific", sum(has_gt18), BUCKET_COUNT)
        add_summary_row(rows, f"{label}_buckets_without_gt18_more_specific", BUCKET_COUNT - sum(has_gt18), BUCKET_COUNT)
        add_summary_row(rows, f"{label}_buckets_with_19_24_more_specific", sum(has_19_24), BUCKET_COUNT)
        add_summary_row(rows, f"{label}_buckets_with_gt24_more_specific", sum(has_gt24), BUCKET_COUNT)
        add_summary_row(rows, f"{label}_buckets_with_24_route", sum(has_24), BUCKET_COUNT)
        add_summary_row(
            rows,
            f"{label}_le18_covered_buckets_with_gt18_more_specific",
            sum(1 for le18, gt18 in zip(has_le18, has_gt18) if le18 and gt18),
            sum(has_le18),
        )
        add_summary_row(
            rows,
            f"{label}_le18_covered_buckets_without_gt18_more_specific",
            sum(1 for le18, gt18 in zip(has_le18, has_gt18) if le18 and not gt18),
            sum(has_le18),
        )

        rows.extend(threshold_rows(f"{label}_gt18_more_specific_count", counters.gt18_count, DEFAULT_THRESHOLDS, BUCKET_COUNT))
        rows.extend(threshold_rows(f"{label}_19_24_more_specific_count", counters.count_19_24, DEFAULT_THRESHOLDS, BUCKET_COUNT))

    for prefix_len in range(33):
        add_summary_row(rows, f"entry_prefix_len_{prefix_len}", entry_len_counts[prefix_len])
        add_summary_row(rows, f"unique_prefix_len_{prefix_len}", unique_len_counts[prefix_len])

    best_counter = Counter(unique.best_le18_len)
    for best_len in range(-1, 19):
        label = "none" if best_len == -1 else str(best_len)
        add_summary_row(rows, f"unique_buckets_best_le18_len_{label}", best_counter[best_len], BUCKET_COUNT)

    return rows


def build_bucket_rows(entry: BucketCounters, unique: BucketCounters) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for bucket in range(BUCKET_COUNT):
        rows.append(
            {
                "bucket": str(bucket),
                "prefix18": bucket_to_cidr(bucket),
                "unique_best_le18_len": str(unique.best_le18_len[bucket]),
                "unique_le18_count": str(unique.le18_count[bucket]),
                "unique_ge18_count": str(unique.ge18_count[bucket]),
                "unique_gt18_count": str(unique.gt18_count[bucket]),
                "unique_19_24_count": str(unique.count_19_24[bucket]),
                "unique_gt24_count": str(unique.count_gt24[bucket]),
                "unique_24_count": str(unique.count_24[bucket]),
                "unique_max_gt18_len": str(unique.max_gt18_len[bucket]),
                "entry_le18_count": str(entry.le18_count[bucket]),
                "entry_ge18_count": str(entry.ge18_count[bucket]),
                "entry_gt18_count": str(entry.gt18_count[bucket]),
                "entry_19_24_count": str(entry.count_19_24[bucket]),
                "entry_gt24_count": str(entry.count_gt24[bucket]),
                "entry_24_count": str(entry.count_24[bucket]),
                "entry_max_gt18_len": str(entry.max_gt18_len[bucket]),
            }
        )
    return rows


def top_bucket_rows(entry: BucketCounters, unique: BucketCounters, top_n: int) -> list[dict[str, str]]:
    ordered = sorted(range(BUCKET_COUNT), key=lambda bucket: (unique.gt18_count[bucket], entry.gt18_count[bucket]), reverse=True)
    rows: list[dict[str, str]] = []
    for rank, bucket in enumerate(ordered[:top_n], start=1):
        rows.append(
            {
                "rank": str(rank),
                "prefix18": bucket_to_cidr(bucket),
                "unique_best_le18_len": str(unique.best_le18_len[bucket]),
                "unique_gt18_count": str(unique.gt18_count[bucket]),
                "unique_19_24_count": str(unique.count_19_24[bucket]),
                "unique_gt24_count": str(unique.count_gt24[bucket]),
                "unique_24_count": str(unique.count_24[bucket]),
                "unique_max_gt18_len": str(unique.max_gt18_len[bucket]),
                "entry_gt18_count": str(entry.gt18_count[bucket]),
                "entry_19_24_count": str(entry.count_19_24[bucket]),
                "entry_gt24_count": str(entry.count_gt24[bucket]),
                "entry_24_count": str(entry.count_24[bucket]),
            }
        )
    return rows


def best_le18_cross_rows(entry: BucketCounters, unique: BucketCounters) -> list[dict[str, str]]:
    buckets_by_best: dict[int, list[int]] = {best_len: [] for best_len in range(-1, 19)}
    for bucket, best_len in enumerate(unique.best_le18_len):
        buckets_by_best[best_len].append(bucket)

    rows: list[dict[str, str]] = []
    for best_len in range(-1, 19):
        buckets = buckets_by_best[best_len]
        total = len(buckets)
        if total == 0:
            continue
        unique_with_gt18 = sum(1 for bucket in buckets if unique.gt18_count[bucket] > 0)
        unique_with_19_24 = sum(1 for bucket in buckets if unique.count_19_24[bucket] > 0)
        unique_gt18_ge8 = sum(1 for bucket in buckets if unique.gt18_count[bucket] >= 8)
        unique_gt18_ge16 = sum(1 for bucket in buckets if unique.gt18_count[bucket] >= 16)
        entry_gt18_ge8 = sum(1 for bucket in buckets if entry.gt18_count[bucket] >= 8)
        entry_gt18_ge16 = sum(1 for bucket in buckets if entry.gt18_count[bucket] >= 16)
        rows.append(
            {
                "best_le18_len": "none" if best_len == -1 else str(best_len),
                "total_buckets": str(total),
                "unique_with_gt18": str(unique_with_gt18),
                "unique_with_gt18_percent": percent(unique_with_gt18, total),
                "unique_with_19_24": str(unique_with_19_24),
                "unique_with_19_24_percent": percent(unique_with_19_24, total),
                "unique_gt18_count_ge8": str(unique_gt18_ge8),
                "unique_gt18_count_ge8_percent": percent(unique_gt18_ge8, total),
                "unique_gt18_count_ge16": str(unique_gt18_ge16),
                "unique_gt18_count_ge16_percent": percent(unique_gt18_ge16, total),
                "entry_gt18_count_ge8": str(entry_gt18_ge8),
                "entry_gt18_count_ge8_percent": percent(entry_gt18_ge8, total),
                "entry_gt18_count_ge16": str(entry_gt18_ge16),
                "entry_gt18_count_ge16_percent": percent(entry_gt18_ge16, total),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    summary_rows: list[dict[str, str]],
    top_rows: list[dict[str, str]],
    cross_rows: list[dict[str, str]],
) -> None:
    summary = {row["metric"]: row for row in summary_rows}

    def value(metric: str) -> str:
        return summary.get(metric, {}).get("value", "")

    def pct(metric: str) -> str:
        row = summary.get(metric, {})
        if not row.get("percent"):
            return ""
        return f"{row['percent']}%"

    lines = [
        "# WIDE Rule /18 Specificity Summary",
        "",
        f"- rule: `{value('rule_file')}`",
        f"- parsed route entries: {value('parsed_route_entries')}",
        f"- unique prefixes: {value('unique_prefixes')}",
        f"- /18 buckets: {value('prefix18_buckets_total')}",
        "",
        "## Key Counts",
        "",
        "| metric | buckets | share |",
        "|---|---:|---:|",
        f"| unique buckets with routes finer than /18 | {value('unique_buckets_with_gt18_more_specific')} | {pct('unique_buckets_with_gt18_more_specific')} |",
        f"| unique buckets without routes finer than /18 | {value('unique_buckets_without_gt18_more_specific')} | {pct('unique_buckets_without_gt18_more_specific')} |",
        f"| unique buckets with /19-/24 routes | {value('unique_buckets_with_19_24_more_specific')} | {pct('unique_buckets_with_19_24_more_specific')} |",
        f"| unique buckets with >=8 routes finer than /18 | {value('buckets_with_unique_gt18_more_specific_count_ge_8')} | {pct('buckets_with_unique_gt18_more_specific_count_ge_8')} |",
        f"| unique buckets with >=16 routes finer than /18 | {value('buckets_with_unique_gt18_more_specific_count_ge_16')} | {pct('buckets_with_unique_gt18_more_specific_count_ge_16')} |",
        f"| entry buckets with >=8 rule entries finer than /18 | {value('buckets_with_entry_gt18_more_specific_count_ge_8')} | {pct('buckets_with_entry_gt18_more_specific_count_ge_8')} |",
        f"| entry buckets with >=16 rule entries finer than /18 | {value('buckets_with_entry_gt18_more_specific_count_ge_16')} | {pct('buckets_with_entry_gt18_more_specific_count_ge_16')} |",
        "",
        "## Best <=18 Cover Cross-Tab",
        "",
        "| best <=18 cover | buckets | unique /19-/24 buckets | share | unique >=8 finer routes | share |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in cross_rows:
        if row["best_le18_len"] not in {"16", "17", "18"}:
            continue
        lines.append(
            f"| /{row['best_le18_len']} | {row['total_buckets']} | {row['unique_with_19_24']} | "
            f"{row['unique_with_19_24_percent']}% | {row['unique_gt18_count_ge8']} | "
            f"{row['unique_gt18_count_ge8_percent']}% |"
        )
    lines.extend(
        [
            "",
        "## Densest /18 Buckets By Unique More-Specific Prefix Count",
        "",
        "| rank | /18 bucket | unique >18 | unique /19-/24 | entry >18 | max len |",
        "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in top_rows[:20]:
        lines.append(
            f"| {row['rank']} | {row['prefix18']} | {row['unique_gt18_count']} | "
            f"{row['unique_19_24_count']} | {row['entry_gt18_count']} | {row['unique_max_gt18_len']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    rule_path = Path(args.rule)
    output_dir = Path(args.output_dir)

    entry = BucketCounters()
    unique = BucketCounters()
    seen_prefixes: set[tuple[int, int]] = set()
    entry_len_counts: Counter[int] = Counter()
    unique_len_counts: Counter[int] = Counter()
    total_lines = 0
    parsed_lines = 0

    with rule_path.open() as handle:
        for total_lines, line in enumerate(handle, start=1):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            ip_text = parts[0]
            prefix_len = int(parts[1])
            if not 0 <= prefix_len <= 32:
                raise ValueError(f"invalid prefix length on line {total_lines}: {prefix_len}")
            network_int = ip_to_int(ip_text) & network_mask(prefix_len)

            parsed_lines += 1
            entry_len_counts[prefix_len] += 1
            entry.add(network_int, prefix_len)

            prefix_key = (network_int, prefix_len)
            if prefix_key not in seen_prefixes:
                seen_prefixes.add(prefix_key)
                unique_len_counts[prefix_len] += 1
                unique.add(network_int, prefix_len)

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = build_summary(
        rule_path=rule_path,
        entry=entry,
        unique=unique,
        total_lines=total_lines,
        parsed_lines=parsed_lines,
        unique_prefixes=len(seen_prefixes),
        entry_len_counts=entry_len_counts,
        unique_len_counts=unique_len_counts,
    )
    bucket_rows = build_bucket_rows(entry, unique)
    top_rows = top_bucket_rows(entry, unique, args.top_n)
    cross_rows = best_le18_cross_rows(entry, unique)

    write_csv(output_dir / "wide_rule_prefix18_overall_summary.csv", summary_rows, ["metric", "value", "denominator", "percent"])
    write_csv(
        output_dir / "wide_rule_prefix18_bucket_summary.csv",
        bucket_rows,
        [
            "bucket",
            "prefix18",
            "unique_best_le18_len",
            "unique_le18_count",
            "unique_ge18_count",
            "unique_gt18_count",
            "unique_19_24_count",
            "unique_gt24_count",
            "unique_24_count",
            "unique_max_gt18_len",
            "entry_le18_count",
            "entry_ge18_count",
            "entry_gt18_count",
            "entry_19_24_count",
            "entry_gt24_count",
            "entry_24_count",
            "entry_max_gt18_len",
        ],
    )
    write_csv(
        output_dir / "wide_rule_prefix18_top_buckets.csv",
        top_rows,
        [
            "rank",
            "prefix18",
            "unique_best_le18_len",
            "unique_gt18_count",
            "unique_19_24_count",
            "unique_gt24_count",
            "unique_24_count",
            "unique_max_gt18_len",
            "entry_gt18_count",
            "entry_19_24_count",
            "entry_gt24_count",
            "entry_24_count",
        ],
    )
    write_csv(
        output_dir / "wide_rule_prefix18_best_le18_cross.csv",
        cross_rows,
        [
            "best_le18_len",
            "total_buckets",
            "unique_with_gt18",
            "unique_with_gt18_percent",
            "unique_with_19_24",
            "unique_with_19_24_percent",
            "unique_gt18_count_ge8",
            "unique_gt18_count_ge8_percent",
            "unique_gt18_count_ge16",
            "unique_gt18_count_ge16_percent",
            "entry_gt18_count_ge8",
            "entry_gt18_count_ge8_percent",
            "entry_gt18_count_ge16",
            "entry_gt18_count_ge16_percent",
        ],
    )
    write_report(output_dir / "REPORT.md", summary_rows, top_rows, cross_rows)

    print(f"wrote {output_dir / 'wide_rule_prefix18_overall_summary.csv'}")
    print(f"wrote {output_dir / 'wide_rule_prefix18_bucket_summary.csv'}")
    print(f"wrote {output_dir / 'wide_rule_prefix18_top_buckets.csv'}")
    print(f"wrote {output_dir / 'wide_rule_prefix18_best_le18_cross.csv'}")
    print(f"wrote {output_dir / 'REPORT.md'}")


if __name__ == "__main__":
    main()
