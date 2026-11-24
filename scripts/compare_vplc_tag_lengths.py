#!/usr/bin/env python3
"""Paired UnifiedCache tag-length trials on the real traces from #124."""

import argparse
import csv
import itertools
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

TRACE_NAMES = ("WIDE 26-03", "Academic A 2018-05", "San Jose", "Chicago", "New York", "CAIDA 25-03 A")
CAPACITIES = (1024, 8192)
TAGS = ("9-24", "1-24", "9-32", "1-32")
INDEXES = {"118": "direct /18", "18": "CRC /18", "50": "ideal-entry"}
WAY = 8


def run_trial(binary, out, packets, trial):
    (label, trace, rule), capacity, tag = trial
    slug = f"{label.replace(' ', '_')}_{capacity}_{tag}"
    output_csv = out / f"{slug}.csv"
    breakdown = out / f"{slug}.json"
    log = out / f"{slug}.log"
    with log.open("w") as output:
        command = [
            str(binary), "-rulefile", rule, "-trace", trace,
            "-max", str(packets), "-windows", str(packets), "-progress-interval", "0",
            "-way", str(WAY), "-cache-tag-length", ",".join([tag] * WAY),
            "-insertion-policy", "exclusive", "-mp-configs", "none",
            "-ps-capacity", str(capacity), "-ps-index-types", ",".join(INDEXES),
            "-output-dir", str(out), "-output-csv", str(output_csv),
            "-breakdown-json", str(breakdown), "-breakdown-window", "1000000",
        ]
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)
    with output_csv.open(newline="") as source:
        rows = {row["cache_index_type"]: row for row in csv.DictReader(source)}
    details = json.loads(breakdown.read_text())
    if rows.keys() != INDEXES.keys() or not 0 < details["packets"] <= packets:
        raise ValueError(f"unexpected simulator output for {slug}")
    for row in rows.values():
        if int(row["packets"]) != details["packets"] or int(row["start_packet"]) != 0:
            raise ValueError(f"inconsistent packet window for {slug}")
    print(f"done {label}, {capacity} entries, tags {tag}", flush=True)
    return rows, details


def write_csv(path, rows):
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(out, traces, trials):
    results = []
    summary = []
    for label, capacity, index in itertools.product(traces, CAPACITIES, INDEXES):
        raw = {tag: trials[label, capacity, tag] for tag in TAGS}
        counts = {details["packets"] for _, details in raw.values()}
        if len(counts) != 1:
            raise ValueError(f"unequal packet counts for {label}, capacity {capacity}")
        packets = counts.pop()
        hits = {tag: int(rows[index]["hits"]) for tag, (rows, _) in raw.items()}
        results.append({
            "trace": label,
            "entries": capacity,
            "index": INDEXES[index],
            "packets": packets,
            **{f"hit_pct_{tag}": f"{100 * hits[tag] / packets:.6f}" for tag in TAGS},
            **{f"delta_pp_{tag}": f"{100 * (hits[tag] - hits['9-24']) / packets:.6f}" for tag in TAGS[1:]},
            **{f"rejected_pct_{tag}": f"{100 * raw[tag][1]['rejected'] / packets:.6f}" for tag in TAGS},
        })

    for capacity, index in itertools.product(CAPACITIES, INDEXES.values()):
        group = [row for row in results if row["entries"] == capacity and row["index"] == index]
        deltas = [float(row["delta_pp_1-32"]) for row in group]
        summary.append({
            "entries": capacity,
            "index": index,
            "traces": len(group),
            **{f"mean_delta_pp_{tag}": f"{mean(float(row[f'delta_pp_{tag}']) for row in group):.6f}" for tag in TAGS[1:]},
            "min_delta_pp_1-32": f"{min(deltas):.6f}",
            "max_delta_pp_1-32": f"{max(deltas):.6f}",
        })

    write_csv(out / "paired.csv", results)
    write_csv(out / "summary.csv", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_list", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--packets", type=int, default=10_000_000)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)
    traces = {}
    with args.trace_list.open(newline="") as source:
        for label, trace, rule in csv.reader((line for line in source if not line.startswith("#")), delimiter="\t"):
            if label in TRACE_NAMES:
                traces[label] = (label, trace, rule)
    selected = [traces[name] for name in TRACE_NAMES]

    binary = raw_dir / "windowed_hitrate"
    subprocess.run([os.environ.get("GO", "go"), "build", "-o", binary, "./cmd/windowed_hitrate"], check=True)
    trials = list(itertools.product(selected, CAPACITIES, TAGS))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        pending = [pool.submit(run_trial, binary, raw_dir, args.packets, trial) for trial in trials]
        results = {
            (record[0], capacity, tag): future.result()
            for (record, capacity, tag), future in zip(trials, pending, strict=True)
        }
    summarize(out, TRACE_NAMES, results)


if __name__ == "__main__":
    main()

