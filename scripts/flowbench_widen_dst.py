#!/usr/bin/env python3
"""Spread FlowBench destinations over the whole hittable region of each prefix.

``fib_to_flowbench.py`` writes only the largest aligned block of a prefix's
hittable region (prefix minus its more-specific prefixes), so FlowBench puts
every destination of that prefix into that one block. The other blocks never
appear in the trace, and the cache sees fewer distinct entries (leaf blocks,
/24 or /18 blocks) per prefix than it would with real traffic.

This script rewrites a simulator trace made by ``flowbench_trace_to_sim.py``:
a destination at offset o of a truncated prefix's representative block (size
B) is mapped to a random position in [o*R/B, (o+1)*R/B) of the prefix's whole
region (all aligned blocks, size R, in address order). The mapping is a
deterministic, one-to-one function of (destination, seed), so repeated
destinations (flows) stay repeated, distinct ones stay distinct, and the
per-prefix packet counts do not change. Destinations of other prefixes are
left as they are.
"""

from __future__ import annotations

import argparse
import bisect
import json
from datetime import datetime, timezone
from pathlib import Path

from fib_to_flowbench import int_to_ip, ip_to_int, largest_block

MASK64 = (1 << 64) - 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule-file", required=True, help="rule file given to fib_to_flowbench.py")
    parser.add_argument("--trace", required=True, help="simulator trace from flowbench_trace_to_sim.py")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args()


def aligned_blocks(lo: int, hi: int) -> list[tuple[int, int]]:
    """Maximal aligned power-of-two blocks covering [lo, hi): [(start, size)]."""
    blocks = []
    while lo < hi:
        size = lo & -lo if lo else 1 << 32
        while lo + size > hi:
            size >>= 1
        blocks.append((lo, size))
        lo += size
    return blocks


def truncated_regions(rule_file: str) -> list[tuple[int, int, list[tuple[int, int]], list[int]]]:
    """(block start, block size, region blocks, cumulative sizes) for prefixes whose region is not one block."""
    prefixes = []
    with open(rule_file) as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 2 or int(fields[1]) == 0:
                continue
            prefixes.append((ip_to_int(fields[0]), int(fields[1])))
    prefixes.sort()

    # same containment stack as fib_to_flowbench.py
    children: list[list[int]] = [[] for _ in prefixes]
    stack: list[int] = []
    for i, (net, length) in enumerate(prefixes):
        while stack:
            pnet, plen = prefixes[stack[-1]]
            if net < pnet + (1 << (32 - plen)):
                break
            stack.pop()
        if stack:
            children[stack[-1]].append(i)
        stack.append(i)

    regions = []
    for i, (net, length) in enumerate(prefixes):
        if not children[i]:
            continue
        end = net + (1 << (32 - length))
        cursor = net
        blocks: list[tuple[int, int]] = []
        best = (net, 0)
        for child in children[i]:
            cnet, clen = prefixes[child]
            if cnet > cursor:
                blocks += aligned_blocks(cursor, cnet)
                candidate = largest_block(cursor, cnet)
                if candidate[1] > best[1]:
                    best = candidate
            cursor = cnet + (1 << (32 - clen))
        if end > cursor:
            blocks += aligned_blocks(cursor, end)
            candidate = largest_block(cursor, end)
            if candidate[1] > best[1]:
                best = candidate
        if len(blocks) < 2:
            continue
        cumulative = []
        total = 0
        for _, size in blocks:
            total += size
            cumulative.append(total)
        regions.append((best[0], best[1], blocks, cumulative))
    regions.sort()
    return regions


def mix(value: int) -> int:
    """splitmix64 finalizer."""
    value = (value + 0x9E3779B97F4A7C15) & MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    return value ^ (value >> 31)


def main() -> None:
    args = parse_args()
    regions = truncated_regions(args.rule_file)
    starts = [r[0] for r in regions]
    salt = mix(args.seed)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    packets = moved = 0
    cache: dict[int, int] = {}
    with open(args.trace) as src, output.open("w") as dst:
        for line in src:
            fields = line.split(",")
            if len(fields) < 7:
                dst.write(line)
                continue
            packets += 1
            ip = ip_to_int(fields[3])
            k = bisect.bisect_right(starts, ip) - 1
            if k >= 0 and ip < regions[k][0] + regions[k][1]:
                new = cache.get(ip)
                if new is None:
                    start, size, blocks, cumulative = regions[k]
                    lo = (ip - start) * cumulative[-1] // size
                    hi = (ip - start + 1) * cumulative[-1] // size
                    offset = lo + mix(ip ^ salt) % (hi - lo)
                    j = bisect.bisect_right(cumulative, offset)
                    new = blocks[j][0] + offset - (cumulative[j - 1] if j else 0)
                    cache[ip] = new
                fields[3] = int_to_ip(new)
                moved += 1
                line = ",".join(fields)
            dst.write(line)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_trace": str(Path(args.trace).resolve()),
        "rule_file": str(Path(args.rule_file).resolve()),
        "seed": args.seed,
        "truncated_prefixes": len(regions),
        "packets": packets,
        "moved_packets": moved,
        "moved_distinct_dst": len(cache),
        "distinct_new_dst": len(set(cache.values())),
    }
    Path(str(output) + ".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
