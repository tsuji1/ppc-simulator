#!/usr/bin/env python3
"""variable_index_explore の static 結果から、トレース・容量ごとの静的最適 L と ideal-leaf を表にする。"""
import collections
import csv
import glob
import sys

out_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts/reports/variable_index_hw"
print("| trace | capacity | best static L | hit% | /16 | /18 | /20 | /24 | ideal-leaf |")
print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for path in sorted(glob.glob(f"{out_dir}/*_static.csv")):
    rows = list(csv.DictReader(open(path)))
    by_cap = collections.defaultdict(dict)
    for r in rows:
        by_cap[int(r["capacity"])][r["policy"] + ":" + r["params"]] = float(r["hit_rate"]) * 100
    for cap, d in sorted(by_cap.items()):
        static = {int(k.split("L=")[1]): v for k, v in d.items() if k.startswith("static:")}
        best = max(static, key=static.get)
        ideal = next(v for k, v in d.items() if k.startswith("ideal-leaf"))
        print(f"| {rows[0]['trace']} | {cap} | /{best} | {static[best]:.2f} | {static[16]:.2f} | {static[18]:.2f} | {static[20]:.2f} | {static[24]:.2f} | {ideal:.2f} |")
