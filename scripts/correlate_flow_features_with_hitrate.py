#!/usr/bin/env python3
"""Join flow-distribution features with simulator hitrate CSVs."""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path


FEATURE_COLUMNS = [
    "flows_per_million_included_packets",
    "one_packet_flow_ratio",
    "top1_packet_share",
    "top10_packet_share",
    "top100_packet_share",
    "ge1024_flow_count",
    "ge1024_packet_share",
    "ge8192_flow_count",
    "ge8192_packet_share",
    "p99_packets_per_flow",
    "max_packets_per_flow",
]

OUTCOME_COLUMNS = ["hitrate", "throughput_gbps", "power_mw", "objective"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Correlate flow features with PS/MP hitrate results.")
    parser.add_argument(
        "--flow-summary",
        default="scripts/reports/flow_stats_no_icmp/flow_trace_summary_no_icmp.csv",
    )
    parser.add_argument(
        "--result-csv",
        action="append",
        required=True,
        help="Result CSV path, or label=path. Repeatable.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--series-regex",
        default="",
        help="Optional regex for keeping result series names before joining.",
    )
    return parser.parse_args()


def read_flow_features(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as handle:
        return {row["trace"]: row for row in csv.DictReader(handle)}


def parse_result_arg(raw: str) -> tuple[str, Path]:
    if "=" in raw:
        label, path = raw.split("=", 1)
        return label.strip(), Path(path.strip())
    path = Path(raw)
    return path.parent.name or path.stem, path


def canonical_trace_name(trace_file_name: str) -> str:
    name = Path(trace_file_name).name
    if name in {"2025-09-27.pcap", "202509271400.pcap"}:
        return "2025-09-27"
    if name in {"2025-12-27.pcap", "202512271400.pcap"}:
        return "2025-12-27"
    if name in {"2026-03-27.pcap", "202603271400.pcap"}:
        return "2026-03-27"
    if name.startswith("equinix-sanjose"):
        return "equinix-sanjose-20140320"
    if name.startswith("equinix-chicago"):
        return "equinix-chicago-20140320"
    if name.startswith("equinix-nyc"):
        return "equinix-nyc-20190117"
    if name.startswith("jpix2sinet"):
        return "jpix2sinet-20180502"
    return ""


def join_rows(args: argparse.Namespace, flow_features: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    joined: list[dict[str, str]] = []
    missing: list[str] = []
    keep_re = re.compile(args.series_regex) if args.series_regex else None
    for raw in args.result_csv:
        result_label, path = parse_result_arg(raw)
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                if keep_re and not keep_re.search(row.get("series", "")):
                    continue
                trace = canonical_trace_name(row.get("trace_file_name", ""))
                if not trace:
                    missing.append(row.get("trace_file_name", ""))
                    continue
                features = flow_features.get(trace)
                if features is None:
                    missing.append(row.get("trace_file_name", ""))
                    continue
                out = {
                    "result_source": result_label,
                    "trace": trace,
                    "trace_file_name": row.get("trace_file_name", ""),
                    "trace_label": row.get("trace_label", ""),
                    "series": row.get("series", ""),
                    "family": row.get("family", ""),
                    "total_capacity_entries": row.get("total_capacity_entries", ""),
                    "capacity_config": row.get("capacity_config", ""),
                    "refbits_config": row.get("refbits_config", ""),
                    "cache_index_type": row.get("cache_index_type", ""),
                }
                for col in FEATURE_COLUMNS:
                    out[col] = features.get(col, "")
                for col in OUTCOME_COLUMNS:
                    out[col] = row.get(col, "")
                joined.append(out)
    return joined, sorted(set(item for item in missing if item))


def as_float(row: dict[str, str], key: str) -> float | None:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    x_diff = [value - x_mean for value in xs]
    y_diff = [value - y_mean for value in ys]
    numerator = sum(x * y for x, y in zip(x_diff, y_diff))
    denominator = math.sqrt(sum(x * x for x in x_diff) * sum(y * y for y in y_diff))
    return float("nan") if denominator == 0 else numerator / denominator


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            result[indexed[k][0]] = rank
        i = j
    return result


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(ranks(xs), ranks(ys))


def correlation_rows(joined: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, str]]] = {"all": joined}
    by_series: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_family: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in joined:
        by_series[row["series"]].append(row)
        by_source[row["result_source"]].append(row)
        by_family[row["family"]].append(row)
    groups["trace_mean:all"] = collapse_rows(joined, ["trace"])
    for source, rows in by_source.items():
        collapsed = collapse_rows(rows, ["result_source", "trace"])
        if len({row["trace"] for row in collapsed}) >= 3:
            groups[f"trace_mean:source:{source}"] = collapsed
    for family, rows in by_family.items():
        collapsed = collapse_rows(rows, ["family", "trace"])
        if len({row["trace"] for row in collapsed}) >= 3:
            groups[f"trace_mean:family:{family}"] = collapsed
    for series, rows in by_series.items():
        if len({row["trace"] for row in rows}) >= 3:
            groups[f"series:{series}"] = rows

    output: list[dict[str, object]] = []
    for group, rows in groups.items():
        for outcome in OUTCOME_COLUMNS:
            for feature in FEATURE_COLUMNS:
                pairs = []
                for row in rows:
                    x = as_float(row, feature)
                    y = as_float(row, outcome)
                    if x is not None and y is not None:
                        pairs.append((x, y))
                trace_count = len({row["trace"] for row in rows})
                if len(pairs) < 3:
                    continue
                xs = [item[0] for item in pairs]
                ys = [item[1] for item in pairs]
                output.append(
                    {
                        "group": group,
                        "outcome": outcome,
                        "feature": feature,
                        "n": len(pairs),
                        "trace_count": trace_count,
                        "pearson": pearson(xs, ys),
                        "spearman": spearman(xs, ys),
                    }
                )
    output.sort(key=lambda row: (row["group"], row["outcome"], -abs(float(row["pearson"]))))
    return output


def collapse_rows(rows: list[dict[str, str]], keys: list[str]) -> list[dict[str, str]]:
    buckets: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row.get(key, "") for key in keys)].append(row)

    collapsed: list[dict[str, str]] = []
    for bucket_rows in buckets.values():
        first = bucket_rows[0]
        out = {
            "result_source": first.get("result_source", ""),
            "trace": first.get("trace", ""),
            "trace_file_name": first.get("trace_file_name", ""),
            "trace_label": first.get("trace_label", ""),
            "series": first.get("series", ""),
            "family": first.get("family", ""),
            "total_capacity_entries": first.get("total_capacity_entries", ""),
            "capacity_config": first.get("capacity_config", ""),
            "refbits_config": first.get("refbits_config", ""),
            "cache_index_type": first.get("cache_index_type", ""),
        }
        for col in FEATURE_COLUMNS:
            out[col] = first.get(col, "")
        for col in OUTCOME_COLUMNS:
            values = [as_float(row, col) for row in bucket_rows]
            finite_values = [value for value in values if value is not None]
            out[col] = f"{statistics.fmean(finite_values):.12g}" if finite_values else ""
        collapsed.append(out)
    return collapsed


def write_csv(path: Path, rows: list[dict[str, object | str]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, joined: list[dict[str, str]], corr: list[dict[str, object]], missing: list[str]) -> None:
    top = sorted(
        [row for row in corr if row["outcome"] == "hitrate" and row["group"] == "all"],
        key=lambda row: -abs(float(row["pearson"])),
    )[:10]
    top_trace_mean = sorted(
        [row for row in corr if row["outcome"] == "hitrate" and row["group"] == "trace_mean:all"],
        key=lambda row: -abs(float(row["pearson"])),
    )[:10]
    lines = [
        "# Flow features vs hitrate correlation",
        "",
        f"- joined rows: `{len(joined):,}`",
        f"- traces: `{len({row['trace'] for row in joined})}`",
        "",
        "## Top all-row correlations with hitrate",
        "",
        "| feature | n | Pearson | Spearman |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in top:
        lines.append(
            f"| {row['feature']} | {row['n']} | {float(row['pearson']):.4f} | {float(row['spearman']):.4f} |"
        )
    lines.extend(
        [
            "",
            "## Top trace-mean correlations with hitrate",
            "",
            "Rows in this table first average hitrate per trace. "
            "This avoids treating repeated cache configurations as independent traffic samples.",
            "",
            "| feature | traces | Pearson | Spearman |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in top_trace_mean:
        lines.append(
            f"| {row['feature']} | {row['trace_count']} | {float(row['pearson']):.4f} | {float(row['spearman']):.4f} |"
        )
    if missing:
        lines.extend(["", "## Missing flow-feature mapping", ""])
        lines.extend(f"- `{item}`" for item in missing[:50])
    lines.extend(
        [
            "",
            "## Caveat",
            "",
            "Trace count is small, so correlation is only a screening step. "
            "Use remove-top/cap/shuffle ablation runs for causal support.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    features = read_flow_features(Path(args.flow_summary))
    joined, missing = join_rows(args, features)
    corr = correlation_rows(joined)
    write_csv(output_dir / "feature_hitrate_join.csv", joined)
    write_csv(output_dir / "feature_hitrate_correlations.csv", corr)
    write_report(output_dir / "feature_hitrate_correlation.md", joined, corr, missing)
    print(f"wrote correlation report to {output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
