# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib",
#   "pandas",
# ]
# ///

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DATES = ("2025-09-27", "2025-12-27", "2026-03-27")
CONFIGS = (
    ("mp-24-20-2048-2048", "MP /24+/20"),
    ("ps-ideal-cap2048", "PS ideal"),
    ("ps-index5-cap2048", "PS index5"),
)
GRAY = "#5F6368"
RED = "#D4211C"
BLUE = "#3569A4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix-root",
        type=Path,
        default=Path("scripts/reports/anon_tree_lpm_remap/target-matrix-exact-k30-r10"),
    )
    parser.add_argument(
        "--nyc-root",
        type=Path,
        default=Path(
            "scripts/reports/anon_tree_lpm_remap/"
            "nyc-to-wide-exact-seeded-k30-r10"
        ),
    )
    parser.add_argument(
        "--wide-reference-root",
        type=Path,
        default=Path(
            "scripts/reports/anon_tree_lpm_remap/order-experiment-c61440"
        ),
    )
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def experiment_dir(
    dataset: str, date: str, matrix_root: Path, nyc_root: Path
) -> Path:
    if dataset == "Chicago":
        return matrix_root / "chicago-exact" / date / "exact-seeded"
    if dataset == "NYC":
        return nyc_root / date / "exact-seeded"
    if dataset == "anon-WIDE":
        return matrix_root / "wide-exact" / date / "exact-seeded"
    raise ValueError(dataset)


def read_lpm_experiment(path: Path) -> tuple[dict[str, str], pd.DataFrame]:
    summary = pd.read_csv(path / "method_summary.csv")
    baseline = summary.loc[summary["method"] == "baseline-anonymized"].iloc[0]
    best = summary.loc[summary["best_transformed"].astype(str).str.lower() == "true"]
    if best.empty:
        raise RuntimeError(f"best transformed row is missing: {path}")
    best_row = best.iloc[0]
    exact_rows = summary.loc[summary["method"].astype(str).str.contains("exact-block")]
    exact_row = exact_rows.iloc[-1] if not exact_rows.empty else best_row

    distribution = pd.read_csv(path / "lpm_distribution_comparison.csv")
    baseline_dist = distribution.loc[
        distribution["method"] == "baseline-anonymized",
        ["lpm_prefix_length", "ratio", "target_ratio"],
    ].copy()
    transformed_dist = distribution.loc[
        distribution["method"] == best_row["method"],
        ["lpm_prefix_length", "ratio"],
    ].copy()
    transformed_dist = transformed_dist.rename(columns={"ratio": "transformed_ratio"})
    merged = baseline_dist.merge(transformed_dist, on="lpm_prefix_length", how="inner")
    merged = merged.rename(columns={"ratio": "baseline_ratio"})

    baseline_tv = float(baseline["tv_distance"])
    transformed_tv = float(best_row["tv_distance"])
    record = {
        "packets": str(int(best_row["packets"])),
        "baseline_tv": f"{baseline_tv:.12f}",
        "transformed_tv": f"{transformed_tv:.12f}",
        "distribution_overlap": f"{1.0 - transformed_tv:.12f}",
        "relative_tv_reduction": (
            f"{(baseline_tv - transformed_tv) / baseline_tv:.12f}"
            if baseline_tv
            else "0.000000000000"
        ),
        "method": str(best_row["method"]),
        "flip_count": str(int(best_row["flip_count"])),
        "exact_block_candidates": str(int(exact_row["exact_block_candidates"])),
        "exact_rounds": str(int(exact_row["exact_rounds"])),
        "exact_theoretical_assignments": str(
            int(exact_row["exact_theoretical_assignments"])
        ),
        "exact_visited_leaves": str(int(exact_row["exact_visited_leaves"])),
        "exact_pruned_assignments": str(int(exact_row["exact_pruned_assignments"])),
        "exact_elapsed": str(exact_row["exact_elapsed"]),
    }
    return record, merged


def final_hitrate(path: Path) -> dict[str, float]:
    frame = pd.read_csv(path)
    result: dict[str, float] = {}
    for config_id, _ in CONFIGS:
        rows = frame.loc[frame["config_id"] == config_id].sort_values(
            ["cumulative_packets", "window_index"]
        )
        if rows.empty:
            raise RuntimeError(f"{config_id} is missing: {path}")
        result[config_id] = float(rows.iloc[-1]["cumulative_hit_rate_pct"])
    return result


def hitrate_paths(
    dataset: str,
    date: str,
    matrix_root: Path,
    nyc_root: Path,
    wide_reference_root: Path,
) -> tuple[Path, Path, Path | None]:
    if dataset == "Chicago":
        root = matrix_root / "hitrate" / "chicago"
        return (
            root / "baseline-anonymous.csv",
            root / f"target-{date}.csv",
            None,
        )
    if dataset == "NYC":
        root = nyc_root / "hitrate"
        return root / "original-nyc.csv", root / f"target-{date}.csv", None
    if dataset == "anon-WIDE":
        old = wide_reference_root / "hitrate"
        new = matrix_root / "hitrate" / "wide"
        return (
            old / f"{date}-baseline-anonymized.csv",
            new / f"transformed-{date}.csv",
            old / f"{date}-non-anonymized.csv",
        )
    raise ValueError(dataset)


def plot_lpm(
    dataset: str,
    distributions: dict[tuple[str, str], pd.DataFrame],
    output: Path,
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.2), sharex=True)
    for axis, date in zip(axes, DATES):
        frame = distributions[(dataset, date)]
        x = frame["lpm_prefix_length"]
        axis.plot(
            x,
            frame["baseline_ratio"] * 100,
            color=GRAY,
            linewidth=2.2,
            marker="o",
            markersize=2.8,
            label="Anonymous",
        )
        axis.plot(
            x,
            frame["transformed_ratio"] * 100,
            color=RED,
            linewidth=2.2,
            marker="o",
            markersize=2.8,
            label="Transformed",
        )
        axis.plot(
            x,
            frame["target_ratio"] * 100,
            color=BLUE,
            linewidth=2.2,
            marker="o",
            markersize=2.8,
            label="Non-anonymous target",
        )
        axis.set_title(date, fontweight="bold")
        axis.set_xlim(0, 32)
        axis.set_xticks((0, 8, 16, 24, 32))
        axis.grid(axis="y", color="#D9DEE7", linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_xlabel("Longest matching prefix length")
    axes[0].set_ylabel("Packet share (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.suptitle(f"{dataset}: LPM distribution matching", y=0.98, fontsize=16)
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.92),
        ncol=3,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.82))
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_tv(lpm: pd.DataFrame, output: Path) -> None:
    labels = [f"{row.dataset}\n{row.target_date[2:]}" for row in lpm.itertuples()]
    x = np.arange(len(labels))
    width = 0.36
    fig, axis = plt.subplots(figsize=(15, 6))
    baseline = lpm["baseline_tv"].to_numpy()
    transformed = lpm["transformed_tv"].to_numpy()
    bars0 = axis.bar(x - width / 2, baseline, width, color=GRAY, label="Anonymous")
    bars1 = axis.bar(x + width / 2, transformed, width, color=RED, label="Transformed")
    axis.bar_label(bars0, fmt="%.3f", padding=2, fontsize=8)
    axis.bar_label(bars1, fmt="%.3f", padding=2, fontsize=8)
    axis.set_ylabel("TV distance to non-anonymous target (lower is better)")
    axis.set_xticks(x, labels)
    axis.grid(axis="y", color="#D9DEE7", linewidth=0.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_miss(hitrate: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(16, 13), sharex=True)
    labels = [
        f"{row.dataset}\n{row.target_date[2:]}"
        for row in hitrate.drop_duplicates(["dataset", "target_date"]).itertuples()
    ]
    x = np.arange(len(labels))
    width = 0.24
    for axis, (config_id, config_label) in zip(axes, CONFIGS):
        frame = hitrate.loc[hitrate["config_id"] == config_id].reset_index(drop=True)
        axis.bar(
            x - width,
            frame["baseline_miss_pct"],
            width,
            color=GRAY,
            label="Anonymous",
        )
        axis.bar(
            x,
            frame["transformed_miss_pct"],
            width,
            color=RED,
            label="Transformed",
        )
        target = frame["nonanonymous_miss_pct"].to_numpy(dtype=float)
        axis.bar(
            x + width,
            target,
            width,
            color=BLUE,
            label="Non-anonymous",
        )
        axis.set_title(config_label, loc="left", fontweight="bold")
        axis.set_ylabel("Miss rate (%)")
        axis.grid(axis="y", color="#D9DEE7", linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    axes[-1].set_xticks(x, labels)
    axes[0].legend(frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_miss_slide(hitrate: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.4))
    labels = [
        f"{row.dataset}\n{row.target_date[2:]}"
        for row in hitrate.drop_duplicates(["dataset", "target_date"]).itertuples()
    ]
    x = np.arange(len(labels))
    width = 0.24
    for axis, (config_id, config_label) in zip(axes, CONFIGS):
        frame = hitrate.loc[hitrate["config_id"] == config_id].reset_index(drop=True)
        axis.bar(
            x - width,
            frame["baseline_miss_pct"],
            width,
            color=GRAY,
            label="Anonymous",
        )
        axis.bar(
            x,
            frame["transformed_miss_pct"],
            width,
            color=RED,
            label="Transformed",
        )
        axis.bar(
            x + width,
            frame["nonanonymous_miss_pct"].to_numpy(dtype=float),
            width,
            color=BLUE,
            label="Non-anonymous",
        )
        axis.set_title(config_label, fontweight="bold")
        axis.set_ylabel("Miss rate (%)")
        axis.set_xticks(x, labels, rotation=55, ha="right", fontsize=7)
        axis.grid(axis="y", color="#D9DEE7", linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        legend_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.99),
        ncol=3,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_markdown(lpm: pd.DataFrame, hitrate: pd.DataFrame, output: Path) -> None:
    lines = [
        "# 非匿名LPM分布への匿名トレース木回転",
        "",
        "## 条件",
        "",
        "- 目的関数: 非匿名トレースのLPM長分布とのTV距離",
        "- 回転深さ: /24、class境界制約なし",
        "- 3候補順序のgreedy探索後、最良写像を初期値に厳密ブロック探索",
        "- 厳密探索: 原則30変数・最大10ラウンド、各ブロックはbranch-and-boundで完全被覆",
        "- anon-WIDE 2026-03-27のみ、k=30実行がセッション上限で終了したため28変数で再実行",
        "- Chicagoは6,338,755 packet、NYCとanon-WIDEは10,000,000 packet",
        "- anon-WIDEは各日付の匿名トレースを同日付の非匿名分布へ合わせた",
        "",
        "## LPM分布",
        "",
        "| anonymous trace | target | baseline TV | transformed TV | overlap | reduction |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in lpm.itertuples():
        lines.append(
            f"| {row.dataset} | {row.target_date} | {row.baseline_tv:.6f} | "
            f"{row.transformed_tv:.6f} | {row.distribution_overlap:.2%} | "
            f"{row.relative_tv_reduction:.2%} |"
        )
    lines.extend(
        [
            "",
            "![TV distance](tv_distance_matrix.png)",
            "",
            "![Chicago LPM](chicago_lpm_distribution_3targets.png)",
            "",
            "![NYC LPM](nyc_lpm_distribution_3targets.png)",
            "",
            "![anon-WIDE LPM](wide_lpm_distribution_3targets.png)",
            "",
            "## Cache miss rate",
            "",
            "warm cache、8-way。MPは/24+/20・2048+2048、PSはcapacity 2048。",
            "ChicagoとNYCには対応する非匿名cache結果を置かず、anon-WIDEのみ同日非匿名を併記した。",
            "",
            "![miss rate](miss_rate_matrix.png)",
            "",
            "数値は `hitrate_summary.csv`、LPMの数値は `lpm_summary.csv` に保存した。",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or args.matrix_root
    output_dir.mkdir(parents=True, exist_ok=True)

    lpm_records: list[dict[str, object]] = []
    distributions: dict[tuple[str, str], pd.DataFrame] = {}
    for dataset in ("Chicago", "NYC", "anon-WIDE"):
        for date in DATES:
            path = experiment_dir(dataset, date, args.matrix_root, args.nyc_root)
            record, distribution = read_lpm_experiment(path)
            record.update(
                {
                    "dataset": dataset,
                    "target_date": date,
                    "result_dir": str(path),
                }
            )
            lpm_records.append(record)
            distributions[(dataset, date)] = distribution

    lpm = pd.DataFrame(lpm_records)
    numeric_lpm = (
        "packets",
        "baseline_tv",
        "transformed_tv",
        "distribution_overlap",
        "relative_tv_reduction",
        "flip_count",
        "exact_block_candidates",
        "exact_rounds",
        "exact_theoretical_assignments",
        "exact_visited_leaves",
        "exact_pruned_assignments",
    )
    for column in numeric_lpm:
        lpm[column] = pd.to_numeric(lpm[column])
    lpm.to_csv(output_dir / "lpm_summary.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    hitrate_records: list[dict[str, object]] = []
    for dataset in ("Chicago", "NYC", "anon-WIDE"):
        for date in DATES:
            baseline_path, transformed_path, nonanonymous_path = hitrate_paths(
                dataset,
                date,
                args.matrix_root,
                args.nyc_root,
                args.wide_reference_root,
            )
            baseline = final_hitrate(baseline_path)
            transformed = final_hitrate(transformed_path)
            nonanonymous = (
                final_hitrate(nonanonymous_path) if nonanonymous_path else {}
            )
            for config_id, config_label in CONFIGS:
                baseline_hit = baseline[config_id]
                transformed_hit = transformed[config_id]
                target_hit = nonanonymous.get(config_id, np.nan)
                hitrate_records.append(
                    {
                        "dataset": dataset,
                        "target_date": date,
                        "config_id": config_id,
                        "config_label": config_label,
                        "baseline_hit_pct": baseline_hit,
                        "transformed_hit_pct": transformed_hit,
                        "nonanonymous_hit_pct": target_hit,
                        "baseline_miss_pct": 100.0 - baseline_hit,
                        "transformed_miss_pct": 100.0 - transformed_hit,
                        "nonanonymous_miss_pct": (
                            100.0 - target_hit if not np.isnan(target_hit) else np.nan
                        ),
                        "transformed_minus_baseline_hit_pp": (
                            transformed_hit - baseline_hit
                        ),
                    }
                )
    hitrate = pd.DataFrame(hitrate_records)
    hitrate.to_csv(output_dir / "hitrate_summary.csv", index=False)

    for dataset, filename in (
        ("Chicago", "chicago_lpm_distribution_3targets.png"),
        ("NYC", "nyc_lpm_distribution_3targets.png"),
        ("anon-WIDE", "wide_lpm_distribution_3targets.png"),
    ):
        plot_lpm(dataset, distributions, output_dir / filename)
    plot_tv(lpm, output_dir / "tv_distance_matrix.png")
    plot_miss(hitrate, output_dir / "miss_rate_matrix.png")
    plot_miss_slide(hitrate, output_dir / "miss_rate_matrix_slide.png")
    write_markdown(lpm, hitrate, output_dir / "FINAL_REPORT_JA.md")

    print(f"wrote {output_dir / 'lpm_summary.csv'}")
    print(f"wrote {output_dir / 'hitrate_summary.csv'}")
    print(f"wrote {output_dir / 'FINAL_REPORT_JA.md'}")


if __name__ == "__main__":
    main()
