#!/usr/bin/env python3
"""Compare ClassBench / FlowBench synthetic traces with real WIDE traces (#77, #83).

Each --source is ``<report dir>`` laid out by the batch runs:

    fidelity/<label>/poptrie/summary.csv
    fidelity/<label>/poptrie/matched_prefix_length_distribution.csv
    fidelity/<label>/coverage/lpm_prefix_coverage.csv
    fidelity/<label>/coverage/lpm_prefix_entries.csv
    hitrate/<label>_cap<N>.csv

Writes fidelity_summary.csv, matched_prefix_length.csv, hitrate_summary.csv
and PNG figures into --output-dir.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CAPACITIES = (4096, 8192)
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7")
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"


def read_kv(path: Path) -> dict[str, str]:
    with path.open() as handle:
        return {row["metric"]: row["value"] for row in csv.DictReader(handle)}


def family(label: str) -> str:
    if label.startswith("real_"):
        return "real"
    if label.startswith("cb_"):
        return "classbench"
    if label.startswith("fb_"):
        return "flowbench"
    return "other"


def discover(sources: list[Path]) -> dict[str, Path]:
    labels: dict[str, Path] = {}
    for source in sources:
        for path in sorted((source / "fidelity").glob("*/poptrie/summary.csv")):
            labels.setdefault(path.parent.parent.name, source)
    return labels


def top_shares(entries: Path, total: int, top_ns=(1, 10, 100)) -> dict[str, float]:
    # Entries hold the per-length top-100, so the global top-100 is inside their union.
    with entries.open() as handle:
        counts = sorted((int(row["packet_count"]) for row in csv.DictReader(handle)), reverse=True)
    return {f"lpm_top{n}_share": sum(counts[:n]) / total for n in top_ns}


def fidelity(labels: dict[str, Path]) -> tuple[list[dict], dict[str, dict[int, float]]]:
    rows = []
    length_share: dict[str, dict[int, float]] = {}
    for label, source in labels.items():
        base = source / "fidelity" / label
        summary = read_kv(base / "poptrie" / "summary.csv")
        processed = int(summary["processed"])
        with (base / "poptrie" / "matched_prefix_length_distribution.csv").open() as handle:
            dist = {int(r["matched_prefix_length"]): int(r["count"]) / processed for r in csv.DictReader(handle)}
        length_share[label] = dist
        per_checkpoint: dict[int, int] = defaultdict(int)
        with (base / "coverage" / "lpm_prefix_coverage.csv").open() as handle:
            for r in csv.DictReader(handle):
                per_checkpoint[int(r["checkpoint_packets"])] += int(r["distinct_lpm_prefixes"])
        last_checkpoint = max(per_checkpoint)
        row = {
            "label": label,
            "family": family(label),
            "packets": processed,
            "distinct_dst": int(summary["distinct_destinations"]),
            "avg_run_length": float(summary["average_run_length"]),
            "max_run_length": int(summary["max_run_length"]),
            "matched_len_avg": float(summary["matched_prefix_length_avg"]),
            "default_route_share": dist.get(0, 0.0),
            "len24_share": dist.get(24, 0.0),
            "len_gt24_share": sum(v for k, v in dist.items() if k > 24),
            "coverage_checkpoint": last_checkpoint,
            "distinct_lpm_prefixes": per_checkpoint[last_checkpoint],
        }
        row.update(top_shares(base / "coverage" / "lpm_prefix_entries.csv", processed))
        rows.append(row)
    return rows, length_share


def config_key(config_id: str) -> str:
    return "mp" if config_id.startswith("mp") else config_id.split("-cap")[0]


def hitrates(labels: dict[str, Path]) -> list[dict]:
    rows = []
    for label, source in labels.items():
        for cap in CAPACITIES:
            path = source / "hitrate" / f"{label}_cap{cap}.csv"
            if not path.exists():
                continue
            with path.open() as handle:
                records = list(csv.DictReader(handle))
            largest_window = max(int(r["window_size"]) for r in records)
            final: dict[str, dict] = {}
            for r in records:
                if int(r["window_size"]) == largest_window:
                    final[r["config_id"]] = r  # keep the last (full-length cumulative) row
            for config_id, r in final.items():
                rows.append({
                    "label": label,
                    "family": family(label),
                    "capacity": cap,
                    "config": config_key(config_id),
                    "config_label": r["config_label"],
                    "packets": int(r["cumulative_packets"]),
                    "hit_rate": float(r["cumulative_hit_rate"]),
                })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def style(ax) -> None:
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY)


def plot_lengths(path: Path, length_share: dict[str, dict[int, float]], picks: list[tuple[str, str]]) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    xs = list(range(33))
    for (label, name), color in zip(picks, SERIES):
        if label not in length_share:
            continue
        ax.plot(xs, [100 * length_share[label].get(x, 0.0) for x in xs], color=color, linewidth=2,
                marker="o", markersize=4, label=name)
    ax.set_xlabel("LPM matched prefix length", color=TEXT_SECONDARY)
    ax.set_ylabel("Packets (%)", color=TEXT_SECONDARY)
    ax.set_title("Matched prefix length, rib.20260327, first 10M packets", loc="left")
    ax.set_xticks(range(0, 33, 4))
    style(ax)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_hitrate(path: Path, rows: list[dict], order: list[tuple[str, str]], capacity: int) -> None:
    by = {(r["label"], r["config"]): r["hit_rate"] for r in rows if r["capacity"] == capacity}
    configs = [("mp", "MP /24+/18"), ("ps-index5", "PS index5"), ("ps-ideal", "PS ideal")]
    present = [(label, name) for label, name in order if (label, "mp") in by]
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(present) * len(configs) / 1.6 + 1.5))
    height = 0.26
    for j, ((cid, cname), color) in enumerate(zip(configs, SERIES)):
        ys = [i + (j - 1) * height for i in range(len(present))]
        values = [100 * by.get((label, cid), 0.0) for label, _ in present]
        ax.barh(ys, values, height=height - 0.03, color=color, label=cname)
    ax.set_yticks(range(len(present)))
    ax.set_yticklabels([name for _, name in present])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Hit rate (%)", color=TEXT_SECONDARY)
    ax.set_title(f"Hit rate at total capacity {capacity} entries, 10M packets", loc="left")
    style(ax)
    ax.grid(False, axis="y")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def display_name(label: str) -> str:
    names = {"real_nonanon": "Real non-anon", "real_anon": "Real anon"}
    if label in names:
        return names[label]
    if label.startswith("cb_"):
        b, fill = label[4:].rsplit("_", 1)
        return f"ClassBench b={b} {'host-random' if fill == 'random' else 'corner'}"
    if label.startswith("fb_"):
        # fb_rd<b>_fd<b> (rule a=1) or fb_ra<a>_rd<b>_fd<b>
        parts = dict((p[:2], p[2:]) for p in label[3:].split("_"))
        return f"FlowBench rule a={parts.get('ra', '1')} b={parts['rd']} flow b={parts['fd']}"
    return label


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", action="append", required=True, help="report dir; repeatable")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    labels = discover([Path(s) for s in args.source])
    fid_rows, length_share = fidelity(labels)
    write_csv(out / "fidelity_summary.csv", fid_rows)
    write_csv(out / "matched_prefix_length.csv",
              [{"prefix_length": n, **{l: length_share[l].get(n, 0.0) for l in labels}} for n in range(33)])
    hit_rows = hitrates(labels)
    write_csv(out / "hitrate_summary.csv", hit_rows)

    plot_lengths(out / "matched_prefix_length.png", length_share, [
        ("real_nonanon", "Real non-anon 2026-03-27"),
        ("real_anon", "Real anon 2026-03-27"),
        ("cb_b0.1_random", "ClassBench b=0.1 host-random"),
        ("fb_rd1_fd1", "FlowBench rule b=1 flow b=1"),
    ])
    order = sorted(labels, key=lambda l: ({"real": 0, "classbench": 1, "flowbench": 2}.get(family(l), 3), l))
    # seed replicates (fb_..._s<N>) go to the seed summary, not the per-trace chart
    order = [l for l in order if not l.endswith("_corner") and "_s" not in l[3:]]
    for cap in CAPACITIES:
        plot_hitrate(out / f"hitrate_cap{cap}.png", hit_rows, [(l, display_name(l)) for l in order], cap)
    seed_rows = seed_summary(fid_rows, hit_rows)
    if seed_rows:
        write_csv(out / "flowbench_seed_summary.csv", seed_rows)
    print(f"wrote report files to {out}")


def seed_summary(fid_rows: list[dict], hit_rows: list[dict]) -> list[dict]:
    """Mean / min / max over seeds per FlowBench (rule a, rule b) with flow Pareto(1, 1).

    Seed 1 is fb_ra<a>_rd<b>_fd1 (fb_rd<b>_fd1 for rule a=1); other seeds add _s<N>.
    """
    hits = {(r["label"], r["config"]): r["hit_rate"] for r in hit_rows if r["capacity"] == 4096}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in fid_rows:
        label = row["label"]
        if not label.startswith("fb_r"):
            continue
        parts = dict((p[:2], p[2:]) for p in label[3:].split("_"))
        if parts.get("fd") != "1" or parts.get("rd") == "0":
            continue
        groups[(parts.get("ra", "1"), parts["rd"])].append(row)
    metrics = {
        "distinct_lpm_prefixes": lambda r: r["distinct_lpm_prefixes"],
        "lpm_top1_share": lambda r: r["lpm_top1_share"],
        "lpm_top100_share": lambda r: r["lpm_top100_share"],
        "matched_len_avg": lambda r: r["matched_len_avg"],
        "hit4096_mp": lambda r: hits.get((r["label"], "mp")),
        "hit4096_ps_index5": lambda r: hits.get((r["label"], "ps-index5")),
        "hit4096_ps_ideal": lambda r: hits.get((r["label"], "ps-ideal")),
    }
    out = []
    for (a, b), rows in sorted(groups.items(), key=lambda kv: (float(kv[0][0]), float(kv[0][1]))):
        if len(rows) < 2:
            continue
        summary = {"rule_a": a, "rule_b": b, "seeds": len(rows)}
        for name, get in metrics.items():
            values = [v for v in (get(r) for r in rows) if v is not None]
            summary[f"{name}_mean"] = sum(values) / len(values)
            summary[f"{name}_min"] = min(values)
            summary[f"{name}_max"] = max(values)
        out.append(summary)
    return out


if __name__ == "__main__":
    main()
