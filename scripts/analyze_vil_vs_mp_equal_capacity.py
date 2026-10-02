#!/usr/bin/env python3
"""Compare VIL and best MP3 at exactly equal total entry capacity."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-dir",
        default="scripts/reports/vil_vs_mp_cause_20260731/base_comparison",
        help="Directory produced by plot_mp3_sweep_results.py",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/reports/vil_vs_mp_cause_20260731/equal_capacity",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def as_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mp_rows = read_csv(base_dir / "best_by_total_capacity.csv")
    vil_rows = read_csv(base_dir / "vil_points.csv")
    mp_by_key = {
        (row["trace_key"], int(row["total_capacity"])): row
        for row in mp_rows
    }
    vil_by_key = {
        (row["trace_key"], int(row["capacity"]), row["cache_index_label"]): row
        for row in vil_rows
    }

    rows: list[dict[str, object]] = []
    trace_keys = sorted({row["trace_key"] for row in vil_rows})
    capacities = sorted(
        {int(row["capacity"]) for row in vil_rows}
        & {int(row["total_capacity"]) for row in mp_rows}
    )
    for trace_key in trace_keys:
        for capacity in capacities:
            mp = mp_by_key.get((trace_key, capacity))
            ideal = vil_by_key.get((trace_key, capacity, "IDEAL"))
            fixed_candidates = [
                row
                for row in vil_rows
                if row["trace_key"] == trace_key
                and int(row["capacity"]) == capacity
                and row["cache_index_label"] != "IDEAL"
            ]
            prefix18 = vil_by_key.get((trace_key, capacity, "PREFIX18"))
            if not mp or not ideal or not fixed_candidates or not prefix18:
                continue
            best_fixed = max(
                fixed_candidates,
                key=lambda row: as_float(row, "hitrate_percent"),
            )
            mp_hit = as_float(mp, "hitrate_percent")
            ideal_hit = as_float(ideal, "hitrate_percent")
            fixed_hit = as_float(best_fixed, "hitrate_percent")
            prefix18_hit = as_float(prefix18, "hitrate_percent")
            rows.append(
                {
                    "trace_key": trace_key,
                    "trace_label": mp["trace_label"],
                    "capacity": capacity,
                    "mp_hitrate_percent": mp_hit,
                    "mp_config": mp["capacity_signature"],
                    "mp_refbits": mp["refbits"],
                    "vil_ideal_hitrate_percent": ideal_hit,
                    "vil_ideal_minus_mp_points": ideal_hit - mp_hit,
                    "vil_best_fixed_index": best_fixed["cache_index_label"],
                    "vil_best_fixed_hitrate_percent": fixed_hit,
                    "vil_best_fixed_minus_mp_points": fixed_hit - mp_hit,
                    "vil_prefix18_hitrate_percent": prefix18_hit,
                    "vil_prefix18_minus_mp_points": prefix18_hit - mp_hit,
                    "vil_ideal_minus_prefix18_points": ideal_hit - prefix18_hit,
                }
            )

    csv_path = output_dir / "equal_capacity_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    report_lines = [
        "# VIL vs MP3 at equal entry capacity",
        "",
        "MP3 is the best measured three-layer configuration at the exact same total entry count.",
        "VIL fixed is the best measured PREFIX16..PREFIX24 index; IDEAL is the leaf-aware index.",
        "",
        "| trace | entries | MP3 hit | VIL best fixed hit | fixed - MP | VIL IDEAL hit | IDEAL - MP | PREFIX18 hit | IDEAL - PREFIX18 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report_lines.append(
            "| {trace_label} | {capacity} | {mp_hitrate_percent:.6f}% | "
            "{vil_best_fixed_hitrate_percent:.6f}% ({vil_best_fixed_index}) | "
            "{vil_best_fixed_minus_mp_points:+.6f} pt | "
            "{vil_ideal_hitrate_percent:.6f}% | {vil_ideal_minus_mp_points:+.6f} pt | "
            "{vil_prefix18_hitrate_percent:.6f}% | "
            "{vil_ideal_minus_prefix18_points:+.6f} pt |".format(**row)
        )
    report_lines.extend(
        [
            "",
            "## Reading the deltas",
            "",
            "- `IDEAL - MP` is the architectural headroom when index placement follows the cached prefix length.",
            "- `best fixed - MP` is what a realizable single fixed prefix index achieves in this sweep.",
            "- `IDEAL - PREFIX18` isolates the placement/conflict cost of forcing every variable-length entry through a /18-derived set index.",
            "",
        ]
    )
    (output_dir / "REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Saved report directory: {output_dir}")
    print(f"comparison rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
