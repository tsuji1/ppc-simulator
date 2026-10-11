#!/usr/bin/env python3
"""#78 の主な比較表（固定 /18・静的最適・各方式）を variable_index_explore の結果 CSV から作る。

usage: summarize_variable_index_vs18.py <out_dir> [<out_dir for WIDE rows to compare> ...]

各方式の条件は #78 中間報告（2026-10-08）と同じ。
"""
import collections
import csv
import glob
import re
import sys
from pathlib import Path

METHODS = {
    "shadow(traffic)": ("_shadow_sweep", "shadow", r"sample=traffic;div=8;epoch=100000;th=0.01;.*switch=keep"),
    "hot64+shadow": ("_shadow_cheap", "shadow", r"div=16;epoch=1000000;th=0.002;.*tagbits=10;.*hot=64"),
    "領域別L(2^16)": ("_region-online", "region-online-majority", r"^g=16;(table=2\^16;)?update=miss;cnt=3$"),
    "近傍±2+rover": ("_shadow_rover", "shadow", r"cand=cur\+-2\+rover;.*epoch=100000;"),
    "way分割 4@/16+4@/20": ("_split", "split", r"^A=4way@/16;B=4way@/20$"),
}


def load(out_dir: Path):
    static = collections.defaultdict(dict)
    for f in glob.glob(str(out_dir / "*_static.csv")):
        if Path(f).name.startswith("phase"):
            continue
        for r in csv.DictReader(open(f)):
            if r["policy"] == "static":
                static[(r["trace"], int(r["capacity"]))][int(r["params"][2:])] = float(r["hit_rate"]) * 100
    methods = {}
    for name, (suffix, policy, pattern) in METHODS.items():
        d = {}
        for f in glob.glob(str(out_dir / f"*{suffix}.csv")):
            if Path(f).name.startswith("phase"):
                continue
            for r in csv.DictReader(open(f)):
                if r["policy"] == policy and re.search(pattern, r["params"]):
                    d[(r["trace"], int(r["capacity"]))] = float(r["hit_rate"]) * 100
        methods[name] = d
    return static, methods


def table(static, methods, label=""):
    names = [n for n in METHODS if n != "way分割 4@/16+4@/20"]
    print(f"| trace | 容量 | 固定/18 | 静的最適 | " + " | ".join(names) + " |")
    print("|---|---:|---:|---:|" + "---:|" * len(names))
    agg = collections.defaultdict(list)
    for key in sorted(k for k in static if k[1] in (1024, 4096, 16384)):
        st = static[key]
        b18 = st[18]
        best = max(st, key=st.get)
        cells = [f"{st[best]:.2f} (/{best}, {st[best] - b18:+.2f})"]
        agg["静的最適"].append(st[best] - b18)
        for n in names:
            v = methods[n].get(key)
            cells.append("–" if v is None else f"{v:.2f} ({v - b18:+.2f})")
            if v is not None:
                agg[n].append(v - b18)
        print(f"| {key[0]}{label} | {key[1]} | {b18:.2f} | " + " | ".join(cells) + " |")
    for title, fn in (("平均", lambda v: sum(v) / len(v)), ("最小", min), ("最大", max)):
        print(f"| **/18比の{title}** | | | " + " | ".join(f"{fn(agg[n]):+.2f}" for n in ["静的最適"] + names) + " |")


def vs_static(static, methods):
    print("| 方式 | 平均 | 最悪 |")
    print("|---|---:|---:|")
    rows = {"固定 /18": {k: v[18] for k, v in static.items()}}
    rows.update(methods)
    for name, d in rows.items():
        diffs = [d[k] - max(static[k].values()) for k in static if k[1] in (1024, 4096, 16384) and k in d]
        print(f"| {name} | {sum(diffs) / len(diffs):+.2f} | {min(diffs):+.2f} |")


if __name__ == "__main__":
    out_dir = Path(sys.argv[1])
    static, methods = load(out_dir)
    table(static, methods)
    print()
    vs_static(static, methods)
