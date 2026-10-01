#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Plot simple before/after evidence for the two hot WIDE /16 groups."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "scripts/reports"
INPUT = REPORTS / "wide_xor_ps16_subtree_diagnosis"
OUTPUT = INPUT / "simple_hot_prefix_graphs"

CASES = (
    (
        "wide09",
        "WIDE 2025-09 → 2026-03 LPM分布",
        REPORTS / "wide_xor_ps16_diagnosis/wide09_original/unified_cacheline_by_set.csv",
        REPORTS / "wide_xor_ps16_diagnosis/wide09_to_202603/unified_cacheline_by_set.csv",
    ),
    (
        "wide12",
        "WIDE 2025-12 → 2026-03 LPM分布",
        REPORTS / "wide_xor_ps16_diagnosis/wide12_original/unified_cacheline_by_set.csv",
        REPORTS / "wide_xor_ps16_diagnosis/wide12_to_202603/unified_cacheline_by_set.csv",
    ),
)

TARGET_PREFIXES = ("150.65.0.0/16", "203.178.0.0/16")
GRAY = "#777777"
RED = "#d7191c"
BLUE = "#377eb8"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def set_rows(path: Path) -> dict[int, dict[str, str]]:
    return {int(row["set_idx"]): row for row in read_csv(path)}


def short_prefix(cidr: str) -> str:
    return cidr.replace(".0.0/16", "/16")


def add_values(ax, bars, values: list[int]) -> None:
    maximum = max(values) if values else 0
    pad = max(maximum * 0.025, 0.4)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + pad,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=11,
        )


def grouped_bars(
    ax,
    labels: list[str],
    before: list[int],
    after: list[int],
    title: str,
    ylabel: str,
    way_line: bool = False,
) -> None:
    x = list(range(len(labels)))
    width = 0.34
    before_bars = ax.bar([v - width / 2 for v in x], before, width, color=GRAY, label="変換前")
    after_bars = ax.bar([v + width / 2 for v in x], after, width, color=RED, label="変換後")
    add_values(ax, before_bars, before)
    add_values(ax, after_bars, after)
    ax.set_xticks(x, labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=15, pad=13)
    ax.grid(axis="y", alpha=0.23)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    if way_line:
        ax.axhline(8, color=BLUE, linestyle="--", linewidth=1.8, label="8-way上限")
    ax.legend(frameon=False, ncol=3 if way_line else 2)
    upper = max(before + after + ([8] if way_line else [0]))
    ax.set_ylim(0, upper * 1.20 + 1)


def save_single(
    path: Path,
    case_title: str,
    labels: list[str],
    before: list[int],
    after: list[int],
    title: str,
    ylabel: str,
    way_line: bool = False,
    note: str | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(10.8, 6.2))
    grouped_bars(ax, labels, before, after, title, ylabel, way_line)
    fig.suptitle(case_title, fontsize=18, fontweight="bold", y=0.98)
    if note:
        fig.text(0.5, 0.015, note, ha="center", fontsize=10, color="#444444")
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 0.94))
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update({
        "font.family": "Noto Sans CJK JP",
        "font.size": 12,
        "axes.unicode_minus": False,
    })
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, object]] = []

    for name, case_title, before_set_path, after_set_path in CASES:
        mappings = {
            row["before_prefix16"]: row
            for row in read_csv(INPUT / f"{name}_prefix16_mapping.csv")
        }
        rows = [mappings[prefix] for prefix in TARGET_PREFIXES]
        before_sets = set_rows(before_set_path)
        after_sets = set_rows(after_set_path)

        labels = [
            f"{short_prefix(row['before_prefix16'])}\n→ {short_prefix(row['after_prefix16'])}\n"
            f"({float(row['packet_share_percent']):.1f}% of packets)"
            for row in rows
        ]
        before_nodes = [int(row["before_descendant_route_nodes"]) for row in rows]
        after_nodes = [int(row["after_descendant_route_nodes"]) for row in rows]
        before_lpm = [int(row["before_distinct_lpm_entries_touched"]) for row in rows]
        after_lpm = [int(row["after_distinct_lpm_entries_touched"]) for row in rows]
        before_miss = [before_sets[int(row["before_set"])]["second_miss"] for row in rows]
        after_miss = [after_sets[int(row["after_set"])]["second_miss"] for row in rows]
        before_miss = [int(value) for value in before_miss]
        after_miss = [int(value) for value in after_miss]

        save_single(
            OUTPUT / f"{name}_hot_prefix_child_nodes.png",
            case_title,
            labels,
            before_nodes,
            after_nodes,
            "ホットな /16 が、子ノードの多い /16 へ移動",
            "/16 配下のルーティングprefix数",
        )
        save_single(
            OUTPUT / f"{name}_hot_prefix_lpm_entries.png",
            case_title,
            labels,
            before_lpm,
            after_lpm,
            "実際に参照したLPMエントリ数が8-wayを大幅に超過",
            "異なるLPMエントリ数",
            way_line=True,
        )
        save_single(
            OUTPUT / f"{name}_hot_prefix_second_miss.png",
            case_title,
            labels,
            before_miss,
            after_miss,
            "移動先setで繰り返しミスが多発",
            "setのsecond-missカウンタ",
            note="ミス数は通信群単独ではなく、その通信群が支配する移動元／移動先set全体のカウンタ",
        )

        fig, axes = plt.subplots(1, 3, figsize=(18, 5.8))
        grouped_bars(axes[0], labels, before_nodes, after_nodes, "① 子ノード数", "prefix数")
        grouped_bars(axes[1], labels, before_lpm, after_lpm, "② 参照LPMエントリ数", "エントリ数", True)
        grouped_bars(axes[2], labels, before_miss, after_miss, "③ 移動元／先setの繰り返しミス", "second-missカウンタ")
        fig.suptitle(case_title + "：ホット通信群の移動とPS /16ミス", fontsize=20, fontweight="bold")
        fig.text(
            0.5,
            0.012,
            "灰色＝変換前、赤＝変換後。ミス数は各通信群が支配するset全体の値。",
            ha="center",
            fontsize=11,
            color="#444444",
        )
        fig.tight_layout(rect=(0, 0.045, 1, 0.93))
        fig.savefig(OUTPUT / f"{name}_hot_prefix_evidence_3panel.png", dpi=200, bbox_inches="tight")
        plt.close(fig)

        for idx, row in enumerate(rows):
            summary_rows.append({
                "case": name,
                "before_prefix16": row["before_prefix16"],
                "after_prefix16": row["after_prefix16"],
                "packets": row["packets"],
                "packet_share_percent": row["packet_share_percent"],
                "before_child_nodes": before_nodes[idx],
                "after_child_nodes": after_nodes[idx],
                "before_lpm_entries": before_lpm[idx],
                "after_lpm_entries": after_lpm[idx],
                "before_set": row["before_set"],
                "after_set": row["after_set"],
                "before_set_second_miss": before_miss[idx],
                "after_set_second_miss": after_miss[idx],
            })

    with (OUTPUT / "hot_prefix_evidence.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)


if __name__ == "__main__":
    main()
