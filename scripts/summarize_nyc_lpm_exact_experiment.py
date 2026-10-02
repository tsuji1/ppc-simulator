# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib>=3.8",
# ]
# ///

"""Compare NYC greedy LPM remapping with exact block branch-and-bound runs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


ORDER_LABELS = {"mass": "Mass-first", "top-down": "Top-down", "bottom-up": "Bottom-up"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--greedy-root", type=Path, required=True)
    parser.add_argument("--exact-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def greedy_winners(root: Path) -> dict[str, dict[str, str]]:
    winners: dict[str, dict[str, str]] = {}
    for row in read_csv(root / "rotation_order_results.csv"):
        date = row["date"]
        if date not in winners or float(row["tv_distance"]) < float(winners[date]["tv_distance"]):
            winners[date] = row
    return winners


def exact_results(root: Path, dates: list[str]) -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for date in dates:
        rows = read_csv(root / date / "exact-seeded" / "method_summary.csv")
        selected = next(row for row in rows if row["best_transformed"] == "true")
        results[date] = selected
    return results


def method_distribution(path: Path, method: str) -> tuple[list[float], list[float]]:
    target = [0.0] * 33
    values = [0.0] * 33
    for row in read_csv(path):
        length = int(row["lpm_prefix_length"])
        target[length] = float(row["target_ratio"]) * 100.0
        if row["method"] == method:
            values[length] = float(row["ratio"]) * 100.0
    return target, values


def write_comparison_csv(path: Path, greedy: dict[str, dict[str, str]], exact: dict[str, dict[str, str]]) -> None:
    fields = [
        "target_date", "greedy_order", "greedy_method", "greedy_tv", "exact_method", "exact_tv",
        "exact_overlap", "tv_improvement", "exact_block_candidates", "exact_rounds",
        "exact_theoretical_assignments", "exact_visited_leaves", "exact_pruned_assignments",
        "exact_elapsed", "exact_trace_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for date in sorted(greedy):
            old = greedy[date]
            new = exact[date]
            old_tv = float(old["tv_distance"])
            new_tv = float(new["tv_distance"])
            writer.writerow(
                {
                    "target_date": date,
                    "greedy_order": old["order"],
                    "greedy_method": old["best_method"],
                    "greedy_tv": f"{old_tv:.12f}",
                    "exact_method": new["method"],
                    "exact_tv": f"{new_tv:.12f}",
                    "exact_overlap": f"{1.0 - new_tv:.12f}",
                    "tv_improvement": f"{old_tv - new_tv:+.12f}",
                    "exact_block_candidates": new["exact_block_candidates"],
                    "exact_rounds": new["exact_rounds"],
                    "exact_theoretical_assignments": new["exact_theoretical_assignments"],
                    "exact_visited_leaves": new["exact_visited_leaves"],
                    "exact_pruned_assignments": new["exact_pruned_assignments"],
                    "exact_elapsed": new["exact_elapsed"],
                    "exact_trace_path": str(root_trace_path(new, date)),
                }
            )


def root_trace_path(row: dict[str, str], date: str) -> Path:
    # method_summary does not repeat the output path; the runner uses this deterministic name.
    return Path("/home/yuzugon/pcap/derived/anon-tree-lpm-remap/nyc-to-wide-exact-seeded-k30-r10") / f"{date}-exact-seeded-k30-r10-10000000.txt"


def plot_distributions(path: Path, greedy_root: Path, exact_root: Path, greedy: dict[str, dict[str, str]], exact: dict[str, dict[str, str]]) -> None:
    dates = sorted(greedy)
    x = list(range(33))
    fig, axes = plt.subplots(len(dates), 1, figsize=(12.5, 12.5), sharex=True)
    for axis, date in zip(axes, dates):
        old = greedy[date]
        new = exact[date]
        old_csv = greedy_root / date / old["order"] / "lpm_distribution_comparison.csv"
        exact_csv = exact_root / date / "exact-seeded" / "lpm_distribution_comparison.csv"
        target, old_values = method_distribution(old_csv, old["best_method"])
        _, exact_values = method_distribution(exact_csv, new["method"])
        _, baseline = method_distribution(exact_csv, "baseline-anonymized")
        axis.plot(x, target, color="#111827", linewidth=2.5, marker="o", markersize=3, label="Non-anonymized target")
        axis.plot(x, baseline, color="#d84b4b", linewidth=1.6, linestyle="--", label="Original NYC")
        axis.plot(x, old_values, color="#8b93a1", linewidth=1.8, label="Previous greedy")
        axis.plot(x, exact_values, color="#2369bd", linewidth=2.3, marker="s", markersize=3, label="Exact-block result")
        axis.set_ylabel("Packet share (%)")
        axis.set_title(
            f"Target {date}: TV {float(old['tv_distance']):.5f} → {float(new['tv_distance']):.5f}; "
            f"overlap {(1.0 - float(new['tv_distance'])) * 100:.2f}%",
            loc="left",
            fontsize=10.5,
        )
        axis.grid(axis="y", linestyle=":", alpha=0.35)
    axes[0].legend(frameon=False, ncol=4, fontsize=8.5)
    axes[-1].set_xticks(x, [f"/{length}" for length in x], rotation=60, ha="right")
    axes[-1].set_xlabel("Longest matching prefix length")
    fig.suptitle("NYC LPM remapping: previous greedy vs exact block branch-and-bound", y=0.995)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_report(path: Path, csv_path: Path, plot_path: Path, greedy: dict[str, dict[str, str]], exact: dict[str, dict[str, str]]) -> None:
    lines = [
        "# NYC LPM exact-block search",
        "",
        "## Scope",
        "",
        "NYC匿名トレースをNYC RIBで評価し、3つの固定非匿名LPM分布へ合わせた。20万packet sampleに現れる全prefix節点をcoordinate sweepし、その後に30変数ずつの全組合せをbranch-and-boundで厳密探索した。",
        "",
        "全活性節点の全組合せを一度に列挙したものではない。各30変数block内では `2^30` 通りを、訪問したleafと許容下界で枝刈りした部分木の合計により完全被覆している。blockの選択と複数blockの反復はblock-coordinate戦略である。",
        "",
        "## Results",
        "",
        "| target | previous TV | exact-block TV | overlap | improvement | variables | rounds | assignments covered | leaves | pruned | exact time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for date in sorted(greedy):
        old = greedy[date]
        new = exact[date]
        old_tv = float(old["tv_distance"])
        new_tv = float(new["tv_distance"])
        lines.append(
            f"| {date} | {old_tv:.8f} | {new_tv:.8f} | {(1.0 - new_tv) * 100:.2f}% | "
            f"{old_tv - new_tv:+.8f} | {new['exact_block_candidates']} | {new['exact_rounds']} | "
            f"{int(new['exact_theoretical_assignments']):,} | {int(new['exact_visited_leaves']):,} | "
            f"{int(new['exact_pruned_assignments']):,} | {new['exact_elapsed']} |"
        )
    lines.extend(
        [
            "",
            f"![LPM comparison]({plot_path.name})",
            "",
            "## Computation reductions",
            "",
            "- 同じ入力prefixのsampleを連続range化し、candidateごとの20万packet全走査を除去。",
            "- sampleに現れないrotation変数はsample目的関数上同値なので除外。",
            "- TVと同値な整数scaled-L1を1packet移動ごとに増分更新。",
            "- 未確定packetを任意のLPM binへ移せると緩和した許容下界でbranch-and-bound。",
            "- 高mass変数を探索木の上位に置き、頻繁な大規模packet更新を削減。",
            "",
            "## Artifacts",
            "",
            f"- CSV: `{csv_path}`",
            f"- plot: `{plot_path}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    greedy = greedy_winners(args.greedy_root)
    exact = exact_results(args.exact_root, sorted(greedy))
    csv_path = args.output_dir / "exact_search_comparison.csv"
    plot_path = args.output_dir / "exact_search_lpm_comparison.png"
    report_path = args.output_dir / "FINAL_REPORT_JA.md"
    write_comparison_csv(csv_path, greedy, exact)
    plot_distributions(plot_path, args.greedy_root, args.exact_root, greedy, exact)
    write_report(report_path, csv_path, plot_path, greedy, exact)
    for output in (csv_path, plot_path, report_path):
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
