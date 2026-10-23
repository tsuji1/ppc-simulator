#!/usr/bin/env python3
"""Summarize the LTPC index-length sweep on FlowBench traces (#83).

Input: ``windowed_hitrate`` CSVs (one per trace) run with
``-windows 1000000,10000000 -ps-index-types 2,5,108..124``. File names are
``real_nonanon.csv``, ``orig_<trace>.csv`` (FlowBench as generated) and
``wide_<trace>.csv`` (after ``flowbench_widen_dst.py``), where ``<trace>`` is
``fb_rib20260327_rd<a>-<b>_fd1-1_n10m_s<seed>``.

The best L is chosen per trace by the cumulative hit rate of the first 1M
packets among the direct prefix indexes (100+L), and evaluated by the hit
rate over the whole 10M packets. ``oracle`` is the best L chosen on 10M.

Writes ``per_trace.csv`` and ``by_a.csv`` (mean / min / max over seeds).
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

TRACE = re.compile(r"(orig|wide)_fb_rib\d+_rd([\d.]+)-([\d.]+)_fd1-1_n10m_s(\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_rates(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    """cumulative hit rate of each config at 1M and at 10M packets."""
    at1m: dict[str, float] = {}
    at10m: dict[str, float] = {}
    with path.open() as handle:
        for r in csv.DictReader(handle):
            if r["window_index"] != "0":
                continue
            rate = float(r["cumulative_hit_rate"])
            if r["window_size"] == "1000000":
                at1m[r["config_id"]] = rate
            elif r["window_size"] == "10000000":
                at10m[r["config_id"]] = rate
    return at1m, at10m


def direct_length(config_id: str) -> int | None:
    m = re.match(r"ps-index1(\d\d)-cap", config_id)
    return int(m.group(1)) if m else None


def main() -> None:
    args = parse_args()
    rows = []
    for path in sorted(Path(args.input_dir).glob("*.csv")):
        at1m, at10m = read_rates(path)
        if not at10m:
            continue
        direct = {direct_length(c): c for c in at10m if direct_length(c) is not None}
        best = max(direct, key=lambda length: (at1m[direct[length]], -abs(length - 18)))
        oracle = max(direct, key=lambda length: at10m[direct[length]])
        m = TRACE.match(path.stem)
        rows.append({
            "label": path.stem,
            "variant": m.group(1) if m else "real",
            "rule_a": m.group(2) if m else "",
            "rule_b": m.group(3) if m else "",
            "seed": m.group(4) if m else "",
            "mp": next(v for c, v in at10m.items() if c.startswith("mp-")),
            "ltpc_crc18": next(v for c, v in at10m.items() if c.startswith("ps-index5-")),
            "ltpc_ideal": next(v for c, v in at10m.items() if c.startswith("ps-ideal-")),
            "ltpc_direct18": at10m[direct[18]],
            "best_l_1m": best,
            "ltpc_best_l": at10m[direct[best]],
            "oracle_l_10m": oracle,
            "ltpc_oracle_l": at10m[direct[oracle]],
        })
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "per_trace.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["variant"], r["rule_a"], r["rule_b"])].append(r)
    metrics = ["mp", "ltpc_crc18", "ltpc_direct18", "ltpc_best_l", "ltpc_oracle_l", "ltpc_ideal", "best_l_1m"]
    summary = []
    for (variant, a, b), group in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        row = {"variant": variant, "rule_a": a, "rule_b": b, "seeds": len(group)}
        for name in metrics:
            values = [float(r[name]) for r in group]
            row[f"{name}_mean"] = sum(values) / len(values)
            row[f"{name}_min"] = min(values)
            row[f"{name}_max"] = max(values)
        summary.append(row)
    with (out / "by_a.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)


if __name__ == "__main__":
    main()
