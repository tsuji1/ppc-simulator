#!/usr/bin/env python3
"""variable_index_explore の shadow スイープを静的最適 L と比べる。

各 (trace, capacity) で gap = shadow hit% - 静的最適 hit% を計算し、設定ごとに
全ケースの平均 gap / 最悪 gap を出す。"""
import collections
import re
import csv
import glob
import sys

out_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts/reports/variable_index_hw"
suffix = sys.argv[2] if len(sys.argv) > 2 else "_shadow_sweep"

static = {}
for path in glob.glob(f"{out_dir}/*_static.csv"):
    for r in csv.DictReader(open(path)):
        if r["policy"] == "static":
            key = (r["trace"], int(r["capacity"]))
            static.setdefault(key, {})[int(r["params"].split("=")[1])] = float(r["hit_rate"]) * 100

by_cfg = collections.defaultdict(dict)
rows_all = []
for path in glob.glob(f"{out_dir}/*{suffix}.csv"):
    for r in csv.DictReader(open(path)):
        key = (r["trace"], int(r["capacity"]))
        if key not in static:
            continue
        best = max(static[key].values())
        gap = float(r["hit_rate"]) * 100 - best
        cfg = re.sub(r";dualwin=\d+", "", r["params"]) 
        by_cfg[cfg][key] = (gap, int(r["switches"]), int(r["shadow_bits"]), r["l_hist"])
        rows_all.append(r)

summary = []
for cfg, d in by_cfg.items():
    gaps = [v[0] for v in d.values()]
    summary.append((sum(gaps) / len(gaps), min(gaps), cfg, len(gaps)))
summary.sort(reverse=True)
print("## 設定ごとの静的最適との差 (pt)：平均 / 最悪 / ケース数（上位 15、下位 5）")
for s in summary[:15]:
    print(f"{s[0]:+.3f} {s[1]:+.3f} n={s[3]} {s[2]}")
print("...")
for s in summary[-5:]:
    print(f"{s[0]:+.3f} {s[1]:+.3f} n={s[3]} {s[2]}")

print("\n## 最良設定のケース別")
best_cfg = summary[0][2]
for key, v in sorted(by_cfg[best_cfg].items()):
    st = static[key]
    bl = max(st, key=st.get)
    print(f"{key[0]:11s} cap={key[1]:6d} gap={v[0]:+.3f} static-best=/{bl} {st[bl]:.2f} fixed18={st[18]:.2f} switches={v[1]} shadow_bits={v[2]} L={v[3]}")

ref18 = {k: v[18] - max(v.values()) for k, v in static.items()}
print("\n参考: 固定 /18 の差 平均 %+.3f 最悪 %+.3f" % (sum(ref18.values()) / len(ref18), min(ref18.values())))
