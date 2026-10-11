#!/usr/bin/env python3
"""variable_index_explore の各方式を、トレース全体での静的最適 L との差 (pt) で比べる。

usage: summarize_variable_index_policies.py <out_dir> <file suffix>"""
import collections
import csv
import glob
import re
import sys

out_dir, suffix = sys.argv[1], sys.argv[2]
static = {}
for path in glob.glob(f"{out_dir}/*_static.csv"):
    for r in csv.DictReader(open(path)):
        if r["policy"] == "static":
            static.setdefault((r["trace"], int(r["capacity"])), {})[int(r["params"].split("=")[1])] = float(r["hit_rate"]) * 100

by_cfg = collections.defaultdict(dict)
for path in glob.glob(f"{out_dir}/*{suffix}.csv"):
    for r in csv.DictReader(open(path)):
        key = (r["trace"], int(r["capacity"]))
        if key in static:
            by_cfg[(r["policy"], re.sub(r";dualwin=\d+", "", r["params"]))][key] = (float(r["hit_rate"]) * 100 - max(static[key].values()), int(r["switches"]), int(r["table_bits"]))

keys = sorted({k for d in by_cfg.values() for k in d})
print("| policy | params | mean | worst | " + " | ".join(f"{t[:6]}@{c}" for t, c in keys) + " |")
print("|---|---|---:|---:|" + "---:|" * len(keys))
rows = []
for cfg, d in by_cfg.items():
    gaps = [d[k][0] for k in keys if k in d]
    rows.append((sum(gaps) / len(gaps), min(gaps), cfg, d))
rows.sort(key=lambda x: -x[0])
for mean, worst, cfg, d in rows:
    cells = " | ".join(f"{d[k][0]:+.2f}" if k in d else "" for k in keys)
    print(f"| {cfg[0]} | {cfg[1]} | {mean:+.2f} | {worst:+.2f} | {cells} |")
ref = {k: v[18] - max(v.values()) for k, v in static.items()}
print(f"| static | L=18 | {sum(ref[k] for k in keys)/len(keys):+.2f} | {min(ref[k] for k in keys):+.2f} | " + " | ".join(f"{ref[k]:+.2f}" for k in keys) + " |")
