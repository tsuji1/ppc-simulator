# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""issue #123：direct / XOR 畳み込み / CRC の index を比べる集計と図。

入力は scripts/run_issue123_xor_index.sh が出す `<trace>_static-train_<index>_w<way>.csv`。
static-train は「先頭 1M packet で L を選び、残りで評価」した行（policy=static-train）と、
同じ評価区間での各固定 L の行（policy=static-eval）を持つ。

出力:
  per_case.csv : trace × 容量 × way × index ごとのミス率（先頭 1M で選んだ L、評価区間での最良 L（/24 まで、/32 まで）、
                 /18、/24、/32 固定）と、上位 10% の set のミス占有
  summary.csv  : 11 trace の平均。ミス率は同じ trace・容量・way の direct（先頭 1M で選んだ L）に対する変化率
  vs_L.png     : L ごとのミス率（direct の評価区間最良に対する比の幾何平均）

使い方: uv run --script summarize_issue123_xor_index.py IN_DIR OUT_DIR
"""

from __future__ import annotations

import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

INDEXES = ["direct", "xor", "crc"]
# 検証済みの既定 categorical palette の先頭 3 色（dataviz skill の palette.md）
COLORS = {"direct": "#2a78d6", "xor": "#eb6834", "crc": "#1baf7a"}
LABELS = {"direct": "direct（上位 L bit の下位 k bit）", "xor": "XOR 畳み込み（上位 L bit）", "crc": "CRC32（上位 L bit、参考）"}
NAME_RE = re.compile(r"^(?P<trace>.+)_static-train_(?P<index>[a-z]+)_w(?P<way>\d+)\.csv$")


def load(in_dir: Path):
    """(trace, index, way, cap) -> {"train": (L, miss, top10), "eval": {L: (miss, top10)}}"""
    data: dict = defaultdict(lambda: {"train": None, "eval": {}})
    for p in sorted(in_dir.glob("*_static-train_*_w*.csv")):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        with p.open() as f:
            for row in csv.DictReader(f):
                key = (m["trace"], m["index"], int(m["way"]), int(row["capacity"]))
                miss = 1.0 - float(row["hit_rate"])
                top = float(row["top10_miss_share"])
                if row["policy"] == "static-train":
                    l = int(re.search(r"L=(\d+)", row["params"]).group(1))
                    data[key]["train"] = (l, miss, top)
                elif row["policy"] == "static-eval":
                    data[key]["eval"][int(row["final_l"])] = (miss, top)
    return data


def per_case(data):
    rows = []
    for (trace, index, way, cap), d in sorted(data.items()):
        ev = d["eval"]
        l_tr, m_tr, top_tr = d["train"]
        opt24 = min((l for l in ev if l <= 24), key=lambda l: ev[l][0])
        opt32 = min(ev, key=lambda l: ev[l][0])
        rows.append({
            "trace": trace, "index": index, "way": way, "capacity": cap,
            "train_L": l_tr, "miss_train": m_tr, "top10_train": top_tr,
            "opt24_L": opt24, "miss_opt24": ev[opt24][0],
            "opt32_L": opt32, "miss_opt32": ev[opt32][0],
            "miss_L18": ev[18][0], "miss_L24": ev[24][0], "miss_L32": ev[32][0],
            "top10_L18": ev[18][1], "top10_L24": ev[24][1],
        })
    return rows


def summarize(rows):
    base = {(r["trace"], r["way"], r["capacity"]): r for r in rows if r["index"] == "direct"}
    groups = defaultdict(list)
    for r in rows:
        groups[(r["way"], r["capacity"], r["index"])].append(r)
    out = []
    for (way, cap, index), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], INDEXES.index(kv[0][2]))):
        def rel(col):
            v = [r[col] / base[(r["trace"], way, cap)]["miss_train"] - 1 for r in rs]
            return sum(v) / len(v)
        better = sum(r["miss_train"] < base[(r["trace"], way, cap)]["miss_train"] - 1e-12 for r in rs)
        worse = sum(r["miss_train"] > base[(r["trace"], way, cap)]["miss_train"] + 1e-12 for r in rs)
        out.append({
            "way": way, "capacity": cap, "index": index, "traces": len(rs),
            "mean_miss_train": sum(r["miss_train"] for r in rs) / len(rs),
            "vs_direct_train": rel("miss_train"),
            "vs_direct_opt24": rel("miss_opt24"),
            "vs_direct_L24": rel("miss_L24"),
            "vs_direct_L32": rel("miss_L32"),
            "better_traces": better, "worse_traces": worse,
            "mean_train_L": sum(r["train_L"] for r in rs) / len(rs),
            "mean_top10_train": sum(r["top10_train"] for r in rs) / len(rs),
        })
    return out


def write_csv(path: Path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})


def plot(data, out: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for font in ("Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic"):
        if any(font in f.name for f in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = font
            break
    ways = sorted({k[2] for k in data})
    caps = sorted({k[3] for k in data})
    traces = sorted({k[0] for k in data})
    fig, axes = plt.subplots(len(ways), len(caps), figsize=(3.0 * len(caps), 2.8 * len(ways)), sharex=True, squeeze=False)
    for i, way in enumerate(ways):
        for j, cap in enumerate(caps):
            ax = axes[i][j]
            for index in INDEXES:
                ls = sorted(data[(traces[0], index, way, cap)]["eval"])
                ys = []
                for l in ls:
                    logs = []
                    for t in traces:
                        ref = min(m for ll, (m, _) in data[(t, "direct", way, cap)]["eval"].items() if ll <= 24)
                        logs.append(math.log(data[(t, index, way, cap)]["eval"][l][0] / ref))
                    ys.append(math.exp(sum(logs) / len(logs)))
                ax.plot(ls, ys, color=COLORS[index], lw=2, label=LABELS[index])
            ax.axvline(24, color="#a3a29c", lw=1, ls=":")
            ax.set_yscale("log")
            ax.set_title(f"{cap} entry・{way}-way", fontsize=10)
            ax.grid(True, color="#e6e5e0", lw=0.6)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            if i == len(ways) - 1:
                ax.set_xlabel("index 長 L（/24 より右は IP 全体まで畳み込む）", fontsize=8)
            if j == 0:
                ax.set_ylabel("ミス率 / direct の最良 L（幾何平均）", fontsize=8)
    axes[0][0].legend(fontsize=7, frameon=False, loc="upper left")
    fig.suptitle(f"index 関数ごとの L とミス率（{len(traces)} trace、評価は先頭 1M 以降）", fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150)


def main():
    in_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    data = load(in_dir)
    if not data:
        sys.exit(f"no input CSV in {in_dir}")
    rows = per_case(data)
    write_csv(out_dir / "per_case.csv", rows)
    write_csv(out_dir / "summary.csv", summarize(rows))
    plot(data, out_dir / "vs_L.png")
    print(f"wrote {out_dir}/per_case.csv, summary.csv, vs_L.png ({len(rows)} cases)")


if __name__ == "__main__":
    main()
