#!/usr/bin/env python3
"""run_trace_key_locality.sh の特徴量と hit rate をまとめる（#117）。

入力:

- --input-dir: features/<label>.csv（metric,value）と hitrate/<label>.csv（実 trace のみ）
- --fb-per-trace: FlowBench の hit rate（summarize_flowbench_rd_fd.py の per_trace.csv）

出力（--output-dir）:

- per_trace.csv: trace ごとの特徴量と hit rate（mp、ltpc_best_l、差）
- by_condition.csv: 実 trace はそのまま、FlowBench は (rd, fd) ごとの seed 平均
- brief.csv: by_condition.csv の主な列だけ（Issue の comment 用）
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

from summarize_flowbench_rd_fd import hitrates

LABEL = re.compile(r"fb_rd([\d.]+)-1_fd([\d.]+)-1_s(\d+)$")
TEXT = {"label", "trace", "rule"}
BRIEF = [
    "distinct_dst", "dst_run_avg", "matched_len_avg", "leaf_len_avg", "leaf_le16_share", "leaf_19_24_share",
    "distinct_ltpc_keys", "distinct_mp18_keys", "distinct_mp24_keys", "mp_keys_per_ltpc_key_pkt_weighted",
    "ltpc_run_avg", "mp_run_avg", "ltpc_cold_miss", "mp_cold_miss", "ltpc_reuse_p90", "mp24_reuse_p90",
    "ltpc_lru_hit", "mp_lru_hit", "mp", "ltpc_best_l", "ltpc_best_l_minus_mp",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--fb-per-trace", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_features(path: Path) -> dict[str, object]:
    with path.open() as handle:
        return {r["metric"]: (r["value"] if r["metric"] in TEXT else float(r["value"])) for r in csv.DictReader(handle)}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    src = Path(args.input_dir)
    with open(args.fb_per_trace) as handle:
        fb_hit = {r["label"]: r for r in csv.DictReader(handle)}

    rows = []
    for path in sorted((src / "features").glob("*.csv")):
        label = path.stem
        feat = read_features(path)
        m = LABEL.match(label)
        row: dict[str, object] = {"label": label, "rd_a": m.group(1) if m else "", "fd_a": m.group(2) if m else "",
                                  "seed": m.group(3) if m else ""}
        row.update({k: v for k, v in feat.items() if k not in TEXT})
        if m:
            hit = fb_hit[label]
            row.update({k: float(hit[k]) for k in ("mp", "ltpc_best_l", "ltpc_best_l_minus_mp")})
        else:
            hit = hitrates(src / "hitrate" / f"{label}.csv")
            row.update({k: hit[k] for k in ("mp", "ltpc_best_l", "ltpc_best_l_minus_mp")})
        rows.append(row)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "per_trace.csv", rows)

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        key = f"fb_rd{r['rd_a']}_fd{r['fd_a']}" if r["rd_a"] else str(r["label"])
        groups[key].append(r)
    metrics = [k for k in rows[0] if k not in ("label", "rd_a", "fd_a", "seed")]
    summary = []
    # 実 trace を先に、FlowBench は rd・fd の順に並べる
    for key in sorted(groups, key=lambda k: (k.startswith("fb_"), k)):
        group = groups[key]
        row = {"condition": key, "seeds": len(group)}
        for name in metrics:
            row[name] = sum(float(r[name]) for r in group) / len(group)
        summary.append(row)
    write_csv(out / "by_condition.csv", summary)
    write_csv(out / "brief.csv", [{"condition": r["condition"]} | {k: round(r[k], 4) for k in BRIEF} for r in summary])


if __name__ == "__main__":
    main()
