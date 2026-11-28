#!/usr/bin/env python3
"""variable_index_crc_epoch.sh の出力から、trace・容量ごとのミス率 (%) の表を作る。

列: 固定 /18、静的最適（L）、事前計算 1M（L）、shadow(traffic)・rover の epoch 別（閾値ごと）。
最後に /18 比のミス率削減の平均と最悪を出す。
"""
import argparse
import csv
import glob
import os
from collections import defaultdict


def params(s):
    return dict(kv.split("=", 1) for kv in s.split(";") if "=" in kv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = []
    for f in sorted(glob.glob(os.path.join(a.dir, "*.csv"))):
        if f.endswith("_series.csv"):
            continue
        with open(f) as fp:
            rows += list(csv.DictReader(fp))

    # key=(trace,cap) -> col -> (miss%, note)
    tab = defaultdict(dict)
    best = {}
    for r in rows:
        k = (r["trace"], int(r["capacity"]))
        miss = 100.0 * (1 - float(r["hit_rate"]))
        p = params(r["params"])
        pol = r["policy"]
        if pol == "static":
            L = int(p["L"])
            if L == 18:
                tab[k]["fixed18"] = (miss, "/18")
            if k not in best or miss < best[k][0]:
                best[k] = (miss, f"/{L}")
        elif pol == "static-switch":
            tab[k]["train1M"] = (miss, f"/{p['L']}")
        elif pol == "shadow":
            if "rover" in p.get("cand", ""):
                kind = "rover"
            elif p.get("sample") == "traffic":
                kind = "traffic"
            else:
                kind = "ideal"  # 全候補・全 set の shadow（variable_index_crc_ideal_shadow.sh）
            col = f"{kind}_ep{int(p['epoch'])//1000}k_th{p['th']}"
            tab[k][col] = (miss, f"→/{r['final_l']}、{r['switches']}回")
    for k, v in best.items():
        tab[k]["oracle"] = v

    cols = ["fixed18", "oracle", "train1M"]
    shadow_cols = sorted({c for v in tab.values() for c in v if c not in cols},
                         key=lambda c: (c.split("_")[0], c.split("_")[2], int(c.split("_")[1][2:-1])))
    cols += shadow_cols

    with open(a.out, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["trace", "capacity"] + [x for c in cols for x in (c, c + "_note")])
        for k in sorted(tab):
            w.writerow(list(k) + [x for c in cols for x in
                                  ((f"{tab[k][c][0]:.4f}", tab[k][c][1]) if c in tab[k] else ("", ""))])

    print("| 方式 | /18 比のミス率削減 平均 (pt) | 最悪 (pt) | ケース数 |")
    print("|---|---:|---:|---:|")
    for c in cols[1:]:
        d = [tab[k]["fixed18"][0] - tab[k][c][0] for k in tab if c in tab[k] and "fixed18" in tab[k]]
        if d:
            print(f"| {c} | {sum(d)/len(d):.3f} | {min(d):.3f} | {len(d)} |")


if __name__ == "__main__":
    main()
