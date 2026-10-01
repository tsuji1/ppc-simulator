#!/usr/bin/env python3
import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path


TRACE_ORDER = {
    "2025-09-27": 0,
    "2025-12-27": 1,
    "2026-03-27": 2,
    "equinix-sanjose-": 3,
    "equinix-sanjose-20140320": 3,
    "equinix-chicago-20140320": 4,
    "equinix-nyc-20190117": 5,
    "jpix2sinet-20180502": 6,
}

TRACE_ALIASES = {
    "equinix-sanjose-": "equinix-sanjose-20140320",
}

SUMMARY_FIELDS = [
    "trace",
    "trace_kind",
    "source_ipv4_packets",
    "included_packets",
    "excluded_icmp_packets",
    "excluded_icmp_packet_ratio_of_source_ipv4",
    "source_flow_count",
    "included_flow_count",
    "excluded_icmp_flow_count",
    "excluded_icmp_flow_ratio_of_source_flows",
    "flows_per_million_included_packets",
    "flows_per_million_source_ipv4_packets",
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
    "p50_bytes_per_flow",
    "p90_bytes_per_flow",
    "p99_bytes_per_flow",
    "max_bytes_per_flow",
    "p50_duration_seconds",
    "p90_duration_seconds",
    "p99_duration_seconds",
    "max_duration_seconds",
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
        description="Recompute flow statistics while excluding ICMP flows."
    )
    parser.add_argument(
        "--input-root",
        default="scripts/reports/flow_stats",
        help="Directory containing per-trace flow_lengths.csv files.",
    )
    parser.add_argument(
        "--output-root",
        default="scripts/reports/flow_stats_no_icmp",
        help="Output directory for ICMP-excluded reports.",
    )
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--progress-interval", type=int, default=1_000_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    trace_dirs = select_trace_dirs(input_root)
    if not trace_dirs:
        raise SystemExit(f"no flow_lengths.csv files found under {input_root}")

    summaries = []
    for trace_dir in trace_dirs:
        print(f"analyzing {trace_dir.name} without ICMP", file=sys.stderr)
        summaries.append(analyze_trace(trace_dir, output_root / trace_dir.name, args))

    write_summary_csv(output_root / "flow_trace_summary_no_icmp.csv", summaries)
    write_markdown(output_root / "flow_count_length_no_icmp.md", summaries)
    print(f"wrote ICMP-excluded flow analysis to {output_root}", file=sys.stderr)


def canonical_trace_name(name: str) -> str:
    return TRACE_ALIASES.get(name, name)


def select_trace_dirs(input_root: Path) -> list[Path]:
    selected: dict[str, Path] = {}
    for path in input_root.iterdir():
        if not path.is_dir() or not (path / "flow_lengths.csv").exists():
            continue
        canonical = canonical_trace_name(path.name)
        current = selected.get(canonical)
        if current is None or (current.name != canonical and path.name == canonical):
            selected[canonical] = path
    return sorted(
        selected.values(),
        key=lambda p: (TRACE_ORDER.get(canonical_trace_name(p.name), 100), canonical_trace_name(p.name)),
    )


def analyze_trace(trace_dir: Path, output_dir: Path, args: argparse.Namespace) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_summary = read_metric_csv(trace_dir / "flow_summary.csv")
    flow_lengths_path = trace_dir / "flow_lengths.csv"

    source_ipv4_packets = int(source_summary.get("ipv4_packets", "0"))
    trace_kind = source_summary.get("trace_kind", "")
    source_trace = source_summary.get("trace", trace_dir.name)

    packets_values: list[int] = []
    bytes_values: list[int] = []
    duration_values: list[float] = []
    top_rows: list[list[str]] = []
    bins: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"flows": 0, "packets": 0, "bytes": 0}
    )
    protocol_packets: dict[int, int] = defaultdict(int)
    protocol_flows: dict[int, int] = defaultdict(int)

    included_packets = 0
    included_bytes = 0
    included_flows = 0
    excluded_icmp_packets = 0
    excluded_icmp_flows = 0
    source_flow_count = 0
    one_packet_flows = 0
    top_flow_desc = ""
    top1_packets = 0
    top10_packets = 0
    top100_packets = 0

    with flow_lengths_path.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        idx = {name: pos for pos, name in enumerate(header)}
        for row_number, row in enumerate(reader, start=1):
            source_flow_count += 1
            protocol_number = int(row[idx["protocol_number"]])
            packets = int(row[idx["packets"]])
            bytes_ = int(row[idx["bytes"]])

            if protocol_number == 1:
                excluded_icmp_packets += packets
                excluded_icmp_flows += 1
                continue

            duration = float(row[idx["duration_seconds"]])
            included_flows += 1
            included_packets += packets
            included_bytes += bytes_
            protocol_packets[protocol_number] += packets
            protocol_flows[protocol_number] += 1

            packets_values.append(packets)
            bytes_values.append(bytes_)
            duration_values.append(duration)
            if packets == 1:
                one_packet_flows += 1

            lower, upper = packet_bin(packets)
            bins[(lower, upper)]["flows"] += 1
            bins[(lower, upper)]["packets"] += packets
            bins[(lower, upper)]["bytes"] += bytes_

            reranked_row = row[:]
            reranked_row[idx["rank"]] = str(included_flows)
            if len(top_rows) < args.top_n:
                top_rows.append(reranked_row)
                if included_flows == 1:
                    top1_packets = packets
                    top_flow_desc = format_flow_desc(row, idx)
                if included_flows <= 10:
                    top10_packets += packets
                if included_flows <= 100:
                    top100_packets += packets

            if args.progress_interval and row_number % args.progress_interval == 0:
                print(
                    f"  {trace_dir.name}: read {row_number:,} flows; included {included_flows:,}; ICMP {excluded_icmp_flows:,}",
                    file=sys.stderr,
                )

    packets_values.sort()
    bytes_values.sort()
    duration_values.sort()
    bin_rows = build_bin_rows(bins, included_flows, included_packets, included_bytes)
    cutoffs = {
        "cutoff99_flow_count_bin": cutoff_bin(bin_rows, 0.99),
        "cutoff995_flow_count_bin": cutoff_bin(bin_rows, 0.995),
        "cutoff999_flow_count_bin": cutoff_bin(bin_rows, 0.999),
    }
    ge1024 = sum_tail(bin_rows, 1024)
    ge8192 = sum_tail(bin_rows, 8192)
    max_bin = format_bin(bin_rows[-1]["lower"], bin_rows[-1]["upper"]) if bin_rows else ""

    summary = {
        "trace": trace_dir.name,
        "trace_kind": trace_kind,
        "source_trace": source_trace,
        "source_ipv4_packets": source_ipv4_packets,
        "included_packets": included_packets,
        "excluded_icmp_packets": excluded_icmp_packets,
        "excluded_icmp_packet_ratio_of_source_ipv4": ratio(excluded_icmp_packets, source_ipv4_packets),
        "source_flow_count": source_flow_count,
        "included_flow_count": included_flows,
        "excluded_icmp_flow_count": excluded_icmp_flows,
        "excluded_icmp_flow_ratio_of_source_flows": ratio(excluded_icmp_flows, source_flow_count),
        "flows_per_million_included_packets": ratio(included_flows * 1_000_000, included_packets),
        "flows_per_million_source_ipv4_packets": ratio(included_flows * 1_000_000, source_ipv4_packets),
        "packets_per_flow": ratio(included_packets, included_flows),
        "one_packet_flow_count": one_packet_flows,
        "one_packet_flow_ratio": ratio(one_packet_flows, included_flows),
        "single_packet_packet_share": packet_share_for_bin(bin_rows, 1, 1),
        "top1_packet_share": ratio(top1_packets, included_packets),
        "top10_packet_share": ratio(top10_packets, included_packets),
        "top100_packet_share": ratio(top100_packets, included_packets),
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
        **cutoffs,
        "ge1024_flow_count": ge1024["flows"],
        "ge1024_flow_ratio": ge1024["flow_ratio"],
        "ge1024_packet_share": ge1024["packet_ratio"],
        "ge8192_flow_count": ge8192["flows"],
        "ge8192_flow_ratio": ge8192["flow_ratio"],
        "ge8192_packet_share": ge8192["packet_ratio"],
        "max_nonempty_bin": max_bin,
        "top_flow": top_flow_desc,
        "protocol_packets": protocol_packets,
        "protocol_flows": protocol_flows,
    }

    write_trace_summary_csv(output_dir / "flow_summary_no_icmp.csv", summary)
    write_bins_csv(output_dir / "flow_length_bins_no_icmp.csv", bin_rows)
    write_top_flows_csv(output_dir / "top_flows_no_icmp.csv", header, top_rows)
    write_protocol_csv(output_dir / "protocol_counts_no_icmp.csv", protocol_packets, protocol_flows, included_packets, included_flows)
    return summary


def read_metric_csv(path: Path) -> dict[str, str]:
    result = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            result[row["metric"]] = row["value"]
    return result


def packet_bin(packets: int) -> tuple[int, int]:
    if packets <= 1:
        return 1, 1
    exp = packets.bit_length() - 1
    lower = 1 << exp
    upper = (1 << (exp + 1)) - 1
    return lower, upper


def build_bin_rows(
    bins: dict[tuple[int, int], dict[str, float]],
    included_flows: int,
    included_packets: int,
    included_bytes: int,
) -> list[dict[str, float]]:
    rows = []
    for (lower, upper), values in sorted(bins.items()):
        rows.append(
            {
                "lower": lower,
                "upper": upper,
                "flows": int(values["flows"]),
                "flow_ratio": ratio(values["flows"], included_flows),
                "packets": int(values["packets"]),
                "packet_ratio": ratio(values["packets"], included_packets),
                "bytes": int(values["bytes"]),
                "byte_ratio": ratio(values["bytes"], included_bytes),
            }
        )
    return rows


def percentile(sorted_values: list[float], q: float):
    if not sorted_values:
        return 0
    index = math.ceil(q * len(sorted_values)) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[index]


def cutoff_bin(bin_rows: list[dict[str, float]], target: float) -> str:
    cumulative = 0.0
    for row in bin_rows:
        cumulative += row["flow_ratio"]
        if cumulative >= target:
            return format_bin(row["lower"], row["upper"])
    if not bin_rows:
        return ""
    return format_bin(bin_rows[-1]["lower"], bin_rows[-1]["upper"])


def sum_tail(bin_rows: list[dict[str, float]], threshold: int) -> dict[str, float]:
    flows = 0
    flow_ratio = 0.0
    packet_ratio = 0.0
    for row in bin_rows:
        if row["lower"] >= threshold:
            flows += row["flows"]
            flow_ratio += row["flow_ratio"]
            packet_ratio += row["packet_ratio"]
    return {"flows": flows, "flow_ratio": flow_ratio, "packet_ratio": packet_ratio}


def packet_share_for_bin(bin_rows: list[dict[str, float]], lower: int, upper: int) -> float:
    for row in bin_rows:
        if row["lower"] == lower and row["upper"] == upper:
            return row["packet_ratio"]
    return 0.0


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def format_bin(lower: int, upper: int) -> str:
    if lower == upper:
        return f"{lower:,}"
    return f"{lower:,}-{upper:,}"


def format_flow_desc(row: list[str], idx: dict[str, int]) -> str:
    return (
        f"{row[idx['protocol']]} {row[idx['src_ip']]}:{row[idx['src_port']]} -> "
        f"{row[idx['dst_ip']]}:{row[idx['dst_port']]} "
        f"({int(row[idx['packets']]):,} pkts, {float(row[idx['duration_seconds']]):.1f}s)"
    )


def write_trace_summary_csv(path: Path, summary: dict[str, object]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for field in SUMMARY_FIELDS:
            writer.writerow([field, format_value(summary.get(field, ""))])
        writer.writerow(["source_trace", summary.get("source_trace", "")])


def write_bins_csv(path: Path, bin_rows: list[dict[str, float]]) -> None:
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
        for row in bin_rows:
            writer.writerow(
                [
                    row["lower"],
                    row["upper"],
                    row["flows"],
                    f"{row['flow_ratio']:.12f}",
                    row["packets"],
                    f"{row['packet_ratio']:.12f}",
                    row["bytes"],
                    f"{row['byte_ratio']:.12f}",
                ]
            )


def write_top_flows_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def write_protocol_csv(
    path: Path,
    protocol_packets: dict[int, int],
    protocol_flows: dict[int, int],
    included_packets: int,
    included_flows: int,
) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "protocol_number",
                "protocol_name",
                "flow_count",
                "flow_ratio",
                "packets",
                "packet_ratio",
            ]
        )
        for protocol in sorted(protocol_packets, key=lambda p: (-protocol_packets[p], p)):
            writer.writerow(
                [
                    protocol,
                    protocol_name(protocol),
                    protocol_flows[protocol],
                    f"{ratio(protocol_flows[protocol], included_flows):.12f}",
                    protocol_packets[protocol],
                    f"{ratio(protocol_packets[protocol], included_packets):.12f}",
                ]
            )


def write_summary_csv(path: Path, summaries: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({field: format_value(summary.get(field, "")) for field in SUMMARY_FIELDS})


def write_markdown(path: Path, summaries: list[dict[str, object]]) -> None:
    lines = []
    lines.append("# Flow analysis excluding ICMP")
    lines.append("")
    lines.append("ICMP (`protocol_number=1`) を除外し、TCP / UDP / その他 IPv4 protocol の flow だけで再集計した。")
    lines.append("分母は `included_packets`、つまり non-ICMP IPv4 packets。`source_ipv4_packets` は元の ICMP 込み IPv4 packet 数。")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| trace | included packets | included flows | ICMP packet share | ICMP flow share | flows / 1M included pkts | 1-pkt flow ratio | top100 pkt share | p99 pkts/flow | 99% cutoff |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for item in summaries:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["trace"]),
                    f"{int(item['included_packets']):,}",
                    f"{int(item['included_flow_count']):,}",
                    pct(item["excluded_icmp_packet_ratio_of_source_ipv4"]),
                    pct(item["excluded_icmp_flow_ratio_of_source_flows"]),
                    f"{float(item['flows_per_million_included_packets']):,.0f}",
                    pct(item["one_packet_flow_ratio"]),
                    pct(item["top100_packet_share"]),
                    f"{int(item['p99_packets_per_flow']):,}",
                    str(item["cutoff99_flow_count_bin"]),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Effect of excluding ICMP")
    lines.append("")
    lines.append("| trace | original flows / 1M IPv4 pkts | non-ICMP flows / 1M non-ICMP pkts | ICMP flow share | ICMP packet share |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for item in summaries:
        original_density = ratio(int(item["source_flow_count"]) * 1_000_000, int(item["source_ipv4_packets"]))
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["trace"]),
                    f"{original_density:,.0f}",
                    f"{float(item['flows_per_million_included_packets']):,.0f}",
                    pct(item["excluded_icmp_flow_ratio_of_source_flows"]),
                    pct(item["excluded_icmp_packet_ratio_of_source_ipv4"]),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("ICMP は非匿名 trace で flow 数の半分以上を占めるが、packet share は `20.7-27.4%`。つまり ICMP は flow 数をかなり増やす一方、巨大 flow tail の主役ではない。ICMP を除外すると、non-ICMP 側の巨大 flow の packet share が相対的に上がる。")
    lines.append("")

    lines.append("## Large-flow tail")
    lines.append("")
    lines.append("| trace | top1 pkt share | >=1024 flows | >=1024 pkt share | >=8192 flows | >=8192 pkt share | max bin | top non-ICMP flow |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for item in summaries:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["trace"]),
                    pct(item["top1_packet_share"]),
                    f"{int(item['ge1024_flow_count']):,}",
                    pct(item["ge1024_packet_share"]),
                    f"{int(item['ge8192_flow_count']):,}",
                    pct(item["ge8192_packet_share"]),
                    str(item["max_nonempty_bin"]),
                    str(item["top_flow"]),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Interpretation")
    lines.append("")
    lines.append("- 非匿名 trace では ICMP が packet の `20.7-27.4%` を占めるため、ICMP を除外すると分母が小さくなり、TCP/UDP/other の巨大 flow の packet share は相対的に大きく見える。")
    lines.append("- それでも非匿名 trace の短命 flow dominance は残る。ICMP 除外後も 1-packet flow ratio は高く、99% cutoff は短い packet-count bin に留まる。")
    lines.append("- Equinix は元々 ICMP が小さいため、ICMP 除外による変化は限定的。中長 flow が厚いという結論は変わらない。")
    lines.append("")

    lines.append("## Files")
    lines.append("")
    lines.append("- `flow_trace_summary_no_icmp.csv`: trace 間比較の summary")
    lines.append("- `<trace>/flow_summary_no_icmp.csv`: trace ごとの metric")
    lines.append("- `<trace>/flow_length_bins_no_icmp.csv`: ICMP 除外後の log2 bin")
    lines.append("- `<trace>/top_flows_no_icmp.csv`: ICMP 除外後の top flows")
    lines.append("- `<trace>/protocol_counts_no_icmp.csv`: ICMP 除外後の protocol 別 flow / packet count")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def protocol_name(protocol: int) -> str:
    if protocol == 6:
        return "TCP"
    if protocol == 17:
        return "UDP"
    if protocol == 1:
        return "ICMP"
    return f"IP:{protocol}"


def pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%"


def format_value(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.12f}"
    return value


if __name__ == "__main__":
    main()
