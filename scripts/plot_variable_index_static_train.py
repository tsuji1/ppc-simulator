"""事前計算（static-train、direct index）の結果を、トレースごとのミス率の棒グラフにする（issue #78）。

入力: scripts/reports/variable_index_hw/<dir>/{trace}_static-train.csv（<dir> は第1引数、既定 direct_static-train）
出力: scripts/reports/variable_index_hw/<dir>/miss_rate_static_train.png

ミス率は評価区間（1M パケット目以降）の 1 - hit_rate。どの方式も同じ評価区間で比べている。
"""

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

font_manager.fontManager.addfont("/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf")

DIR = Path(__file__).resolve().parent / "reports/variable_index_hw" / (sys.argv[1] if len(sys.argv) > 1 else "direct_static-train")
FULL = DIR.name.endswith("_full")
TRACES = [("wide202603", "WIDE 2026-03"), ("nyc", "NYC"), ("chicago", "Chicago"), ("sanjose", "San Jose")]
CAPS = [1024, 2048, 4096, 8192, 16384]
# (key, 凡例, 色)。固定 /18 は基準なので中立のグレー、他は参照パレットの slot 1-4 を固定順で使う
SERIES = [
    ("fixed18", "固定 /18", "#8b8a85"),
    ("train10000", "事前計算 先頭10k", "#2a78d6"),
    ("train100000", "事前計算 先頭100k", "#eb6834"),
    ("train1000000", "事前計算 先頭1M", "#1baf7a"),
    ("oracle", "静的最適（評価区間で選んだ上限）", "#eda100"),
]

plt.rcParams.update({
    "font.family": "IPAexGothic",
    "font.size": 10,
    "axes.edgecolor": "#b5b4ae",
    "axes.labelcolor": "#52514e",
    "xtick.color": "#52514e",
    "ytick.color": "#52514e",
    "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb",
})


def load(trace):
    """capacity -> {series key: (miss %, L)}"""
    out = {}
    for r in csv.DictReader(open(DIR / f"{trace}_static-train.csv")):
        cap = int(r["capacity"])
        miss = (1 - float(r["hit_rate"])) * 100
        L = int(r["params"].split("L=")[1])
        d = out.setdefault(cap, {"eval": {}})
        if r["policy"] == "static-eval":
            d["eval"][L] = miss
        else:
            d["train" + r["params"].split(";")[0].split("=")[1]] = (miss, L)
    for d in out.values():
        d["fixed18"] = (d["eval"][18], 18)
        best = min(d["eval"], key=d["eval"].get)
        d["oracle"] = (d["eval"][best], best)
    return out


n = len(SERIES)
width = 0.8 / n


def draw(ax, trace, title):
    data = load(trace)
    for i, (key, label, color) in enumerate(SERIES):
        xs = [c + (i - (n - 1) / 2) * width for c in range(len(CAPS))]
        ys = [data[cap][key][0] for cap in CAPS]
        ax.bar(xs, ys, width=width * 0.9, color=color, label=label, edgecolor="#fcfcfb", linewidth=0.8)
        # 選ばれた L を棒の上に小さく書く（固定 /18 は自明なので省く）
        if key != "fixed18":
            for x, cap in zip(xs, CAPS):
                ax.text(x, data[cap][key][0], f"/{data[cap][key][1]}", ha="center", va="bottom",
                        fontsize=6.5, color="#52514e", rotation=90)
    ax.set_title(title, loc="left", fontsize=12, color="#0b0b0b")
    ax.set_xticks(range(len(CAPS)), [f"{c:,}" for c in CAPS])
    ax.set_xlabel("エントリ数")
    ax.set_ylabel("ミス率 (%)")
    ax.margins(y=0.15)
    ax.grid(axis="y", color="#e5e4df", linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


fig, axes = plt.subplots(2, 2, figsize=(12, 7.5))
for ax, (trace, title) in zip(axes.flat, TRACES):
    draw(ax, trace, title)

handles, labels = axes.flat[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="upper center", ncol=n, frameon=False, fontsize=10, bbox_to_anchor=(0.5, 1.0))
span = ("全長: WIDE 206M、NYC 91M、San Jose 38M、Chicago 5.3M" if FULL else "約9M、Chicago は約5.3M")
fig.text(0.5, 0.005, f"8-way、direct index（上位 L bit prefix の下位 bit）。評価区間は 1M パケット目以降（{span}）。"
         "\n棒の上の数字は選ばれた index 長。縦軸はトレースごとに異なる。",
         ha="center", fontsize=8.5, color="#52514e")
fig.tight_layout(rect=(0, 0.045, 1, 0.95))
out = DIR / "miss_rate_static_train.png"
fig.savefig(out, dpi=200)
print(out)

# トレースごとに 1 枚ずつ（スライド用）
for trace, title in TRACES:
    f, ax = plt.subplots(figsize=(8, 4.8))
    draw(ax, trace, title)
    f.legend(*ax.get_legend_handles_labels(), loc="upper center", ncol=3, frameon=False, fontsize=9,
             bbox_to_anchor=(0.5, 1.0))
    f.text(0.5, 0.01, f"8-way、direct index。評価区間は 1M パケット目以降（{span}）。棒の上の数字は選ばれた index 長。",
           ha="center", fontsize=7.5, color="#52514e")
    f.tight_layout(rect=(0, 0.04, 1, 0.88))
    o = DIR / f"miss_rate_static_train_{trace}.png"
    f.savefig(o, dpi=200)
    plt.close(f)
    print(o)
