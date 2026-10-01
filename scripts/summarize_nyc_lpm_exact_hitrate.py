# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib>=3.8",
# ]
# ///

"""Compare NYC cache hit rates for previous greedy and exact-block remappings."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


DATES = ("2025-09-27", "2025-12-27", "2026-03-27")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--greedy-summary", type=Path, required=True)
    parser.add_argument("--exact-hitrate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_exact_file(path: Path) -> dict[str, dict[str, str]]:
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


def load_data(greedy_path: Path, exact_dir: Path) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], dict[str, float], dict[str, str]]:
    greedy: dict[tuple[str, str], float] = {}
    labels: dict[str, str] = {}
    for row in read_csv(greedy_path):
        labels[row["config_id"]] = row["config_label"]
        trace = row["trace"]
        if trace.startswith("target-"):
            greedy[(trace.removeprefix("target-"), row["config_id"])] = float(row["hit_rate_pct"])

    original_rows = load_exact_file(exact_dir / "original-nyc.csv")
    original = {config_id: float(row["cumulative_hit_rate_pct"]) for config_id, row in original_rows.items()}
    exact: dict[tuple[str, str], float] = {}
    for date in DATES:
        for config_id, row in load_exact_file(exact_dir / f"target-{date}.csv").items():
            labels[config_id] = row["config_label"]
            exact[(date, config_id)] = float(row["cumulative_hit_rate_pct"])
    return greedy, exact, original, labels


def write_output_csv(path: Path, greedy: dict[tuple[str, str], float], exact: dict[tuple[str, str], float], original: dict[str, float], labels: dict[str, str]) -> None:
    fields = ["target_date", "config_id", "config_label", "original_nyc_pct", "previous_greedy_pct", "exact_block_pct", "exact_minus_greedy_pp", "exact_minus_original_pp"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for config_id in sorted(labels):
            for date in DATES:
                writer.writerow(
                    {
                        "target_date": date,
                        "config_id": config_id,
                        "config_label": labels[config_id],
                        "original_nyc_pct": f"{original[config_id]:.8f}",
                        "previous_greedy_pct": f"{greedy[(date, config_id)]:.8f}",
                        "exact_block_pct": f"{exact[(date, config_id)]:.8f}",
                        "exact_minus_greedy_pp": f"{exact[(date, config_id)] - greedy[(date, config_id)]:+.8f}",
                        "exact_minus_original_pp": f"{exact[(date, config_id)] - original[config_id]:+.8f}",
                    }
                )


def plot(path: Path, greedy: dict[tuple[str, str], float], exact: dict[tuple[str, str], float], original: dict[str, float], labels: dict[str, str]) -> None:
    configs = sorted(labels)
    fig, axes = plt.subplots(len(configs), 1, figsize=(11.5, 3.6 * len(configs)), squeeze=False)
    width = 0.34
    x = list(range(len(DATES)))
    for axis, config_id in zip(axes[:, 0], configs):
        old_values = [greedy[(date, config_id)] for date in DATES]
        exact_values = [exact[(date, config_id)] for date in DATES]
        old_bars = axis.bar([value - width / 2 for value in x], old_values, width, label="Previous greedy", color="#8b93a1")
        exact_bars = axis.bar([value + width / 2 for value in x], exact_values, width, label="Exact-block", color="#286fbb")
        axis.axhline(original[config_id], color="#d24b4b", linestyle="--", linewidth=1.6, label=f"Original NYC {original[config_id]:.4f}%")
        axis.bar_label(old_bars, labels=[f"{value:.4f}" for value in old_values], padding=2, fontsize=8)
        axis.bar_label(exact_bars, labels=[f"{value:.4f}" for value in exact_values], padding=2, fontsize=8)
        axis.set_xticks(x, DATES)
        axis.set_ylabel("Hit rate (%)")
        axis.set_title(labels[config_id], loc="left")
        axis.grid(axis="y", alpha=0.25)
        all_values = old_values + exact_values + [original[config_id]]
        span = max(all_values) - min(all_values)
        margin = max(0.35, span * 0.2)
        axis.set_ylim(max(0.0, min(all_values) - margin), min(100.1, max(all_values) + margin))
    axes[0, 0].legend(frameon=False, ncol=3, fontsize=8.5)
    fig.suptitle("NYC RIB: 10M-packet warm-cache hit rate after exact block search", y=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_report(path: Path, csv_path: Path, plot_path: Path, greedy: dict[tuple[str, str], float], exact: dict[tuple[str, str], float], original: dict[str, float], labels: dict[str, str]) -> None:
    lines = [
        "# NYC exact-block remapping hit rate",
        "",
        "- NYC RIB, first 10,000,000 valid IPv4 TCP/UDP packets",
        "- warm cache, way 8",
        "- MP `/24+/20`, capacity `2048+2048`",
        "- PS capacity `2048`, index5 and ideal index2",
        "",
        "| target | cache | original NYC | previous greedy | exact-block | exact - greedy | exact - original |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for date in DATES:
        for config_id in sorted(labels):
            old = greedy[(date, config_id)]
            new = exact[(date, config_id)]
            base = original[config_id]
            lines.append(f"| {date} | {labels[config_id]} | {base:.6f}% | {old:.6f}% | {new:.6f}% | {new-old:+.6f} pp | {new-base:+.6f} pp |")
    lines.extend(
        [
            "",
            f"![Hit rate comparison]({plot_path.name})",
            "",
            "LPM長ヒストグラムだけを最適化しているため、exact-blockでTVが改善してもcache hit rateの改善は保証されない。",
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
    greedy, exact, original, labels = load_data(args.greedy_summary, args.exact_hitrate_dir)
    csv_path = args.output_dir / "exact_hitrate_comparison.csv"
    plot_path = args.output_dir / "exact_hitrate_comparison.png"
    report_path = args.output_dir / "HITRATE.md"
    write_output_csv(csv_path, greedy, exact, original, labels)
    plot(plot_path, greedy, exact, original, labels)
    write_report(report_path, csv_path, plot_path, greedy, exact, original, labels)
    for output in (csv_path, plot_path, report_path):
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
