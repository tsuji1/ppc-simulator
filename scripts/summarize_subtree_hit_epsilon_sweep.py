#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.8"]
# ///
"""Summarize the traffic-decile /16 hit-node epsilon sweep."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_result(path: Path) -> dict[str, object]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    row = next(row for row in rows if row["method"] == "adaptive-lpm-subtree-hit")
    epsilon = float(path.parent.name.removeprefix("epsilon-").replace("p", "."))
    return {
        "epsilon": epsilon,
        "subtree_hit_before": float(row["subtree_hit_before"]),
        "subtree_hit_after": float(row["subtree_hit_after"]),
        "subtree_improvement_percent": 100
        * (float(row["subtree_hit_before"]) - float(row["subtree_hit_after"]))
        / float(row["subtree_hit_before"]),
        "seed_lpm_tv": float(row["subtree_seed_tv"]),
        "final_lpm_tv": float(row["subtree_final_tv"]),
        "lpm_tv_limit": float(row["subtree_tv_limit"]),
        "upper_accepted": int(row["subtree_upper_accepted"]),
        "lower_accepted": int(row["subtree_lower_accepted"]),
        "flip_count": int(row["flip_count"]),
    }


def read_cache_results(root: Path) -> list[dict[str, object]]:
    cache_dir = root / "cache-eval"
    labels = ("anon", "target", "lpm-seed", "eps0", "eps0005", "eps001", "eps002")
    rows: list[dict[str, object]] = []
    for label in labels:
        path = cache_dir / f"{label}.csv"
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(
                    {
                        "condition": label,
                        "config_id": row["config_id"],
                        "hits": int(row["hits"]),
                        "misses": int(row["misses"]),
                        "hit_rate_pct": float(row["hit_rate_pct"]),
                    }
                )
    return rows


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        (read_result(path) for path in input_root.glob("epsilon-*/method_summary.csv")),
        key=lambda row: float(row["epsilon"]),
    )
    if not rows:
        raise SystemExit(f"no method_summary.csv files below {input_root}")

    fields = list(rows[0])
    with (output_dir / "epsilon_sweep_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    x = [float(row["epsilon"]) for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    axes[0].plot(x, [float(row["subtree_hit_after"]) for row in rows], marker="o", label="after")
    axes[0].axhline(float(rows[0]["subtree_hit_before"]), color="0.5", linestyle="--", label="LPM seed")
    axes[0].set_xlabel("LPM-TV epsilon")
    axes[0].set_ylabel("Mean decile × h16..h24 TV")
    axes[0].set_title("Hit-node distribution fit")
    axes[0].legend()

    axes[1].plot(x, [float(row["final_lpm_tv"]) for row in rows], marker="o", label="final")
    axes[1].plot(x, [float(row["lpm_tv_limit"]) for row in rows], marker=".", linestyle="--", label="constraint")
    axes[1].axhline(float(rows[0]["seed_lpm_tv"]), color="0.5", linestyle=":", label="seed")
    axes[1].set_xlabel("LPM-TV epsilon")
    axes[1].set_ylabel("LPM-TV")
    axes[1].set_title("LPM constraint")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(output_dir / "epsilon_sweep.png", dpi=180)
    plt.close(fig)

    cache_rows = read_cache_results(input_root)
    if cache_rows:
        cache_fields = list(cache_rows[0])
        with (output_dir / "cache_hitrate_summary.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=cache_fields)
            writer.writeheader()
            writer.writerows(cache_rows)
        configurations = ("ps-index5-cap2048", "ps-ideal-cap2048", "mp-24-20-2048-2048")
        conditions = list(dict.fromkeys(str(row["condition"]) for row in cache_rows))
        figure, axis = plt.subplots(figsize=(10.5, 4.5))
        width = 0.24
        for config_index, config in enumerate(configurations):
            values = [
                next(
                    (float(row["hit_rate_pct"]) for row in cache_rows if row["condition"] == condition and row["config_id"] == config),
                    float("nan"),
                )
                for condition in conditions
            ]
            positions = [index + (config_index - 1) * width for index in range(len(conditions))]
            axis.bar(positions, values, width=width, label=config)
        axis.set_xticks(range(len(conditions)), conditions)
        axis.set_ylabel("Hit rate (%)")
        axis.set_title("1M-packet cache evaluation")
        axis.legend(fontsize=8)
        axis.set_ylim(min(float(row["hit_rate_pct"]) for row in cache_rows) - 0.5, 100)
        figure.tight_layout()
        figure.savefig(output_dir / "cache_hitrate.png", dpi=180)
        plt.close(figure)

    best = min(rows, key=lambda row: float(row["subtree_hit_after"]))
    report = [
        "# Traffic-decile /16 hit-node epsilon sweep",
        "",
        "The transformation starts from the LPM-directed greedy mapping, then evaluates `/0..15` rotations before `/16..23` rotations.",
        "A rotation is accepted only when it improves the mean TV distance of the traffic-decile `h16..h24` distributions and keeps LPM-TV within the seed plus epsilon.",
        "Each active `/16` contributes its packet count, so a million-packet subtree has proportionally more influence than a hundred-packet subtree.",
        "",
        "| epsilon | hit TV before | hit TV after | improvement | LPM seed | LPM final | limit | upper accepted | lower accepted |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['epsilon']:.3f} | {row['subtree_hit_before']:.6f} | {row['subtree_hit_after']:.6f} | "
            f"{row['subtree_improvement_percent']:.2f}% | {row['seed_lpm_tv']:.6f} | {row['final_lpm_tv']:.6f} | "
            f"{row['lpm_tv_limit']:.6f} | {row['upper_accepted']} | {row['lower_accepted']} |"
        )
    report.extend(
        [
            "",
            f"Best hit-distribution score in this sweep: epsilon `{best['epsilon']:.3f}` with `{best['subtree_hit_after']:.6f}`.",
            "",
            "![epsilon sweep](epsilon_sweep.png)",
            "",
        ]
    )
    if cache_rows:
        report.extend(
            [
                "## Cache evaluation (1M packets)",
                "",
                "| condition | PS PREFIX18 | PS IDEAL | MP /24+/20 |",
                "|---|---:|---:|---:|",
            ]
        )
        for condition in dict.fromkeys(str(row["condition"]) for row in cache_rows):
            values = {
                str(row["config_id"]): float(row["hit_rate_pct"])
                for row in cache_rows
                if row["condition"] == condition
            }
            report.append(
                f"| {condition} | {values.get('ps-index5-cap2048', float('nan')):.4f}% | "
                f"{values.get('ps-ideal-cap2048', float('nan')):.4f}% | "
                f"{values.get('mp-24-20-2048-2048', float('nan')):.4f}% |"
            )
        report.extend(["", "![cache hit rate](cache_hitrate.png)", ""])
    (output_dir / "REPORT.md").write_text("\n".join(report))


if __name__ == "__main__":
    main()
