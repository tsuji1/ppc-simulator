#!/usr/bin/env python3
"""Join simulator recordCacheHit output with packet-to-flow-bin metadata."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attribute cache hit/miss lines to flow-length bins using packet_flow_map.csv."
    )
    parser.add_argument("--packet-flow-map", required=True)
    parser.add_argument("--hit-trace", required=True, help="cachehitrace file with one 'hit IP' or 'miss IP' line per packet.")
    parser.add_argument("--variant", required=True)
    parser.add_argument("--config-label", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--bin-column",
        choices=("variant_flow_bin", "baseline_flow_bin"),
        default="variant_flow_bin",
        help="Which flow bin to use for grouping.",
    )
    return parser.parse_args()


def read_packet_rows(path: Path, variant: str) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["variant"] == variant]
    if not rows:
        raise SystemExit(f"no rows found for variant {variant!r} in {path}")
    rows.sort(key=lambda row: int(row["row_index"]))
    return rows


def read_hit_lines(path: Path) -> list[bool]:
    result: list[bool] = []
    with path.open() as handle:
        for line_number, line in enumerate(handle, start=1):
            fields = line.strip().split()
            if not fields:
                continue
            state = fields[0].lower()
            if state == "hit":
                result.append(True)
            elif state == "miss":
                result.append(False)
            else:
                raise SystemExit(f"{path}:{line_number}: expected hit/miss, got {fields[0]!r}")
    if not result:
        raise SystemExit(f"no hit/miss lines found in {path}")
    return result


def bin_sort_key(label: str) -> tuple[int, int]:
    if "-" not in label:
        value = int(label.replace(",", ""))
        return (value, value)
    left, right = label.split("-", 1)
    return (int(left.replace(",", "")), int(right.replace(",", "")))


def analyze(rows: list[dict[str, str]], hits: list[bool], bin_column: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    if len(rows) != len(hits):
        raise SystemExit(f"packet map rows ({len(rows)}) and hit lines ({len(hits)}) differ")

    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"packets": 0, "hits": 0, "misses": 0})
    top100 = {"packets": 0, "hits": 0, "misses": 0}
    non_top100 = {"packets": 0, "hits": 0, "misses": 0}

    for row, is_hit in zip(rows, hits):
        label = row[bin_column]
        group = groups[label]
        group["packets"] += 1
        if is_hit:
            group["hits"] += 1
        else:
            group["misses"] += 1

        rank = int(row["flow_rank"])
        target = top100 if rank <= 100 else non_top100
        target["packets"] += 1
        if is_hit:
            target["hits"] += 1
        else:
            target["misses"] += 1

    total_packets = len(hits)
    total_hits = sum(1 for hit in hits if hit)
    total_misses = total_packets - total_hits
    summary = {
        "packets": total_packets,
        "hits": total_hits,
        "misses": total_misses,
        "hit_rate": ratio(total_hits, total_packets),
        "top100_packets": top100["packets"],
        "top100_hit_rate": ratio(top100["hits"], top100["packets"]),
        "non_top100_packets": non_top100["packets"],
        "non_top100_hit_rate": ratio(non_top100["hits"], non_top100["packets"]),
    }

    bin_rows = []
    for label, values in sorted(groups.items(), key=lambda item: bin_sort_key(item[0])):
        packets = values["packets"]
        hits_for_bin = values["hits"]
        misses_for_bin = values["misses"]
        bin_rows.append(
            {
                "flow_bin": label,
                "packets": packets,
                "packet_share": ratio(packets, total_packets),
                "hits": hits_for_bin,
                "misses": misses_for_bin,
                "hit_rate": ratio(hits_for_bin, packets),
                "miss_share": ratio(misses_for_bin, total_misses),
            }
        )
    return summary, bin_rows


def ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else float(numerator) / float(denominator)


def write_outputs(output_dir: Path, variant: str, config_label: str, summary: dict[str, object], bin_rows: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{variant}__{config_label}" if config_label else variant
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)

    summary_path = output_dir / f"{stem}_hit_summary.csv"
    with summary_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for key, value in summary.items():
            writer.writerow([key, value])

    bin_path = output_dir / f"{stem}_hit_by_flow_bin.csv"
    with bin_path.open("w", newline="") as handle:
        fieldnames = ["flow_bin", "packets", "packet_share", "hits", "misses", "hit_rate", "miss_share"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(bin_rows)

    md_path = output_dir / f"{stem}_hit_by_flow_bin.md"
    lines = [
        f"# Hit/miss by flow bin: {variant}",
        "",
        f"- config: `{config_label or 'unknown'}`",
        f"- packets: `{int(summary['packets']):,}`",
        f"- hit rate: `{float(summary['hit_rate']) * 100:.4f}%`",
        f"- top100 hit rate: `{float(summary['top100_hit_rate']) * 100:.4f}%`",
        "",
        "| flow bin | packets | packet share | misses | hit rate | miss share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in bin_rows:
        lines.append(
            "| {flow_bin} | {packets:,} | {packet_share:.2%} | {misses:,} | {hit_rate:.4%} | {miss_share:.2%} |".format(
                flow_bin=row["flow_bin"],
                packets=int(row["packets"]),
                packet_share=float(row["packet_share"]),
                misses=int(row["misses"]),
                hit_rate=float(row["hit_rate"]),
                miss_share=float(row["miss_share"]),
            )
        )
    md_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {summary_path}, {bin_path}, {md_path}", file=sys.stderr)


def main() -> None:
    args = parse_args()
    rows = read_packet_rows(Path(args.packet_flow_map), args.variant)
    hits = read_hit_lines(Path(args.hit_trace))
    summary, bin_rows = analyze(rows, hits, args.bin_column)
    write_outputs(Path(args.output_dir), args.variant, args.config_label, summary, bin_rows)


if __name__ == "__main__":
    main()
