#!/usr/bin/env python3
"""Generate slide charts for ICMP-excluded flow analysis.

The repository environment does not require plotting dependencies for this
task; charts are emitted as compact SVG files using only the standard library.
"""

from __future__ import annotations

import csv
import html
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SUMMARY = ROOT / "reports" / "flow_stats_no_icmp" / "flow_trace_summary_no_icmp.csv"
OUT_DIR = ROOT / "reports" / "flow_stats_no_icmp" / "slide_assets"

LABELS = {
    "2025-09-27": "2025-09",
    "2025-12-27": "2025-12",
    "2026-03-27": "2026-03",
    "equinix-sanjose-": "San Jose",
    "equinix-sanjose-20140320": "San Jose",
    "equinix-chicago-20140320": "Chicago",
    "equinix-nyc-20190117": "NYC",
    "jpix2sinet-20180502": "JPIX→SINET",
}


def read_summary() -> list[dict[str, str]]:
    with SUMMARY.open(newline="") as f:
        return list(csv.DictReader(f))


def pct(value: str) -> float:
    return float(value) * 100.0


def label_for(trace: str) -> str:
    return LABELS.get(trace, trace)


def original_density(row: dict[str, str]) -> float:
    return float(row["source_flow_count"]) * 1_000_000 / float(row["source_ipv4_packets"])


def save_svg(name: str, body: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="520" viewBox="0 0 1000 520">
  <style>
    text {{ font-family: "Yu Gothic", "Noto Sans CJK JP", "Meiryo", sans-serif; fill: #111827; }}
    .title {{ font-size: 26px; font-weight: 700; }}
    .axis {{ font-size: 16px; fill: #374151; }}
    .tick {{ font-size: 14px; fill: #475569; }}
    .legend {{ font-size: 15px; fill: #1f2937; }}
    .value {{ font-size: 14px; fill: #111827; }}
    .grid {{ stroke: #CBD5E1; stroke-width: 1; opacity: 0.65; }}
    .axisline {{ stroke: #334155; stroke-width: 1.4; }}
  </style>
  <rect width="1000" height="520" fill="#ffffff"/>
{body}
</svg>
"""
    (OUT_DIR / name).write_text(svg)


def fmt_num(value: float) -> str:
    return f"{value:,.0f}"


def bar_chart(
    *,
    name: str,
    title: str,
    labels: list[str],
    series: list[tuple[str, list[float], str]],
    y_max: float,
    y_unit: str,
    value_format: str = "number",
) -> None:
    width, height = 1000, 520
    left, right, top, bottom = 90, 40, 100, 86
    plot_w = width - left - right
    plot_h = height - top - bottom
    group_w = plot_w / len(labels)
    bar_gap = 8
    bar_w = min(58, (group_w * 0.72 - bar_gap * (len(series) - 1)) / len(series))
    chart = []
    chart.append(f'  <text x="{left}" y="36" class="title">{html.escape(title)}</text>')
    chart.append(f'  <text x="{left}" y="68" class="axis">{html.escape(y_unit)}</text>')

    for i in range(6):
        value = y_max * i / 5
        y = top + plot_h - (value / y_max) * plot_h
        chart.append(f'  <line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="grid"/>')
        chart.append(f'  <text x="{left-12}" y="{y+5:.1f}" text-anchor="end" class="tick">{html.escape(fmt_num(value))}</text>')

    chart.append(f'  <line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" class="axisline"/>')
    chart.append(f'  <line x1="{left}" y1="{top+plot_h}" x2="{width-right}" y2="{top+plot_h}" class="axisline"/>')

    legend_spacing = 130
    legend_x = width - right - (len(series) * legend_spacing)
    for idx, (label, _values, color) in enumerate(series):
        lx = legend_x + idx * legend_spacing
        chart.append(f'  <rect x="{lx}" y="54" width="18" height="18" fill="{color}" rx="3"/>')
        chart.append(f'  <text x="{lx+26}" y="69" class="legend">{html.escape(label)}</text>')

    for group_idx, label in enumerate(labels):
        center = left + group_w * group_idx + group_w / 2
        group_bar_total = len(series) * bar_w + (len(series) - 1) * bar_gap
        start_x = center - group_bar_total / 2
        chart.append(f'  <text x="{center:.1f}" y="{top+plot_h+34}" text-anchor="middle" class="axis">{html.escape(label)}</text>')
        for series_idx, (_series_label, values, color) in enumerate(series):
            value = values[group_idx]
            bar_h = (value / y_max) * plot_h
            x = start_x + series_idx * (bar_w + bar_gap)
            y = top + plot_h - bar_h
            chart.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="4"/>')
            if value_format == "percent":
                text = f"{value:.1f}%"
            else:
                text = fmt_num(value)
            chart.append(f'  <text x="{x+bar_w/2:.1f}" y="{y-8:.1f}" text-anchor="middle" class="value">{html.escape(text)}</text>')

    save_svg(name, "\n".join(chart))


def plot_density(rows: list[dict[str, str]]) -> None:
    labels = [label_for(r["trace"]) for r in rows]
    original = [original_density(r) for r in rows]
    no_icmp = [float(r["flows_per_million_included_packets"]) for r in rows]
    bar_chart(
        name="flow_density_no_icmp_compare.svg",
        title="フロー密度: ICMP 除外で非匿名 trace は大きく低下",
        labels=labels,
        series=[
            ("ICMP 込み", original, "#5B7CFA"),
            ("ICMP 除外", no_icmp, "#F59E0B"),
        ],
        y_max=500_000,
        y_unit="フロー数 / 100万 IPv4 パケット",
    )


def plot_icmp_share(rows: list[dict[str, str]]) -> None:
    labels = [label_for(r["trace"]) for r in rows]
    packet = [pct(r["excluded_icmp_packet_ratio_of_source_ipv4"]) for r in rows]
    flow = [pct(r["excluded_icmp_flow_ratio_of_source_flows"]) for r in rows]
    bar_chart(
        name="icmp_flow_packet_share.svg",
        title="ICMP はフロー数を増やすが、パケット比率はそこまで大きくない",
        labels=labels,
        series=[
            ("パケット比率", packet, "#10B981"),
            ("フロー比率", flow, "#EF4444"),
        ],
        y_max=70,
        y_unit="ICMP の比率（%）",
        value_format="percent",
    )


def plot_tail(rows: list[dict[str, str]]) -> None:
    labels = [label_for(r["trace"]) for r in rows]
    ge1024 = [pct(r["ge1024_packet_share"]) for r in rows]
    ge8192 = [pct(r["ge8192_packet_share"]) for r in rows]
    top100 = [pct(r["top100_packet_share"]) for r in rows]
    bar_chart(
        name="large_tail_no_icmp_packet_share.svg",
        title="ICMP 除外後も少数の大きなフローにパケットが集中",
        labels=labels,
        series=[
            ("上位100", top100, "#64748B"),
            ("1024+", ge1024, "#14B8A6"),
            ("8192+", ge8192, "#F97316"),
        ],
        y_max=70,
        y_unit="パケット占有率（%）",
        value_format="percent",
    )


def main() -> None:
    rows = read_summary()
    plot_density(rows)
    plot_icmp_share(rows)
    plot_tail(rows)


if __name__ == "__main__":
    main()
