#!/usr/bin/env python3
"""Convert a routing rule file into a ClassBench filter set.

Input rule format: ``<ip> <prefix_len> <nexthop>`` (one prefix per line).
Each prefix becomes a 5-tuple filter whose destination field is the prefix
and every other field is a wildcard:

    @0.0.0.0/0<TAB>1.0.0.0/24<TAB>0 : 65535<TAB>0 : 65535<TAB>0x00/0x00

The default route (/0) is skipped by default because ClassBench would emit
0.0.0.0 / 255.255.255.255 corner headers for it.

ClassBench's trace_generator numbers filters from 0 in input order, so a
side-car ``.map`` file can be written that lists ``filter_no prefix nexthop``
for later post-processing (see classbench_trace_to_sim.py).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule-file", required=True)
    parser.add_argument("--output", required=True, help="ClassBench filter file to write")
    parser.add_argument("--keep-default", action="store_true", help="Keep the /0 default route")
    parser.add_argument("--max", type=int, default=0, help="Maximum filters to write; 0 writes all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_default = 0
    skipped_invalid = 0
    length_counts: Counter[int] = Counter()
    with open(args.rule_file) as src, output.open("w") as dst:
        for line in src:
            fields = line.split()
            if len(fields) < 2:
                continue
            try:
                network = ipaddress.IPv4Network(f"{fields[0]}/{fields[1]}", strict=True)
            except ValueError:
                skipped_invalid += 1
                continue
            if network.prefixlen == 0 and not args.keep_default:
                skipped_default += 1
                continue
            dst.write(f"@0.0.0.0/0\t{network}\t0 : 65535\t0 : 65535\t0x00/0x00\n")
            length_counts[network.prefixlen] += 1
            written += 1
            if args.max and written >= args.max:
                break

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_file": str(Path(args.rule_file).resolve()),
        "output": str(output.resolve()),
        "filters": written,
        "skipped_default": skipped_default,
        "skipped_invalid": skipped_invalid,
        "prefix_length_counts": {str(k): v for k, v in sorted(length_counts.items())},
    }
    Path(str(output) + ".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {written} filters to {output} (skipped default={skipped_default}, invalid={skipped_invalid})")


if __name__ == "__main__":
    main()
