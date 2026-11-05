# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""issue #123：direct / XOR 畳み込み / CRC32 の index を比べる表と図（第 2 版）。

入力は scripts/run_issue123_xor_index.sh の出力ディレクトリ（`<trace>_static-train_<index>_w<way>.csv`）。
各 CSV には、先頭 1M packet で選んだ L で評価した行（policy=static-train）と、
同じ評価区間（先頭 1M 以降）での各固定 L（/9〜/32）の行（policy=static-eval）がある。

出力（OUT_DIR）:
  per_trace.csv          trace × way × 容量ごとのミス率 [%]。各 index で選んだ L のミス率と、
                         direct が選んだ L に XOR・CRC をそろえたときのミス率
  extremes.md            direct 比の変化が大きい組（上位 8 件）の表
  miss_by_capacity.{pdf,png}   容量ごとのミス率（11 trace の算術平均）
  trace_heatmap.{pdf,png}      trace ごとの direct 比（各 index が自分で選んだ L。% と pt を併記）
  trace_heatmap_sameL.{pdf,png} 同上、ただし XOR・CRC も direct が選んだ L で比べる
  top10_share.{pdf,png}        ミスの多い上位 10% の set が全ミスに占める割合
  vs_L.{pdf,png}               L ごとのミス率（direct の最良 L に対する比の幾何平均）

使い方: uv run --script plot_issue123_xor_index.py RAW_DIR OUT_DIR
"""

from __future__ import annotations

import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
import matplotlib.ticker  # noqa: E402

# docs/guidelines/figures.md：categorical 1〜4 を使い、同じ方式は図をまたいで同じ色にする
BLUE, ORANGE, AQUA, PURPLE, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#7a5ad6", "#8a8984"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
STYLE = {  # index → (色, 線種, マーカー, 塗り)
    "direct": (BLUE, "-", "o", True),
    "xor": (ORANGE, "--", "s", True),
    "crc": (AQUA, ":", "^", False),
}
NAME = {"direct": "direct（現行）", "xor": "XOR 畳み込み", "crc": "CRC32"}
# 表示名と並び順は docs/guidelines/figures.md に合わせる
TRACES = [("wide0927", "WIDE 25-09"), ("wide1227", "WIDE 25-12"), ("wide0327", "WIDE 26-03"),
          ("jpix", "Academic A 2018-05"), ("sinet", "Academic B 2018-05"), ("sanjose", "San Jose"),
          ("chicago", "Chicago"), ("nyc", "New York"), ("caida0320a", "CAIDA 25-03 A"),
          ("caida0320b", "CAIDA 25-03 B"), ("caida1120a", "CAIDA 25-11 A")]
LABEL = dict(TRACES)
FNAME = re.compile(r"^(?P<trace>.+)_static-train_(?P<index>[a-z]+)_w(?P<way>\d+)\.csv$")
COND = "11 trace の全長、L は先頭 1M packet で選び、評価は先頭 1M 以降"


def load(raw: Path):
    """(trace, index, way, cap) -> {"L": 選んだ L, "miss": ミス率, "top": 上位10%占有, "eval": {L: (miss, top)}, "pkts": 評価 packet 数}"""
    d: dict = defaultdict(lambda: {"eval": {}})
    for p in sorted(raw.glob("*_static-train_*_w*.csv")):
        m = FNAME.match(p.name)
        if not m:
            continue
        with p.open() as f:
            for r in csv.DictReader(f):
                k = (m["trace"], m["index"], int(m["way"]), int(r["capacity"]))
                miss, top = 1 - float(r["hit_rate"]), float(r["top10_miss_share"])
                if r["policy"] == "static-train":
                    d[k].update(L=int(re.search(r"L=(\d+)", r["params"]).group(1)), miss=miss, top=top,
                                pkts=int(r["packets"]))
                else:
                    d[k]["eval"][int(r["final_l"])] = (miss, top)
    return d


def per_trace(d):
    rows = []
    keys = sorted({(t, w, c) for t, _, w, c in d})
    order = {t: i for i, (t, _) in enumerate(TRACES)}
    for t, w, c in sorted(keys, key=lambda k: (k[1], k[2], order.get(k[0], 99))):
        base = d[(t, "direct", w, c)]
        row = {"trace": LABEL.get(t, t), "way": w, "capacity": c, "packets": base["pkts"],
               "direct_L": base["L"], "direct_miss_pct": 100 * base["miss"]}
        for idx in ("xor", "crc"):
            x = d[(t, idx, w, c)]
            same = x["eval"][base["L"]][0]
            row |= {f"{idx}_L": x["L"], f"{idx}_miss_pct": 100 * x["miss"],
                    f"{idx}_vs_direct_pct": 100 * (x["miss"] / base["miss"] - 1),
                    f"{idx}_vs_direct_pt": 100 * (x["miss"] - base["miss"]),
                    f"{idx}_miss_sameL_pct": 100 * same,
                    f"{idx}_sameL_vs_direct_pct": 100 * (same / base["miss"] - 1)}
        rows.append(row)
    return rows


def write_csv(path: Path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})


def write_extremes(path: Path, rows, n=8):
    cand = [(r, idx) for r in rows for idx in ("xor", "crc")]
    cand.sort(key=lambda x: -abs(x[0][f"{x[1]}_vs_direct_pct"]))
    lines = ["| 方式 | trace | way | 容量 | direct（L・ミス率） | 方式（L・ミス率） | 変化率 | 差 | 同じ L にそろえた変化率 |",
             "|---|---|---:|---:|---|---|---:|---:|---:|"]
    for r, idx in cand[:n]:
        lines.append(f"| {NAME[idx]} | {r['trace']} | {r['way']} | {r['capacity']} | /{r['direct_L']}・{r['direct_miss_pct']:.3f}% "
                     f"| /{r[f'{idx}_L']}・{r[f'{idx}_miss_pct']:.3f}% | {r[f'{idx}_vs_direct_pct']:+.1f}% "
                     f"| {r[f'{idx}_vs_direct_pt']:+.3f}pt | {r[f'{idx}_sameL_vs_direct_pct']:+.1f}% |")
    path.write_text("\n".join(lines) + "\n")


def setup():
    for font in ("Noto Sans CJK JP", "BIZ UDGothic", "IPAexGothic"):
        if any(font in f.name for f in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = font
            break
    plt.rcParams.update({"axes.edgecolor": INK2, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "text.color": INK, "pdf.fonttype": 42})


def style(ax):
    ax.grid(True, axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def save(fig, out: Path, stem: str):
    for ext in ("pdf", "png"):
        fig.savefig(out / f"{stem}.{ext}", dpi=150, bbox_inches="tight")
    plt.close(fig)


def caps_ways(d):
    return sorted({k[3] for k in d}), sorted({k[2] for k in d}), [t for t, _ in TRACES if any(k[0] == t for k in d)]


def miss_by_capacity(d, out):
    caps, ways, traces = caps_ways(d)
    series = [(f"{NAME['direct']}・上位 L bit", "direct", None) + STYLE["direct"],
              (f"{NAME['xor']}・上位 L bit", "xor", None) + STYLE["xor"],
              (f"{NAME['crc']}・上位 L bit", "crc", None) + STYLE["crc"],
              ("XOR 畳み込み・上位 24 bit 全部", "xor", 24, PURPLE, "-.", "D", False),
              ("XOR 畳み込み・IP 全体 32 bit", "xor", 32, GRAY, (0, (1, 1)), "v", False)]
    fig, axes = plt.subplots(1, len(ways), figsize=(5.4 * len(ways), 4.3), sharey=True)
    for ax, w in zip(axes, ways):
        for label, idx, fixL, color, ls, mk, fill in series:
            ys = []
            for c in caps:
                v = [d[(t, idx, w, c)]["miss"] if fixL is None else d[(t, idx, w, c)]["eval"][fixL][0] for t in traces]
                ys.append(100 * sum(v) / len(v))
            ax.plot(caps, ys, color=color, ls=ls, lw=1.8, marker=mk, ms=6,
                    mfc=color if fill else "white", mec=color, label=label)
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
        ax.set_xticks(caps, [f"{c // 1024}K" for c in caps])
        ax.set_title(f"{w}-way", fontsize=11)
        ax.set_xlabel("総 entry 数")
        style(ax)
    axes[0].set_ylabel("ミス率 [%]（対数軸、11 trace の算術平均）")
    axes[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.suptitle(f"index の作り方とミス率（{COND}）", fontsize=11)
    fig.tight_layout()
    save(fig, out, "miss_by_capacity")


def heatmap(d, out, same_l: bool):
    caps, ways, traces = caps_ways(d)
    cmap = LinearSegmentedColormap.from_list("div", [BLUE, "#f0efec", "#e34948"])
    norm = TwoSlopeNorm(vmin=-30, vcenter=0, vmax=30)
    fig, axes = plt.subplots(1, 4, figsize=(17, 6.4), sharey=True)
    im = None
    for ax, (idx, w) in zip(axes, [(i, w) for i in ("xor", "crc") for w in ways]):
        grid, text = [], []
        for t in traces:
            g, tx = [], []
            for c in caps:
                b = d[(t, "direct", w, c)]
                m = d[(t, idx, w, c)]["eval"][b["L"]][0] if same_l else d[(t, idx, w, c)]["miss"]
                g.append(100 * (m / b["miss"] - 1))
                tx.append(f"{g[-1]:+.0f}%\n{100 * (m - b['miss']):+.2f}pt")
            grid.append(g)
            text.append(tx)
        im = ax.imshow(grid, cmap=cmap, norm=norm, aspect="auto")
        for i, row in enumerate(grid):
            for j, v in enumerate(row):
                ax.text(j, i, text[i][j], ha="center", va="center", fontsize=6.8, linespacing=1.1,
                        color="white" if abs(v) > 18 else INK)
        ax.set_xticks(range(len(caps)), [f"{c // 1024}K" for c in caps])
        ax.set_yticks(range(len(traces)), [LABEL[t] for t in traces])
        ax.set_title(f"{NAME[idx]}・{w}-way", fontsize=10)
        ax.set_xlabel("総 entry 数")
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=axes, shrink=0.75, pad=0.01)
    cb.set_label("direct 比のミス率の変化率 [%]（青 = 減る、±30% で飽和）")
    how = "XOR・CRC も direct が選んだ L にそろえて比較" if same_l else "各方式が先頭 1M で自分の L を選んで比較"
    fig.suptitle(f"trace ごとの direct 比：上段は変化率 [%]、下段はミス率の差 [pt]（上位 L bit だけを使う index。{how}）",
                 fontsize=11)
    save(fig, out, "trace_heatmap_sameL" if same_l else "trace_heatmap")


def top10_share(d, out):
    caps, ways, traces = caps_ways(d)
    hatch = {"direct": "", "xor": "///", "crc": ".."}
    fig, axes = plt.subplots(1, len(ways), figsize=(5.4 * len(ways), 3.8), sharey=True)
    wd = 0.26
    for ax, w in zip(axes, ways):
        for k, idx in enumerate(("direct", "xor", "crc")):
            color = STYLE[idx][0]
            ys = [100 * sum(d[(t, idx, w, c)]["top"] for t in traces) / len(traces) for c in caps]
            ax.bar([i + (k - 1) * wd for i in range(len(caps))], ys, width=wd - 0.04, color=color,
                   hatch=hatch[idx], edgecolor="white", lw=0.8, label=NAME[idx])
        ax.set_xticks(range(len(caps)), [f"{c // 1024}K" for c in caps])
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_ylim(0, 100)
        ax.set_title(f"{w}-way", fontsize=11)
        ax.set_xlabel("総 entry 数")
        style(ax)
    axes[0].set_ylabel("上位 10% の set のミス占有 [%]")
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    fig.suptitle(f"ミスの集中（11 trace の算術平均、{COND}）", fontsize=11)
    fig.tight_layout()
    save(fig, out, "top10_share")


def vs_l(d, out):
    caps, ways, traces = caps_ways(d)
    fig, axes = plt.subplots(len(ways), len(caps), figsize=(3.1 * len(caps), 2.9 * len(ways)), sharex=True, squeeze=False)
    for i, w in enumerate(ways):
        for j, c in enumerate(caps):
            ax = axes[i][j]
            for idx in ("direct", "xor", "crc"):
                color, ls, mk, fill = STYLE[idx]
                ls_ = sorted(d[(traces[0], idx, w, c)]["eval"])
                ys = []
                for L in ls_:
                    logs = [math.log(d[(t, idx, w, c)]["eval"][L][0]
                                     / min(m for LL, (m, _) in d[(t, "direct", w, c)]["eval"].items() if LL <= 24))
                            for t in traces]
                    ys.append(math.exp(sum(logs) / len(logs)))
                ax.plot(ls_, ys, color=color, ls=ls, lw=1.6, marker=mk, ms=3, markevery=3,
                        mfc=color if fill else "white", mec=color, label=NAME[idx])
            ax.axvline(24, color=GRAY, lw=0.8, ls=":")
            ax.set_yscale("log")
            ax.set_yticks([1, 2, 4, 8, 16], ["1", "2", "4", "8", "16"])
            ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
            ax.set_ylim(0.9, 18)
            ax.set_title(f"{c // 1024}K entry・{w}-way", fontsize=9)
            style(ax)
            if i == len(ways) - 1:
                ax.set_xlabel("index 長 L（/24 より右は IP 全体まで使う）", fontsize=8)
            if j == 0:
                ax.set_ylabel("direct の最良 L との比\n（対数軸、幾何平均）", fontsize=8)
    axes[0][0].legend(fontsize=7, frameon=False, loc="upper left")
    fig.suptitle(f"index 長 L とミス率（{COND}）", fontsize=11)
    fig.tight_layout()
    save(fig, out, "vs_L")


def main():
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    setup()
    d = load(raw)
    if not d:
        sys.exit(f"no input CSV in {raw}")
    rows = per_trace(d)
    write_csv(out / "per_trace.csv", rows)
    write_extremes(out / "extremes.md", rows)
    miss_by_capacity(d, out)
    heatmap(d, out, same_l=False)
    heatmap(d, out, same_l=True)
    top10_share(d, out)
    vs_l(d, out)
    print(f"wrote {out}（{len(rows)} 行）")


if __name__ == "__main__":
    main()
