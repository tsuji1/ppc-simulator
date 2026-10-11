#!/usr/bin/env python3
"""Convert a FlowBench 1-field (dst LPM) trace into the simulator trace format.

FlowBench rows (default style): ``0x<dst hex> <rule index>``. The rule index
refers to FlowBench's internal order (sorted by available width), not to the
input file order, so it is ignored; LPM is recomputed by the analyzers.

Simulator rows (7 columns): ``time,len,srcIP,dstIP,proto,srcPort,dstPort``.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", required=True, help="FlowBench trace file")
    parser.add_argument("--output", required=True)
    parser.add_argument("--src-ip", default="192.0.2.1")
    parser.add_argument("--proto", choices=("tcp", "udp"), default="tcp")
    parser.add_argument("--packet-len", type=int, default=64)
    parser.add_argument("--src-port", type=int, default=12345)
    parser.add_argument("--dst-port", type=int, default=80)
    parser.add_argument("--time-step", type=float, default=0.000001)
    parser.add_argument("--meta", default="", help="Extra JSON object merged into the metadata file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    suffix = f",{args.proto},{args.src_port},{args.dst_port}\n"
    prefix = f",{args.packet_len},{args.src_ip},"
    with open(args.trace) as src, output.open("w") as dst:
        for line in src:
            value = int(line.split()[0], 16)
            ip = f"{value >> 24}.{(value >> 16) & 255}.{(value >> 8) & 255}.{value & 255}"
            dst.write(f"{rows * args.time_step:.6f}{prefix}{ip}{suffix}")
            rows += 1

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "flowbench_trace": str(Path(args.trace).resolve()),
        "output": str(output.resolve()),
        "rows": rows,
    }
    if args.meta:
        meta.update(json.loads(args.meta))
    Path(str(output) + ".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {rows} rows to {output}")


if __name__ == "__main__":
    main()
