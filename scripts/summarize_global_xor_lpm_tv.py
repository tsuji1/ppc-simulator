# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib",
#   "pandas",
# ]
# ///

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path("scripts/reports/global-xor-lpm-tv-exhaustive24")
DATES = ("2025-09-27", "2025-12-27", "2026-03-27")
DATASETS = (("chicago", "Chicago"), ("nyc", "NYC"), ("anon-wide", "anon-WIDE"))
CONFIGS = (
    ("mp-24-20-2048-2048", "MP /24+/20"),
    ("ps-ideal-cap2048", "PS ideal"),
    ("ps-index5-cap2048", "PS index5"),
)
GRAY = "#666666"
RED = "#C62828"
BLUE = "#3569A4"
GRID = "#D9DEE7"


def final_hitrate(path: Path) -> dict[str, float]:
    frame = pd.read_csv(path)
    result: dict[str, float] = {}
    for config_id, _ in CONFIGS:
        rows = frame.loc[frame["config_id"] == config_id].sort_values(
            ["cumulative_packets", "window_index"]
        )
        result[config_id] = float(rows.iloc[-1]["cumulative_hit_rate_pct"])
    return result


def read_distribution(dataset: str, date: str) -> pd.DataFrame:
    path = ROOT / dataset / date
    measured = pd.read_csv(path / "lpm_distribution.csv")
    target = pd.read_csv(path / "reference_lpm_distribution.csv")
    frame = measured.merge(target, on="lpm_prefix_length")
    before_total = frame["before_count"].sum()
    after_total = frame["after_count"].sum()
    target_total = frame["count"].sum()
    frame["anonymous_pct"] = frame["before_count"] / before_total * 100
    frame["transformed_pct"] = frame["after_count"] / after_total * 100
    frame["nonanonymous_pct"] = frame["count"] / target_total * 100
    return frame


def plot_lpm(dataset_label: str, distributions: dict[str, pd.DataFrame], output: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(17.2, 5.0), sharey=True)
    for axis, date in zip(axes, DATES):
        frame = distributions[date]
        x = frame["lpm_prefix_length"]
        axis.plot(x, frame["anonymous_pct"], color=GRAY, linewidth=2.2, label="Anonymous")
        axis.plot(x, frame["transformed_pct"], color=RED, linewidth=2.2, label="Transformed")
        axis.plot(x, frame["nonanonymous_pct"], color=BLUE, linewidth=2.2, label="Non-anonymous")
        axis.set_title(date, fontsize=13, fontweight="bold")
        axis.set_xlim(0, 32)
        axis.set_xticks((0, 8, 16, 24, 32))
        axis.set_xlabel("Longest matching prefix length")
        axis.grid(axis="y", color=GRID, linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Packet share (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=3, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_tv(summary: pd.DataFrame, output: Path) -> None:
    labels = [f"{row.dataset}\n{row.target_date[2:]}" for row in summary.itertuples()]
    x = np.arange(len(labels))
    width = 0.36
    fig, axis = plt.subplots(figsize=(14.5, 5.5))
    before = axis.bar(x - width / 2, summary["before_tv"], width, color=GRAY, label="Anonymous")
    after = axis.bar(x + width / 2, summary["after_tv"], width, color=RED, label="Transformed")
    axis.bar_label(before, fmt="%.3f", padding=2, fontsize=8)
    axis.bar_label(after, fmt="%.3f", padding=2, fontsize=8)
    axis.set_ylabel("TV distance (lower is better)")
    axis.set_xticks(x, labels)
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_miss(dataset: str, label: str, miss: pd.DataFrame, output: Path) -> None:
    frame = miss.loc[miss["dataset"] == label]
    fig, axes = plt.subplots(1, 3, figsize=(16.8, 4.9))
    x = np.arange(len(DATES))
    if dataset == "anon-wide":
        width = 0.24
        offsets = (-width, 0, width)
        columns = (
            ("anonymous_miss_pct", GRAY, "Anonymous"),
            ("transformed_miss_pct", RED, "Transformed"),
            ("nonanonymous_miss_pct", BLUE, "Non-anonymous"),
        )
    else:
        width = 0.34
        offsets = (-width / 2, width / 2)
        columns = (
            ("anonymous_miss_pct", GRAY, "Anonymous"),
            ("transformed_miss_pct", RED, "Transformed"),
        )
    for axis, (config_id, config_label) in zip(axes, CONFIGS):
        rows = frame.loc[frame["config_id"] == config_id].set_index("target_date").loc[list(DATES)]
        for offset, (column, color, series_label) in zip(offsets, columns):
            bars = axis.bar(x + offset, rows[column], width, color=color, label=series_label)
            axis.bar_label(bars, fmt="%.2f", padding=2, fontsize=7)
        axis.set_title(config_label, fontweight="bold")
        axis.set_xticks(x, [date[2:] for date in DATES])
        axis.set_ylabel("Miss rate (%)")
        axis.grid(axis="y", color=GRID, linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.99), ncol=len(columns), frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    lpm_records: list[dict[str, object]] = []
    all_distributions: dict[tuple[str, str], pd.DataFrame] = {}
    for dataset, label in DATASETS:
        for date in DATES:
            summary = pd.read_csv(ROOT / dataset / date / "search_summary.csv").iloc[0]
            lpm_records.append(
                {
                    "dataset": label,
                    "target_date": date,
                    "packets": int(summary["packets"]),
                    "patterns": int(summary["patterns"]),
                    "mask_hex": summary["mask_hex"],
                    "before_tv": float(summary["before_tv"]),
                    "after_tv": float(summary["after_tv"]),
                    "tv_reduction_pct": (
                        100 * (float(summary["before_tv"]) - float(summary["after_tv"]))
                        / float(summary["before_tv"])
                    ),
                    "search_seconds": float(summary["search_seconds"]),
                }
            )
            all_distributions[(dataset, date)] = read_distribution(dataset, date)
    lpm = pd.DataFrame(lpm_records)
    lpm.to_csv(ROOT / "lpm_summary.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    hitrate_root = ROOT / "hitrate"
    original_city = {
        "Chicago": final_hitrate(hitrate_root / "chicago-original.csv"),
        "NYC": final_hitrate(hitrate_root / "nyc-original.csv"),
    }
    miss_records: list[dict[str, object]] = []
    for dataset, label in DATASETS:
        for date in DATES:
            if dataset == "anon-wide":
                anonymous = final_hitrate(hitrate_root / f"wide-original-{date}.csv")
                transformed = final_hitrate(hitrate_root / f"wide-transformed-{date}.csv")
                nonanonymous = final_hitrate(hitrate_root / f"wide-nonanon-{date}.csv")
            else:
                anonymous = original_city[label]
                transformed = final_hitrate(hitrate_root / f"{dataset}-transformed-{date}.csv")
                nonanonymous = {}
            for config_id, config_label in CONFIGS:
                miss_records.append(
                    {
                        "dataset": label,
                        "target_date": date,
                        "config_id": config_id,
                        "config_label": config_label,
                        "anonymous_miss_pct": 100 - anonymous[config_id],
                        "transformed_miss_pct": 100 - transformed[config_id],
                        "nonanonymous_miss_pct": (
                            100 - nonanonymous[config_id] if nonanonymous else np.nan
                        ),
                    }
                )
    miss = pd.DataFrame(miss_records)
    miss.to_csv(ROOT / "miss_rate_summary.csv", index=False)

    for dataset, label in DATASETS:
        plot_lpm(
            label,
            {date: all_distributions[(dataset, date)] for date in DATES},
            ROOT / f"{dataset}-lpm.png",
        )
        plot_miss(dataset, label, miss, ROOT / f"{dataset}-miss-rate.png")
    plot_tv(lpm, ROOT / "tv-distance.png")
    print(lpm.to_string(index=False))
    print(f"wrote {ROOT / 'miss_rate_summary.csv'}")


if __name__ == "__main__":
    main()
