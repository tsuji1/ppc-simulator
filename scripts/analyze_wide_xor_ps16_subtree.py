#!/usr/bin/env python3
# /// script
# dependencies = ["matplotlib>=3.8"]
# ///
"""Diagnose PS /16 cache misses after the global upper-24-bit XOR."""

from __future__ import annotations

import csv
import ipaddress
import math
import struct
import zlib
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "scripts/reports"
OUT = REPORT_ROOT / "wide_xor_ps16_subtree_diagnosis"

CASES = (
    {
        "name": "wide09",
        "label": "WIDE 2025-09 → 2026-03 LPM distribution",
        "rule": ROOT.parent / "rules/rib.20250927.0600.unique.rule",
        "search": REPORT_ROOT / "global-xor-lpm-tv-exhaustive24/wide-2025-09/2026-03-27/search_summary.csv",
        "counts": REPORT_ROOT / "global-xor-lpm-tv-exhaustive24/wide-2025-09/2026-03-27/trace_ip_counts.csv",
        "before_sets": REPORT_ROOT / "wide_xor_ps16_diagnosis/wide09_original/unified_cacheline_by_set.csv",
        "after_sets": REPORT_ROOT / "wide_xor_ps16_diagnosis/wide09_to_202603/unified_cacheline_by_set.csv",
    },
    {
        "name": "wide12",
        "label": "WIDE 2025-12 → 2026-03 LPM distribution",
        "rule": ROOT.parent / "rules/rib.20251227.0600.unique.rule",
        "search": REPORT_ROOT / "global-xor-lpm-tv-exhaustive24/wide-2025-12/2026-03-27/search_summary.csv",
        "counts": REPORT_ROOT / "global-xor-lpm-tv-exhaustive24/wide-2025-12/2026-03-27/trace_ip_counts.csv",
        "before_sets": REPORT_ROOT / "wide_xor_ps16_diagnosis/wide12_original/unified_cacheline_by_set.csv",
        "after_sets": REPORT_ROOT / "wide_xor_ps16_diagnosis/wide12_to_202603/unified_cacheline_by_set.csv",
    },
)


def ip_int(text: str) -> int:
    return int(ipaddress.IPv4Address(text))


def ip16_text(value: int) -> str:
    return f"{value >> 8}.{value & 255}.0.0/16"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def crc_set(prefix16: int) -> int:
    # Go simulator: crc32.ChecksumIEEE(uint32ToBytes(dst_ip >> 16)) % 1024.
    return (zlib.crc32(struct.pack(">I", prefix16)) & 0xFFFFFFFF) % 1024


def load_rules(path: Path):
    by_len = [set() for _ in range(33)]
    descendants = [0] * 65536
    child_nodes: dict[int, list[int]] = defaultdict(lambda: [0] * 256)
    with path.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            net = ip_int(parts[0])
            plen = int(parts[1])
            mask = 0 if plen == 0 else (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
            net &= mask
            by_len[plen].add(net)
            if plen <= 16:
                continue
            p16 = net >> 16
            descendants[p16] += 1
            third = (net >> 8) & 255
            if plen <= 24:
                span = 1 << (24 - plen)
                start = third & ~(span - 1)
                for bucket in range(start, start + span):
                    child_nodes[p16][bucket] += 1
            else:
                child_nodes[p16][third] += 1
    return by_len, descendants, child_nodes


def lpm(by_len: list[set[int]], value: int) -> tuple[int, int]:
    for plen in range(32, -1, -1):
        mask = 0 if plen == 0 else (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
        net = value & mask
        if net in by_len[plen]:
            return net, plen
    return 0, 0


def weighted_quantile(items: list[tuple[int, int]], q: float) -> int:
    total = sum(weight for _, weight in items)
    threshold = total * q
    running = 0
    for value, weight in sorted(items):
        running += weight
        if running >= threshold:
            return value
    return max(value for value, _ in items)


def pearson(xs: list[float], ys: list[float]) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else float("nan")


def plot_sets(case, before: list[dict], after: list[dict]) -> None:
    x = list(range(1024))
    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    for ax, field, ylabel in (
        (axes[0], "hit_count", "Hit count"),
        (axes[1], "total_miss", "Miss count"),
    ):
        ax.plot(x, [int(r[field]) for r in before], color="#777777", lw=1.1, label="Before XOR")
        ax.plot(x, [int(r[field]) for r in after], color="#d7191c", lw=1.1, label="After XOR")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=.25)
        ax.legend(frameon=False, ncol=2)
    axes[1].set_xlabel("PS /16 cache set number (0–1023)")
    axes[0].set_title(case["label"] + " — measured PS /16 set activity")
    fig.tight_layout()
    fig.savefig(OUT / f"{case['name']}_set_hit_miss_before_after.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 4.6))
    ax.plot(x, [int(r["total_miss"]) for r in before], color="#777777", lw=1.1, label="Before XOR")
    ax.plot(x, [int(r["total_miss"]) for r in after], color="#d7191c", lw=1.1, label="After XOR")
    ax.set_yscale("symlog", linthresh=10)
    ax.set_xlabel("PS /16 cache set number (0–1023)")
    ax.set_ylabel("Miss count (symmetric log scale)")
    ax.set_title(case["label"] + " — miss count, including small sets")
    ax.grid(axis="y", alpha=.25)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / f"{case['name']}_set_miss_log_before_after.png", dpi=180)
    plt.close(fig)


def analyze_case(case: dict) -> dict:
    mask = int(read_rows(case["search"])[0]["mask_hex"], 16)
    mask16, mask_third = mask >> 16, (mask >> 8) & 255
    by_len, descendants, child_nodes = load_rules(case["rule"])
    counts = [(ip_int(r["ip"]), int(r["count"])) for r in read_rows(case["counts"])]
    before_sets, after_sets = read_rows(case["before_sets"]), read_rows(case["after_sets"])
    plot_sets(case, before_sets, after_sets)

    p16_packets: dict[int, int] = defaultdict(int)
    p16_third_packets: dict[int, list[int]] = defaultdict(lambda: [0] * 256)
    routes_before: dict[int, set[tuple[int, int]]] = defaultdict(set)
    routes_after: dict[int, set[tuple[int, int]]] = defaultdict(set)
    total = 0
    prefix0_before = prefix0_after = 0
    for ip, count in counts:
        transformed = ip ^ mask
        old16, new16 = ip >> 16, transformed >> 16
        p16_packets[old16] += count
        p16_third_packets[old16][(ip >> 8) & 255] += count
        old_route, old_len = lpm(by_len, ip)
        new_route, new_len = lpm(by_len, transformed)
        routes_before[old16].add((old_route, old_len))
        routes_after[new16].add((new_route, new_len))
        prefix0_before += count if old_len == 0 else 0
        prefix0_after += count if new_len == 0 else 0
        total += count

    mapping_rows = []
    before_items, after_items = [], []
    for old16, packets in p16_packets.items():
        new16 = old16 ^ mask16
        before_nodes, after_nodes = descendants[old16], descendants[new16]
        before_items.append((before_nodes, packets))
        after_items.append((after_nodes, packets))
        mapping_rows.append({
            "before_prefix16": ip16_text(old16),
            "after_prefix16": ip16_text(new16),
            "packets": packets,
            "packet_share_percent": f"{100 * packets / total:.9f}",
            "before_descendant_route_nodes": before_nodes,
            "after_descendant_route_nodes": after_nodes,
            "node_ratio_after_before": f"{after_nodes / max(before_nodes, 1):.6f}",
            "before_distinct_lpm_entries_touched": len(routes_before[old16]),
            "after_distinct_lpm_entries_touched": len(routes_after[new16]),
            "before_set": crc_set(old16),
            "after_set": crc_set(new16),
        })
    mapping_rows.sort(key=lambda r: int(r["packets"]), reverse=True)
    fields = list(mapping_rows[0])
    write_rows(OUT / f"{case['name']}_prefix16_mapping.csv", mapping_rows, fields)

    # Direct before-vs-after subtree comparison. Bubble area represents packet count.
    fig, ax = plt.subplots(figsize=(7.5, 7))
    xs = [int(r["before_descendant_route_nodes"]) for r in mapping_rows]
    ys = [int(r["after_descendant_route_nodes"]) for r in mapping_rows]
    ws = [int(r["packets"]) for r in mapping_rows]
    sizes = [5 + 180 * math.sqrt(w / max(ws)) for w in ws]
    ax.scatter(xs, ys, s=sizes, color="#d7191c", alpha=.35, edgecolors="none")
    lim = max(max(xs), max(ys), 1)
    ax.plot([0, lim], [0, lim], color="#777777", ls="--", lw=1, label="No change")
    ax.set_xscale("symlog", linthresh=1)
    ax.set_yscale("symlog", linthresh=1)
    ax.set_xlabel("Descendant route nodes under /16 before XOR")
    ax.set_ylabel("Descendant route nodes under /16 after XOR")
    ax.set_title(case["label"] + " — each point is one traffic-active /16")
    ax.grid(alpha=.2)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / f"{case['name']}_prefix16_subtree_before_after.png", dpi=180)
    plt.close(fig)

    # Show the two source /16 groups contributing the most packets to the two worst sets.
    after_miss = {int(r["set_idx"]): int(r["total_miss"]) for r in after_sets}
    hot_sets = sorted(after_miss, key=after_miss.get, reverse=True)[:2]
    candidates = [r for r in mapping_rows if int(r["after_set"]) in hot_sets]
    chosen = []
    for set_idx in hot_sets:
        group = [r for r in candidates if int(r["after_set"]) == set_idx]
        if group:
            chosen.append(max(group, key=lambda r: int(r["packets"])))
    fig, axes = plt.subplots(len(chosen), 1, figsize=(14, 3.6 * len(chosen)), sharex=True)
    if len(chosen) == 1:
        axes = [axes]
    x = list(range(256))
    for ax, row in zip(axes, chosen):
        old16 = ip_int(row["before_prefix16"].split("/")[0]) >> 16
        new16 = old16 ^ mask16
        before_curve = child_nodes[old16]
        # x denotes the original child; after XOR it lands at x XOR mask_third.
        after_curve = [child_nodes[new16][i ^ mask_third] for i in x]
        ax.plot(x, before_curve, color="#777777", lw=1.5, label=f"Before: {ip16_text(old16)}")
        ax.plot(x, after_curve, color="#d7191c", lw=1.5, label=f"After: {ip16_text(new16)} (mapped child)")
        ax.set_ylabel("Relevant route nodes")
        ax.set_title(f"Destination set {row['after_set']}; {int(row['packets']):,} packets from this /16 group")
        ax.grid(axis="y", alpha=.25)
        ax.legend(frameon=False, ncol=2)
    axes[-1].set_xlabel("Original /24 child number inside /16 (0–255)")
    fig.suptitle(case["label"] + " — route-tree complexity across the 256 children", y=1.01)
    fig.tight_layout()
    fig.savefig(OUT / f"{case['name']}_hot_prefix16_256_children.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    set_rows = []
    for set_idx in range(1024):
        members = [r for r in mapping_rows if int(r["after_set"]) == set_idx]
        packet_sum = sum(int(r["packets"]) for r in members)
        weighted_nodes = (
            sum(int(r["packets"]) * int(r["after_descendant_route_nodes"]) for r in members) / packet_sum
            if packet_sum else 0
        )
        distinct_routes = sum(int(r["after_distinct_lpm_entries_touched"]) for r in members)
        set_rows.append({
            "set_idx": set_idx,
            "packets": packet_sum,
            "packet_weighted_descendant_nodes": f"{weighted_nodes:.6f}",
            "active_prefix16_count": len(members),
            "sum_distinct_lpm_entries_touched": distinct_routes,
            "hit_count": after_sets[set_idx]["hit_count"],
            "first_miss": after_sets[set_idx]["first_miss"],
            "second_miss": after_sets[set_idx]["second_miss"],
            "total_miss": after_sets[set_idx]["total_miss"],
        })
    write_rows(OUT / f"{case['name']}_after_set_structure.csv", set_rows, list(set_rows[0]))

    weighted_before = sum(v * w for v, w in before_items) / total
    weighted_after = sum(v * w for v, w in after_items) / total
    second = [int(r["second_miss"]) for r in after_sets]
    structure = [float(r["packet_weighted_descendant_nodes"]) for r in set_rows]
    packets_by_set = [int(r["packets"]) for r in set_rows]
    route_touch = [int(r["sum_distinct_lpm_entries_touched"]) for r in set_rows]
    return {
        "case": case["label"],
        "mask_hex": f"0x{mask:08x}",
        "packets": total,
        "prefix0_before_percent": 100 * prefix0_before / total,
        "prefix0_after_percent": 100 * prefix0_after / total,
        "weighted_descendant_nodes_before": weighted_before,
        "weighted_descendant_nodes_after": weighted_after,
        "weighted_descendant_nodes_ratio": weighted_after / weighted_before,
        "weighted_median_nodes_before": weighted_quantile(before_items, .5),
        "weighted_median_nodes_after": weighted_quantile(after_items, .5),
        "weighted_p90_nodes_before": weighted_quantile(before_items, .9),
        "weighted_p90_nodes_after": weighted_quantile(after_items, .9),
        "corr_second_miss_vs_weighted_nodes": pearson(second, structure),
        "corr_second_miss_vs_packets": pearson(second, packets_by_set),
        "corr_second_miss_vs_distinct_routes": pearson(second, route_touch),
        "worst_sets": ",".join(str(x) for x in hot_sets),
        "worst_two_miss_share_percent": 100 * sum(after_miss[x] for x in hot_sets) / sum(after_miss.values()),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summaries = [analyze_case(case) for case in CASES]
    write_rows(OUT / "summary.csv", summaries, list(summaries[0]))
    lines = [
        "# WIDE global XOR: PS /16 subtree diagnosis",
        "",
        "`descendant route nodes` is the number of explicit routing-table prefixes longer than /16 under a /16 node.",
        "The 256-child plot assigns every route node to the /24 child cells it can affect; prefixes shorter than /24 span multiple cells.",
        "All packet-weighted statistics use the same 10,000,000 destination packets as the XOR search.",
        "",
    ]
    for s in summaries:
        lines += [
            f"## {s['case']}",
            "",
            f"- mask: `{s['mask_hex']}`",
            f"- /0 packet share: {s['prefix0_before_percent']:.4f}% → {s['prefix0_after_percent']:.4f}%",
            f"- packet-weighted descendant nodes: {s['weighted_descendant_nodes_before']:.2f} → {s['weighted_descendant_nodes_after']:.2f} ({s['weighted_descendant_nodes_ratio']:.2f}x)",
            f"- weighted median: {s['weighted_median_nodes_before']} → {s['weighted_median_nodes_after']}",
            f"- weighted p90: {s['weighted_p90_nodes_before']} → {s['weighted_p90_nodes_after']}",
            f"- two worst sets: {s['worst_sets']} ({s['worst_two_miss_share_percent']:.2f}% of cacheline misses)",
            f"- Pearson r(second miss, packet-weighted subtree nodes): {s['corr_second_miss_vs_weighted_nodes']:.4f}",
            f"- Pearson r(second miss, packets): {s['corr_second_miss_vs_packets']:.4f}",
            f"- Pearson r(second miss, distinct LPM entries touched): {s['corr_second_miss_vs_distinct_routes']:.4f}",
            "",
        ]
    (OUT / "REPORT.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
