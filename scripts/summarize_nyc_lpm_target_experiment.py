# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib>=3.8",
# ]
# ///

"""Summarize NYC remapping to three fixed non-anonymized LPM targets."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


ORDERS = ("mass", "top-down", "bottom-up")
ORDER_LABELS = {
    "mass": "Mass-first",
    "top-down": "Top-down",
    "bottom-up": "Bottom-up",
}
TRACE_LABELS = {
    "original-nyc": "Original NYC",
    "target-2025-09-27": "Remapped to 2025-09-27",
    "target-2025-12-27": "Remapped to 2025-12-27",
    "target-2026-03-27": "Remapped to 2026-03-27",
}
TRACE_COLORS = {
    "original-nyc": "#7c8798",
    "target-2025-09-27": "#337ab7",
    "target-2025-12-27": "#e7902f",
    "target-2026-03-27": "#3a9d68",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def select_winners(root: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(root / "rotation_order_results.csv")
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    winners: dict[str, dict[str, str]] = {}
    for date, date_rows in by_date.items():
        winners[date] = min(date_rows, key=lambda row: float(row["tv_distance"]))
    return winners


def read_lpm(path: Path, selected_method: str) -> tuple[list[float], list[float], list[float]]:
    rows = read_csv(path)
    target = [0.0] * 33
    baseline = [0.0] * 33
    transformed = [0.0] * 33
    for row in rows:
        length = int(row["lpm_prefix_length"])
        target[length] = float(row["target_ratio"]) * 100.0
        if row["method"] == "baseline-anonymized":
            baseline[length] = float(row["ratio"]) * 100.0
        elif row["method"] == selected_method:
            transformed[length] = float(row["ratio"]) * 100.0
    return target, baseline, transformed


def plot_lpm(path: Path, root: Path, winners: dict[str, dict[str, str]]) -> None:
    dates = sorted(winners)
    fig, axes = plt.subplots(len(dates), 1, figsize=(12.5, 12.5), sharex=True)
    x = list(range(33))
    for axis, date in zip(axes, dates):
        winner = winners[date]
        report_dir = root / date / winner["order"]
        target, baseline, transformed = read_lpm(
            report_dir / "lpm_distribution_comparison.csv", winner["best_method"]
        )
        axis.plot(x, target, color="#111827", linewidth=2.5, marker="o", markersize=3.5, label="Non-anonymized target")
        axis.plot(x, baseline, color="#dc4c4c", linewidth=1.8, linestyle="--", marker="x", markersize=4, label="Original NYC on NYC RIB")
        axis.plot(x, transformed, color="#2563b8", linewidth=2.2, marker="s", markersize=3.5, label="Remapped NYC on NYC RIB")
        axis.set_ylabel("Packet share (%)")
        axis.set_title(
            f"Target {date}: {ORDER_LABELS[winner['order']]} / {winner['best_method']}  "
            f"TV={float(winner['tv_distance']):.5f}, overlap={float(winner['distribution_overlap']) * 100:.2f}%",
            loc="left",
            fontsize=10.5,
        )
        axis.grid(axis="y", linestyle=":", alpha=0.35)
    axes[0].legend(frameon=False, ncol=3, fontsize=9)
    axes[-1].set_xticks(x, [f"/{value}" for value in x], rotation=60, ha="right")
    axes[-1].set_xlabel("Longest matching prefix length")
    fig.suptitle("NYC anonymous trace remapped to fixed non-anonymized LPM distributions", y=0.995)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def load_final_hitrate(path: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(path)
    max_window = max(int(row["window_size"]) for row in rows)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if int(row["window_size"]) != max_window:
            continue
        current = result.get(row["config_id"])
        if current is None or int(row["cumulative_packets"]) > int(current["cumulative_packets"]):
            result[row["config_id"]] = row
    return result


def load_hitrates(hitrate_dir: Path) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, str]]:
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    config_labels: dict[str, str] = {}
    for trace_key in TRACE_LABELS:
        for config_id, row in load_final_hitrate(hitrate_dir / f"{trace_key}.csv").items():
            by_key[(trace_key, config_id)] = row
            config_labels[config_id] = row["config_label"]
    return by_key, config_labels


def write_hitrate_csv(path: Path, by_key: dict[tuple[str, str], dict[str, str]], config_labels: dict[str, str]) -> None:
    fields = ["trace", "trace_label", "config_id", "config_label", "packets", "hits", "hit_rate_pct", "delta_from_original_pp", "trace_path"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for config_id in sorted(config_labels):
            baseline = float(by_key[("original-nyc", config_id)]["cumulative_hit_rate_pct"])
            for trace_key in TRACE_LABELS:
                row = by_key[(trace_key, config_id)]
                value = float(row["cumulative_hit_rate_pct"])
                writer.writerow(
                    {
                        "trace": trace_key,
                        "trace_label": TRACE_LABELS[trace_key],
                        "config_id": config_id,
                        "config_label": config_labels[config_id],
                        "packets": row["cumulative_packets"],
                        "hits": row["cumulative_hits"],
                        "hit_rate_pct": f"{value:.8f}",
                        "delta_from_original_pp": f"{value - baseline:+.8f}",
                        "trace_path": row["trace_path"],
                    }
                )


def plot_hitrates(path: Path, by_key: dict[tuple[str, str], dict[str, str]], config_labels: dict[str, str]) -> None:
    configs = sorted(config_labels)
    trace_keys = list(TRACE_LABELS)
    fig, axes = plt.subplots(len(configs), 1, figsize=(11.5, 3.6 * len(configs)), squeeze=False)
    for axis, config_id in zip(axes[:, 0], configs):
        values = [float(by_key[(trace_key, config_id)]["cumulative_hit_rate_pct"]) for trace_key in trace_keys]
        bars = axis.bar(range(len(trace_keys)), values, color=[TRACE_COLORS[key] for key in trace_keys])
        axis.bar_label(bars, labels=[f"{value:.4f}%" for value in values], padding=3, fontsize=8.5)
        axis.set_xticks(range(len(trace_keys)), [TRACE_LABELS[key] for key in trace_keys])
        axis.set_ylabel("Hit rate (%)")
        axis.set_title(config_labels[config_id], loc="left")
        axis.grid(axis="y", alpha=0.25)
        low = min(values)
        axis.set_ylim(max(0.0, low - max(0.5, (100.0 - low) * 0.12)), 100.15)
    fig.suptitle("NYC RIB: 10M-packet warm-cache hit rate before and after LPM remapping", y=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_report(
    path: Path,
    root: Path,
    winners: dict[str, dict[str, str]],
    by_key: dict[tuple[str, str], dict[str, str]],
    config_labels: dict[str, str],
    lpm_plot: Path,
    hitrate_plot: Path,
    hitrate_csv: Path,
) -> None:
    lines = [
        "# NYC trace remapping to three non-anonymized LPM targets",
        "",
        "## Definition",
        "",
        "NYC匿名トレースの宛先prefix treeを回転し、NYCのRIBで評価されるLPM長分布を、WIDE非匿名トレースから得た固定LPM分布へ合わせた。",
        "目標分布をNYC RIBで再計算したのではなく、既報の3つの非匿名LPMヒストグラムを固定目標として直接使用した。",
        "",
        "- NYC trace: `/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap`",
        "- NYC RIB: `/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule`",
        "- first 10,000,000 valid IPv4 TCP/UDP packets",
        "- /24 rotations, 200,000-packet deterministic reservoir, 61,440 candidate budget, 2 passes",
        "- mass-first / top-down / bottom-upを実行し、1,000万packet全件TVが最小のrunを選択",
        "",
        "## LPM fitting",
        "",
        "| target | original TV | best TV | overlap | order | initialization | flips | transformed trace |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | --- |",
    ]
    for date in sorted(winners):
        winner = winners[date]
        lines.append(
            f"| {date} | {float(winner['baseline_tv']):.8f} | {float(winner['tv_distance']):.8f} | "
            f"{float(winner['distribution_overlap']) * 100:.2f}% | {ORDER_LABELS[winner['order']]} | "
            f"{winner['best_method']} | {int(winner['flip_count']):,} | `{winner['trace_path']}` |"
        )
    lines.extend(["", f"![LPM distributions]({lpm_plot.name})", "", "## Cache hit rate", "", "- NYC RIBを全トレースに使用", "- warm cache, way 8", "- MP: /24+/20, capacity 2048+2048", "- PS: capacity 2048, index5 and ideal index2", "", "| cache | original NYC | to 2025-09-27 | delta | to 2025-12-27 | delta | to 2026-03-27 | delta |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for config_id in sorted(config_labels):
        baseline = float(by_key[("original-nyc", config_id)]["cumulative_hit_rate_pct"])
        cells = [f"| {config_labels[config_id]} | {baseline:.6f}%"]
        for date in sorted(winners):
            value = float(by_key[(f"target-{date}", config_id)]["cumulative_hit_rate_pct"])
            cells.append(f"{value:.6f}% | {value - baseline:+.6f} pp")
        lines.append(" | ".join(cells) + " |")
    lines.extend(
        [
            "",
            f"![Hit rates]({hitrate_plot.name})",
            "",
            "LPM長の周辺分布だけを最適化しているため、hit rateが単調に改善する保証はない。特にPS index5は回転後IPのset衝突にも依存する。",
            "",
            "## Artifacts",
            "",
            f"- rotation-order results: `{root / 'rotation_order_results.csv'}`",
            f"- hit-rate CSV: `{hitrate_csv}`",
            f"- LPM plot: `{lpm_plot}`",
            f"- hit-rate plot: `{hitrate_plot}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    winners = select_winners(args.experiment_root)
    hitrate_dir = args.experiment_root / "hitrate"
    by_key, config_labels = load_hitrates(hitrate_dir)
    lpm_plot = args.output_dir / "nyc_lpm_distribution_3targets.png"
    hitrate_plot = args.output_dir / "nyc_hitrate_3targets.png"
    hitrate_csv = args.output_dir / "nyc_hitrate_3targets.csv"
    report = args.output_dir / "FINAL_REPORT_JA.md"
    plot_lpm(lpm_plot, args.experiment_root, winners)
    write_hitrate_csv(hitrate_csv, by_key, config_labels)
    plot_hitrates(hitrate_plot, by_key, config_labels)
    write_report(report, args.experiment_root, winners, by_key, config_labels, lpm_plot, hitrate_plot, hitrate_csv)
    for output in (lpm_plot, hitrate_plot, hitrate_csv, report):
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
