# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""issue #123：summarize_issue123_xor_index.py の per_case.csv から追加の図を作る。

  miss_by_capacity.png : 容量ごとのミス率（11 trace の平均）。direct・XOR・CRC（上位 L bit、先頭 1M で選んだ L）と、
                         XOR で上位 24 bit・IP 全体（32 bit）を畳み込んだもの
  trace_heatmap.png    : trace × 容量ごとの、XOR と CRC の direct 比（ミス率の変化率）
  top10_share.png      : ミスの多い上位 10% の set が全ミスに占める割合（先頭 1M で選んだ L）

使い方: uv run --script plot_issue123_xor_index.py PER_CASE_CSV OUT_DIR
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

# dataviz skill の既定 palette（categorical の先頭 5 色、diverging は blue↔red で中央は gray）
C = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "magenta": "#e87ba4"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
TRACE_ORDER = ["wide0927", "wide1227", "wide0327", "chicago", "sanjose", "nyc", "jpix", "sinet",
               "caida0320a", "caida0320b", "caida1120a"]
TRACE_LABEL = {"wide0927": "WIDE 2025-09", "wide1227": "WIDE 2025-12", "wide0327": "WIDE 2026-03",
               "chicago": "Chicago", "sanjose": "San Jose", "nyc": "NYC", "jpix": "Academic A",
               "sinet": "Academic B", "caida0320a": "CAIDA 25-03 A", "caida0320b": "CAIDA 25-03 B",
               "caida1120a": "CAIDA 25-11 A"}


def setup_font():
    for font in ("Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic"):
        if any(font in f.name for f in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = font
            break
    plt.rcParams.update({"axes.edgecolor": INK2, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "text.color": INK})


def style(ax):
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def load(path: Path):
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            for k in r:
                if k not in ("trace", "index"):
                    r[k] = float(r[k])
            r["way"], r["capacity"] = int(r["way"]), int(r["capacity"])
            rows.append(r)
    return rows


def miss_by_capacity(rows, out: Path):
    by = {(r["trace"], r["index"], r["way"], r["capacity"]): r for r in rows}
    ways = sorted({r["way"] for r in rows})
    caps = sorted({r["capacity"] for r in rows})
    traces = sorted({r["trace"] for r in rows})
    series = [
        ("direct（現行、上位 L bit）", "direct", "miss_train", C["blue"], "-"),
        ("XOR 畳み込み（上位 L bit）", "xor", "miss_train", C["orange"], "-"),
        ("CRC32（上位 L bit、参考）", "crc", "miss_train", C["aqua"], "-"),
        ("XOR 畳み込み（上位 24 bit 全部）", "xor", "miss_L24", C["yellow"], "--"),
        ("XOR 畳み込み（IP 全体 32 bit）", "xor", "miss_L32", C["magenta"], "--"),
    ]
    fig, axes = plt.subplots(1, len(ways), figsize=(5.2 * len(ways), 4.2), sharey=True)
    for ax, way in zip(axes, ways):
        for label, idx, col, color, ls in series:
            ys = [100 * sum(by[(t, idx, way, c)][col] for t in traces) / len(traces) for c in caps]
            ax.plot(caps, ys, color=color, lw=2, ls=ls, marker="o", ms=5, label=label)
            # 上位 L bit の 3 本は重なるので、direct と破線の 2 本だけ右端に値を書く
            if idx == "direct" or ls == "--":
                ax.annotate(f"{ys[-1]:.2f}%", (caps[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                            va="center", fontsize=8, color=INK2)
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
        ax.set_xticks(caps, [f"{c // 1024}K" for c in caps])
        ax.set_xlim(caps[0] * 0.8, caps[-1] * 1.9)
        ax.set_title(f"{way}-way", fontsize=11)
        ax.set_xlabel("容量（entry）")
        style(ax)
    axes[0].set_ylabel("ミス率（%、11 trace の平均、対数）")
    axes[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.suptitle("上位 L bit の中で混ぜても変わらず、L より下の bit まで混ぜると大きく悪化する", fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def trace_heatmap(rows, out: Path):
    by = {(r["trace"], r["index"], r["way"], r["capacity"]): r for r in rows}
    ways = sorted({r["way"] for r in rows})
    caps = sorted({r["capacity"] for r in rows})
    traces = [t for t in TRACE_ORDER if any(r["trace"] == t for r in rows)]
    cmap = LinearSegmentedColormap.from_list("div", [C["blue"], "#f0efec", "#e34948"])
    norm = TwoSlopeNorm(vmin=-15, vcenter=0, vmax=15)
    fig, axes = plt.subplots(1, 4, figsize=(15, 5.2), sharey=True)
    im = None
    for ax, (idx, way) in zip(axes, [(i, w) for i in ("xor", "crc") for w in ways]):
        grid = [[100 * (by[(t, idx, way, c)]["miss_train"] / by[(t, "direct", way, c)]["miss_train"] - 1)
                 for c in caps] for t in traces]
        im = ax.imshow(grid, cmap=cmap, norm=norm, aspect="auto")
        for i, row in enumerate(grid):
            for j, v in enumerate(row):
                ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=7.5,
                        color="white" if abs(v) > 9 else INK)
        ax.set_xticks(range(len(caps)), [f"{c // 1024}K" for c in caps])
        ax.set_yticks(range(len(traces)), [TRACE_LABEL.get(t, t) for t in traces])
        name = "XOR 畳み込み" if idx == "xor" else "CRC32（参考）"
        ax.set_title(f"{name}・{way}-way", fontsize=10)
        ax.set_xlabel("容量（entry）")
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=axes, shrink=0.8, pad=0.01)
    cb.set_label("direct 比のミス率変化（%、青 = 良い、±15% で飽和）")
    fig.suptitle("trace ごとの direct 比（上位 L bit の中で混ぜた場合、L は先頭 1M で選択）", fontsize=11)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def top10_share(rows, out: Path):
    ways = sorted({r["way"] for r in rows})
    caps = sorted({r["capacity"] for r in rows})
    acc = defaultdict(list)
    for r in rows:
        acc[(r["index"], r["way"], r["capacity"])].append(r["top10_train"])
    fig, axes = plt.subplots(1, len(ways), figsize=(5.2 * len(ways), 3.8), sharey=True)
    w = 0.26
    for ax, way in zip(axes, ways):
        for k, (idx, color, label) in enumerate([("direct", C["blue"], "direct"), ("xor", C["orange"], "XOR 畳み込み"),
                                                 ("crc", C["aqua"], "CRC32（参考）")]):
            ys = [100 * sum(acc[(idx, way, c)]) / len(acc[(idx, way, c)]) for c in caps]
            xs = [i + (k - 1) * w for i in range(len(caps))]
            ax.bar(xs, ys, width=w - 0.03, color=color, label=label, edgecolor="white", linewidth=1)
        ax.set_xticks(range(len(caps)), [f"{c // 1024}K" for c in caps])
        ax.set_title(f"{way}-way", fontsize=11)
        ax.set_xlabel("容量（entry）")
        ax.set_ylim(0, 100)
        style(ax)
        ax.grid(False, axis="x")
    axes[0].set_ylabel("上位 10% の set のミス占有（%）")
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    fig.suptitle("ミスの集中は index 関数では変わらない（11 trace の平均）", fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main():
    per_case, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_font()
    rows = load(per_case)
    miss_by_capacity(rows, out_dir / "miss_by_capacity.png")
    trace_heatmap(rows, out_dir / "trace_heatmap.png")
    top10_share(rows, out_dir / "top10_share.png")
    print(f"wrote {out_dir}/miss_by_capacity.png, trace_heatmap.png, top10_share.png")


if __name__ == "__main__":
    main()
