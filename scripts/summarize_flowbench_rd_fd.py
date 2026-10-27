#!/usr/bin/env python3
"""FlowBench の rd・fd 掃引（run_flowbench_rd_fd_sweep.sh の出力）を集計する（#117、#118）。

入力（--input-dir）:

    coverage/<label>/lpm_prefix_coverage.csv, lpm_prefix_entries.csv
    hitrate/<label>.csv   windowed_hitrate（-windows 1000000,10000000、-ps-index-types 2,5,108..124）

label は ``real`` か ``fb_rd<a>-<b>_fd<a>-<b>_s<seed>``。

LTPC の best L は、direct prefix index（100+L）のうち先頭 1M パケットの累積 hit rate が最大の L
（同点なら 18 に近いほう）で、10M 通しの hit rate で評価する。oracle は 10M で選んだ L。

出力（--output-dir）:

- per_trace.csv: trace ごとの使われる prefix 数・上位 prefix の packet 割合・平均 LPM 長・hit rate
- by_condition.csv: (rd, fd) ごとの seed の平均・最小・最大
- brief.csv: by_condition.csv の主な指標の平均だけ（Issue の comment 用）
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

from summarize_flowbench_bestl import direct_length, read_rates

LABEL = re.compile(r"fb_rd([\d.]+)-([\d.]+)_fd([\d.]+)-([\d.]+)_s(\d+)$")
METRICS = [
    "distinct_lpm_prefixes", "lpm_top1_share", "lpm_top100_share", "matched_len_avg",
    "mp", "ltpc_crc18", "ltpc_direct18", "ltpc_best_l", "ltpc_oracle_l", "ltpc_ideal", "best_l_1m",
    "ltpc_best_l_minus_mp",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def coverage(base: Path) -> dict[str, float]:
    """最後の checkpoint での使われる prefix 数・上位 prefix の割合・平均 LPM 長。"""
    by_checkpoint: dict[int, list[dict]] = defaultdict(list)
    with (base / "lpm_prefix_coverage.csv").open() as handle:
        for r in csv.DictReader(handle):
            by_checkpoint[int(r["checkpoint_packets"])].append(r)
    last = by_checkpoint[max(by_checkpoint)]
    packets = sum(int(r["packet_count"]) for r in last)
    # entries は長さごとの上位 100 なので、全体の上位 100 はその和集合に含まれる
    with (base / "lpm_prefix_entries.csv").open() as handle:
        counts = sorted((int(r["packet_count"]) for r in csv.DictReader(handle)), reverse=True)
    return {
        "distinct_lpm_prefixes": sum(int(r["distinct_lpm_prefixes"]) for r in last),
        "lpm_top1_share": sum(counts[:1]) / packets,
        "lpm_top100_share": sum(counts[:100]) / packets,
        "matched_len_avg": sum(int(r["lpm_prefix_length"]) * int(r["packet_count"]) for r in last) / packets,
    }


def hitrates(path: Path) -> dict[str, float]:
    at1m, at10m = read_rates(path)
    direct = {direct_length(c): c for c in at10m if direct_length(c) is not None}
    best = max(direct, key=lambda length: (at1m[direct[length]], -abs(length - 18)))
    oracle = max(direct, key=lambda length: at10m[direct[length]])
    mp = next(v for c, v in at10m.items() if c.startswith("mp-"))
    return {
        "mp": mp,
        "ltpc_crc18": next(v for c, v in at10m.items() if c.startswith("ps-index5-")),
        "ltpc_direct18": at10m[direct[18]],
        "best_l_1m": best,
        "ltpc_best_l": at10m[direct[best]],
        "oracle_l_10m": oracle,
        "ltpc_oracle_l": at10m[direct[oracle]],
        "ltpc_ideal": next(v for c, v in at10m.items() if c.startswith("ps-ideal-")),
        "ltpc_best_l_minus_mp": at10m[direct[best]] - mp,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    src = Path(args.input_dir)
    rows = []
    for path in sorted((src / "hitrate").glob("*.csv")):
        label = path.stem
        m = LABEL.match(label)
        row = {
            "label": label,
            "rd_a": m.group(1) if m else "",
            "rd_b": m.group(2) if m else "",
            "fd_a": m.group(3) if m else "",
            "fd_b": m.group(4) if m else "",
            "seed": m.group(5) if m else "",
        }
        row.update(coverage(src / "coverage" / label))
        row.update(hitrates(path))
        rows.append(row)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "per_trace.csv", rows)

    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["rd_a"], r["rd_b"], r["fd_a"], r["fd_b"])].append(r)
    summary = []
    for key, group in sorted(groups.items()):
        row = dict(zip(("rd_a", "rd_b", "fd_a", "fd_b"), key))
        row["seeds"] = len(group)
        for name in METRICS:
            values = [float(r[name]) for r in group]
            row[f"{name}_mean"] = sum(values) / len(values)
            row[f"{name}_min"] = min(values)
            row[f"{name}_max"] = max(values)
        summary.append(row)
    write_csv(out / "by_condition.csv", summary)
    # Issue の comment に載せる、主な指標の seed 平均だけの表
    brief_metrics = ["distinct_lpm_prefixes", "lpm_top100_share", "mp", "ltpc_best_l", "ltpc_best_l_minus_mp", "best_l_1m"]
    brief = [{k: r[k] for k in ("rd_a", "fd_a", "seeds")} | {m: round(r[f"{m}_mean"], 4) for m in brief_metrics}
             for r in summary]
    write_csv(out / "brief.csv", brief)


if __name__ == "__main__":
    main()
