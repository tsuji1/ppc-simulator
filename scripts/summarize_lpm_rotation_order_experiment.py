# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "matplotlib>=3.8",
# ]
# ///

"""Summarize mass/top-down/bottom-up LPM rotation experiments."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt


ORDERS = ("mass", "top-down", "bottom-up")
ORDER_LABELS = {
    "mass": "Mass-first",
    "top-down": "Top-down",
    "bottom-up": "Bottom-up",
}
ORDER_DESCRIPTIONS = {
    "mass": "全深さの候補をパケット量の降順で試す。頻出部分木への大きな変更を先に確定する。",
    "top-down": "浅いprefixから深いprefixへ試す。同じ深さではパケット量の多い節点を先にする。",
    "bottom-up": "深いprefixから浅いprefixへ試す。同じ深さではパケット量の多い節点を先にする。",
}


@dataclass(frozen=True)
class Result:
    date: str
    order: str
    selected_candidates: int
    best_method: str
    packets: int
    tv: float
    baseline_tv: float
    jsd: float
    mean_lpm: float
    target_mean_lpm: float
    mean_lpm_delta: float
    sample_tv: float
    flip_count: int
    elapsed: str
    trace_path: str
    report_dir: Path

    @property
    def overlap(self) -> float:
        return 1.0 - self.tv

    @property
    def relative_reduction(self) -> float:
        return 1.0 - self.tv / self.baseline_tv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate three LPM rotation traversal orders."
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        required=True,
        help="Directory containing DATE/{mass,top-down,bottom-up}",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def markdown_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}: `([^`]+)`", text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing REPORT.md field: {label}")
    return match.group(1)


def load_result(report_dir: Path, date: str, order: str) -> Result:
    report_text = (report_dir / "REPORT.md").read_text(encoding="utf-8")
    with (report_dir / "method_summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = next(row for row in rows if row["best_transformed"] == "true")
    baseline = next(row for row in rows if row["method"] == "baseline-anonymized")
    return Result(
        date=date,
        order=order,
        selected_candidates=int(markdown_value(report_text, "selected LPM hill-climb candidates")),
        best_method=selected["method"],
        packets=int(selected["packets"]),
        tv=float(selected["tv_distance"]),
        baseline_tv=float(baseline["tv_distance"]),
        jsd=float(selected["jensen_shannon"]),
        mean_lpm=float(selected["mean_lpm"]),
        target_mean_lpm=float(selected["target_mean_lpm"]),
        mean_lpm_delta=float(selected["mean_lpm_delta"]),
        sample_tv=float(selected["sample_tv"]),
        flip_count=int(selected["flip_count"]),
        elapsed=markdown_value(report_text, "elapsed"),
        trace_path=markdown_value(report_text, "transformed trace"),
        report_dir=report_dir,
    )


def load_results(root: Path) -> list[Result]:
    results: list[Result] = []
    for date_dir in sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)
    ):
        for order in ORDERS:
            report_dir = date_dir / order
            if not (report_dir / "REPORT.md").exists():
                raise FileNotFoundError(f"missing experiment: {report_dir}")
            results.append(load_result(report_dir, date_dir.name, order))
    if not results:
        raise ValueError(f"no experiment directories under {root}")
    return results


def write_csv(path: Path, results: list[Result]) -> None:
    fields = [
        "date",
        "order",
        "selected_candidates",
        "best_method",
        "packets",
        "tv_distance",
        "distribution_overlap",
        "baseline_tv",
        "relative_tv_reduction",
        "jensen_shannon",
        "mean_lpm",
        "target_mean_lpm",
        "mean_lpm_delta",
        "sample_tv",
        "flip_count",
        "elapsed",
        "trace_path",
        "report_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "date": result.date,
                    "order": result.order,
                    "selected_candidates": result.selected_candidates,
                    "best_method": result.best_method,
                    "packets": result.packets,
                    "tv_distance": f"{result.tv:.12f}",
                    "distribution_overlap": f"{result.overlap:.12f}",
                    "baseline_tv": f"{result.baseline_tv:.12f}",
                    "relative_tv_reduction": f"{result.relative_reduction:.12f}",
                    "jensen_shannon": f"{result.jsd:.12f}",
                    "mean_lpm": f"{result.mean_lpm:.8f}",
                    "target_mean_lpm": f"{result.target_mean_lpm:.8f}",
                    "mean_lpm_delta": f"{result.mean_lpm_delta:.8f}",
                    "sample_tv": f"{result.sample_tv:.12f}",
                    "flip_count": result.flip_count,
                    "elapsed": result.elapsed,
                    "trace_path": result.trace_path,
                    "report_dir": result.report_dir,
                }
            )


def write_plot(path: Path, results: list[Result]) -> None:
    dates = sorted({result.date for result in results})
    by_key = {(result.date, result.order): result for result in results}
    width = 0.24
    colors = {"mass": "#687386", "top-down": "#3b82c4", "bottom-up": "#ef8a3b"}
    fig, ax = plt.subplots(figsize=(11.5, 6.4))
    centers = list(range(len(dates)))
    for index, order in enumerate(ORDERS):
        offset = (index - 1) * width
        values = [by_key[(date, order)].tv for date in dates]
        bars = ax.bar(
            [center + offset for center in centers],
            values,
            width=width,
            label=ORDER_LABELS[order],
            color=colors[order],
        )
        ax.bar_label(bars, labels=[f"{value:.4f}" for value in values], padding=3, fontsize=9)
    ax.set_xticks(centers, dates)
    ax.set_ylabel("Total variation distance (lower is better)")
    ax.set_title("LPM distribution fitting: candidate traversal order")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=3, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_markdown(path: Path, results: list[Result], csv_path: Path, plot_path: Path) -> None:
    dates = sorted({result.date for result in results})
    by_key = {(result.date, result.order): result for result in results}
    winners = {date: min((by_key[(date, order)] for order in ORDERS), key=lambda result: result.tv) for date in dates}
    mean_by_order = {
        order: sum(by_key[(date, order)].tv for date in dates) / len(dates) for order in ORDERS
    }
    lines = [
        "# LPM tree-rotation traversal-order experiment",
        "",
        "## Question",
        "",
        "同じprefix-local rotation候補を、どの順序でgreedyに採否判定すると非匿名LPM分布へ最も近づくかを比較する。",
        "",
        "## Common conditions",
        "",
        "- target/evaluation: first 10,000,000 valid IPv4 TCP/UDP packets",
        "- optimization reservoir: 200,000 packets (deterministic)",
        "- rotation depth: /24",
        "- candidate budget: 61,440 nodes",
        "- hill-climb passes: 2",
        "- initial mappings: identity and adaptive-packet; the lower full-trace TV is retained",
        "- no historical class A/B/C/D boundary constraint",
        "- only the candidate traversal order differs between the three experiments",
        "",
        "## Three candidates",
        "",
    ]
    for order in ORDERS:
        lines.extend((f"### {ORDER_LABELS[order]}", "", ORDER_DESCRIPTIONS[order], ""))
    lines.extend(
        (
            "## Full-trace results",
            "",
            "| date | mass-first TV | top-down TV | bottom-up TV | winner | overlap | baseline TV |",
            "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
        )
    )
    for date in dates:
        winner = winners[date]
        lines.append(
            f"| {date} | {by_key[(date, 'mass')].tv:.8f} | "
            f"{by_key[(date, 'top-down')].tv:.8f} | {by_key[(date, 'bottom-up')].tv:.8f} | "
            f"{ORDER_LABELS[winner.order]} ({winner.best_method}) | {winner.overlap * 100:.2f}% | "
            f"{winner.baseline_tv:.8f} |"
        )
    best_average_order = min(ORDERS, key=mean_by_order.get)
    lines.extend(
        (
            "",
            "## Aggregate",
            "",
            "| order | mean TV across dates | wins |",
            "| --- | ---: | ---: |",
        )
    )
    for order in ORDERS:
        wins = sum(winner.order == order for winner in winners.values())
        lines.append(f"| {ORDER_LABELS[order]} | {mean_by_order[order]:.8f} | {wins} |")
    lines.extend(
        (
            "",
            "## Conclusion",
            "",
            f"単一順序では `{ORDER_LABELS[best_average_order]}` の平均TVが最小だが、全日付で同じ順序が勝つわけではない。",
            "したがって採用方式は、3順序を同じ候補集合で実行し、1,000万packet全件のTVが最小の回転表を選ぶmulti-order greedy searchとする。",
            "これは大域最適を保証しないが、順序依存を明示的に吸収し、各実験と選択理由を再現できる。",
            "",
            "## Artifacts",
            "",
            f"- CSV: `{csv_path}`",
            f"- plot: `{plot_path}`",
            "- each run directory contains REPORT.md, method_summary.csv, lpm_distribution_comparison.csv, and best_mapping.gob.gz",
            "",
        )
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = load_results(args.input_root)
    csv_path = args.output_dir / "rotation_order_results.csv"
    plot_path = args.output_dir / "rotation_order_tv_comparison.png"
    report_path = args.output_dir / "EXPERIMENT.md"
    write_csv(csv_path, results)
    write_plot(plot_path, results)
    write_markdown(report_path, results, csv_path, plot_path)
    print(f"wrote {csv_path}")
    print(f"wrote {plot_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
