# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib>=3.8",
# ]
# ///

"""Aggregate final 10M-packet hit rates for LPM remapping experiments."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt


KINDS = ("baseline-anonymized", "non-anonymized", "best-transformed")
KIND_LABELS = {
    "baseline-anonymized": "Original anonymized",
    "non-anonymized": "Non-anonymized",
    "best-transformed": "Best LPM-remapped",
}
KIND_COLORS = {
    "baseline-anonymized": "#9097a3",
    "non-anonymized": "#3979b9",
    "best-transformed": "#ef8a3b",
}


@dataclass(frozen=True)
class HitRate:
    date: str
    kind: str
    config_id: str
    config_label: str
    cumulative_packets: int
    cumulative_hits: int
    hit_rate_pct: float
    trace_path: str
    source_csv: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize LPM remap hit-rate CSVs.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def parse_name(path: Path) -> tuple[str, str]:
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})-(baseline-anonymized|non-anonymized|best-transformed)\.csv",
        path.name,
    )
    if not match:
        raise ValueError(f"unexpected hit-rate filename: {path.name}")
    return match.group(1), match.group(2)


def load_file(path: Path) -> list[HitRate]:
    date, kind = parse_name(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    max_window = max(int(row["window_size"]) for row in rows)
    selected = [row for row in rows if int(row["window_size"]) == max_window]
    by_config: dict[str, dict[str, str]] = {}
    for row in selected:
        current = by_config.get(row["config_id"])
        if current is None or int(row["cumulative_packets"]) > int(current["cumulative_packets"]):
            by_config[row["config_id"]] = row
    return [
        HitRate(
            date=date,
            kind=kind,
            config_id=row["config_id"],
            config_label=row["config_label"],
            cumulative_packets=int(row["cumulative_packets"]),
            cumulative_hits=int(row["cumulative_hits"]),
            hit_rate_pct=float(row["cumulative_hit_rate_pct"]),
            trace_path=row["trace_path"],
            source_csv=path,
        )
        for row in by_config.values()
    ]


def load_all(input_dir: Path) -> list[HitRate]:
    paths = sorted(input_dir.glob("*.csv"))
    results = [result for path in paths for result in load_file(path)]
    dates = {result.date for result in results}
    expected = {(date, kind) for date in dates for kind in KINDS}
    actual = {(result.date, result.kind) for result in results}
    missing = expected - actual
    if missing:
        raise ValueError(f"missing date/kind inputs: {sorted(missing)}")
    return results


def write_csv(path: Path, results: list[HitRate]) -> None:
    fields = [
        "date",
        "trace_kind",
        "config_id",
        "config_label",
        "cumulative_packets",
        "cumulative_hits",
        "hit_rate_pct",
        "trace_path",
        "source_csv",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda value: (value.date, value.config_id, value.kind)):
            writer.writerow(
                {
                    "date": result.date,
                    "trace_kind": result.kind,
                    "config_id": result.config_id,
                    "config_label": result.config_label,
                    "cumulative_packets": result.cumulative_packets,
                    "cumulative_hits": result.cumulative_hits,
                    "hit_rate_pct": f"{result.hit_rate_pct:.8f}",
                    "trace_path": result.trace_path,
                    "source_csv": result.source_csv,
                }
            )


def write_plot(path: Path, results: list[HitRate]) -> None:
    dates = sorted({result.date for result in results})
    configs = sorted({result.config_id: result.config_label for result in results}.items())
    by_key = {(result.date, result.kind, result.config_id): result for result in results}
    fig, axes = plt.subplots(len(configs), 1, figsize=(11.5, 3.6 * len(configs)), squeeze=False)
    width = 0.24
    centers = list(range(len(dates)))
    for axis, (config_id, label) in zip(axes[:, 0], configs):
        all_values: list[float] = []
        for index, kind in enumerate(KINDS):
            values = [by_key[(date, kind, config_id)].hit_rate_pct for date in dates]
            all_values.extend(values)
            bars = axis.bar(
                [center + (index - 1) * width for center in centers],
                values,
                width=width,
                label=KIND_LABELS[kind],
                color=KIND_COLORS[kind],
            )
            axis.bar_label(bars, labels=[f"{value:.3f}" for value in values], padding=2, fontsize=8)
        axis.set_xticks(centers, dates)
        axis.set_ylabel("Hit rate (%)")
        axis.set_title(label)
        axis.grid(axis="y", alpha=0.25)
        low = min(all_values)
        axis.set_ylim(max(0.0, low - max(0.5, (100.0 - low) * 0.12)), 100.15)
    axes[0, 0].legend(frameon=False, ncol=3, loc="lower left")
    fig.suptitle("10M-packet warm-cache hit rate after LPM remapping", y=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_markdown(path: Path, results: list[HitRate], csv_path: Path, plot_path: Path) -> None:
    dates = sorted({result.date for result in results})
    configs = sorted({result.config_id: result.config_label for result in results}.items())
    by_key = {(result.date, result.kind, result.config_id): result for result in results}
    lines = [
        "# Hit-rate evaluation of best LPM-remapped traces",
        "",
        "## Conditions",
        "",
        "- first 10,000,000 valid IPv4 TCP/UDP packets",
        "- warm cache, way 8",
        "- MP: /24+/20, capacity 2048+2048",
        "- PS: capacity 2048, index5 and ideal index2",
        "- comparison: original anonymized, non-anonymized, and best of the three rotation orders",
        "",
        "## Final cumulative hit rates",
        "",
        "| date | cache | original anonymized | non-anonymized | best remapped | remapped - target | remapped - original |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for date in dates:
        for config_id, label in configs:
            baseline = by_key[(date, "baseline-anonymized", config_id)].hit_rate_pct
            target = by_key[(date, "non-anonymized", config_id)].hit_rate_pct
            transformed = by_key[(date, "best-transformed", config_id)].hit_rate_pct
            lines.append(
                f"| {date} | {label} | {baseline:.6f}% | {target:.6f}% | {transformed:.6f}% | "
                f"{transformed - target:+.6f} pp | {transformed - baseline:+.6f} pp |"
            )
    lines.extend(
        (
            "",
            "## Interpretation",
            "",
            "LPM histogramだけを目的関数にしているため、cache hit rateの一致は最適化条件ではない。",
            "MPおよびideal PSが非匿名値へ近づくかは変換後prefix localityの副次的な検証であり、index5は回転によるset collisionの変化も受ける。",
            "したがってLPM分布一致とhit rate一致は別の性質として報告する。",
            "",
            "## Artifacts",
            "",
            f"- CSV: `{csv_path}`",
            f"- plot: `{plot_path}`",
            "- raw CSVs: one file per date and trace kind in this directory",
            "",
        )
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = load_all(args.input_dir)
    csv_path = args.output_dir / "hitrate_summary.csv"
    plot_path = args.output_dir / "hitrate_comparison.png"
    report_path = args.output_dir / "HITRATE.md"
    write_csv(csv_path, results)
    write_plot(plot_path, results)
    write_markdown(report_path, results, csv_path, plot_path)
    print(f"wrote {csv_path}")
    print(f"wrote {plot_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
