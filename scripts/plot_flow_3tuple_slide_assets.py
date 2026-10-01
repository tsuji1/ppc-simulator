#!/usr/bin/env python3
"""Generate SVG charts for 3-tuple flow analysis slides."""

from __future__ import annotations

import csv
import html
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NO_ICMP_SUMMARY = ROOT / "reports" / "flow_stats_no_icmp" / "flow_trace_summary_no_icmp.csv"
THREE_TUPLE_SUMMARY = ROOT / "reports" / "flow_stats_3tuple" / "flow_trace_summary_3tuple.csv"
OUT_DIR = ROOT / "reports" / "flow_stats_3tuple" / "slide_assets"

TRACE_ORDER = ["2025-09-27", "2025-12-27", "2026-03-27", "equinix-chicago-20140320"]
LABELS = {
    "2025-09-27": "2025-09",
    "2025-12-27": "2025-12",
    "2026-03-27": "2026-03",
    "equinix-chicago-20140320": "Equinix",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def read_data() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    five = {row["trace"]: row for row in read_csv(NO_ICMP_SUMMARY)}
    three = {
        row["trace"]: row
        for row in read_csv(THREE_TUPLE_SUMMARY)
        if row["mode"] == "3tuple_no_icmp"
    }
    return five, three


def fmt_num(value: float) -> str:
    return f"{value:,.0f}"


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

    legend_spacing = 145
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
            elif value_format == "decimal":
                text = f"{value:.2f}"
            else:
                text = fmt_num(value)
            chart.append(f'  <text x="{x+bar_w/2:.1f}" y="{y-8:.1f}" text-anchor="middle" class="value">{html.escape(text)}</text>')

    save_svg(name, "\n".join(chart))


def plot_density(five: dict[str, dict[str, str]], three: dict[str, dict[str, str]]) -> None:
    labels = [LABELS[trace] for trace in TRACE_ORDER]
    five_values = [float(five[trace]["flows_per_million_included_packets"]) for trace in TRACE_ORDER]
    three_values = [float(three[trace]["flows_per_million_packets"]) for trace in TRACE_ORDER]
    bar_chart(
        name="flow_density_5tuple_vs_3tuple_no_icmp.svg",
        title="フロー密度: ポートを無視すると下がる",
        labels=labels,
        series=[
            ("5要素", five_values, "#5B7CFA"),
            ("3要素", three_values, "#F59E0B"),
        ],
        y_max=250_000,
        y_unit="フロー数 / 100万 non-ICMP IPv4 パケット",
    )


def plot_packets_per_flow(five: dict[str, dict[str, str]], three: dict[str, dict[str, str]]) -> None:
    labels = [LABELS[trace] for trace in TRACE_ORDER]
    five_values = [float(five[trace]["packets_per_flow"]) for trace in TRACE_ORDER]
    three_values = [float(three[trace]["packets_per_flow"]) for trace in TRACE_ORDER]
    bar_chart(
        name="packets_per_flow_5tuple_vs_3tuple_no_icmp.svg",
        title="平均フロー長: 3要素ではフローが太く見える",
        labels=labels,
        series=[
            ("5要素", five_values, "#64748B"),
            ("3要素", three_values, "#14B8A6"),
        ],
        y_max=30,
        y_unit="平均パケット数 / フロー",
        value_format="decimal",
    )


def plot_tail(five: dict[str, dict[str, str]], three: dict[str, dict[str, str]]) -> None:
    labels = [LABELS[trace] for trace in TRACE_ORDER]
    five_values = [float(five[trace]["ge8192_packet_share"]) * 100 for trace in TRACE_ORDER]
    three_values = [float(three[trace]["ge8192_packet_share"]) * 100 for trace in TRACE_ORDER]
    bar_chart(
        name="tail8192_5tuple_vs_3tuple_no_icmp.svg",
        title="巨大フロー占有率: 3要素では少し上がる",
        labels=labels,
        series=[
            ("5要素", five_values, "#8B5CF6"),
            ("3要素", three_values, "#F97316"),
        ],
        y_max=55,
        y_unit="8192+ pkt/flow のパケット占有率（%）",
        value_format="percent",
    )


def main() -> None:
    five, three = read_data()
    plot_density(five, three)
    plot_packets_per_flow(five, three)
    plot_tail(five, three)


if __name__ == "__main__":
    main()
