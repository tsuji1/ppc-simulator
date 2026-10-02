#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "matplotlib>=3.9.2",
#   "pydantic-settings>=2.5.2",
#   "pymongo>=4.10.1",
# ]
# ///
"""Create slide-18-style power and miss-rate graphs for full-trace greedy transforms."""

from pathlib import Path

import plot_global_xor_cross_trace_power_miss as base


ROOT = Path(__file__).resolve().parent / "reports" / "greedy-tree-lpm-cap8192-cross-trace"
LABELS = [
    ("JPIX-SINET 2018-05", "jpix-sinet", "rrc06.bview.20180502.0000.unique.rule"),
    ("SINET-JPIX 2018-05", "sinet-jpix", "rrc06.bview.20180502.0000.unique.rule"),
    ("WIDE 2025-09", "wide-2025-09", "rib.20250927.0600.unique.rule"),
    ("WIDE 2025-12", "wide-2025-12", "rib.20251227.0600.unique.rule"),
    ("WIDE 2026-03", "wide-2026-03", "rib.20260327.0600.unique.rule"),
    ("San Jose 2014-03", "sanjose", "route-views.isc.rib.20140320.1400.unique.rule"),
    ("Chicago 2014-03", "chicago", "route-views.chicago.rib.20160628.1400.unique.rule"),
    ("New York 2019-01", "nyc", "rrc11.bview.20190117.1600.unique.rule"),
]

base.ROOT = ROOT
base.TRACE_SETS = {"original": base.TRACE_SETS["original"]}
for date in ("2025-09-27", "2025-12-27", "2026-03-27"):
    for order in ("top-down", "bottom-up"):
        condition = f"{date}-{order}"
        base.TRACE_SETS[condition] = [
            (label, f"{dataset}-to-{date}-{order}.txt", rule)
            for label, dataset, rule in LABELS
        ]

original_plot = base.plot


def greedy_plot(rows, traces, metric, ylabel, title, path):
    title = title.replace("24-bit XOR target:", "Full-trace greedy:")
    title = title.replace("-top-down:", " (top-down):")
    title = title.replace("-bottom-up:", " (bottom-up):")
    original_plot(rows, traces, metric, ylabel, title, path)


base.plot = greedy_plot

if __name__ == "__main__":
    raise SystemExit(base.main())
