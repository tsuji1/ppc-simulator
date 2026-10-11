#!/usr/bin/env python3
"""Convert a ClassBench trace_generator output into the simulator trace format.

ClassBench trace rows (tab separated, decimal):
    src_ip dst_ip src_port dst_port proto filter_no

Simulator rows (7 columns):
    time,len,srcIP,dstIP,proto,srcPort,dstPort

trace_generator picks either the low or the high corner of each field, so a
dst-prefix-only filter set yields only network or broadcast addresses.
``--fill-host random`` replaces the destination with a random address inside
the prefix of ``filter_no`` (the filter used for generation, not the LPM
result). One random address is drawn per burst: consecutive identical
ClassBench rows keep the same destination, so Pareto locality is preserved.
``--fill-host corner`` keeps the ClassBench destination unchanged.

src / ports / proto are fixed because they are wildcards in the filter set.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import random
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", required=True, help="ClassBench *_trace file")
    parser.add_argument("--filters", required=True, help="ClassBench filter file used to generate the trace")
    parser.add_argument("--output", required=True)
    parser.add_argument("--fill-host", choices=("random", "corner"), default="random")
    parser.add_argument("--seed", type=int, default=1, help="Seed for --fill-host random")
    parser.add_argument("--src-ip", default="192.0.2.1")
    parser.add_argument("--proto", choices=("tcp", "udp"), default="tcp")
    parser.add_argument("--packet-len", type=int, default=64)
    parser.add_argument("--src-port", type=int, default=12345)
    parser.add_argument("--dst-port", type=int, default=80)
    parser.add_argument("--time-step", type=float, default=0.000001)
    parser.add_argument("--meta", default="", help="Extra JSON object merged into the metadata file")
    return parser.parse_args()


def load_dst_prefixes(path: str) -> tuple[list[int], list[int]]:
    """Return (network, host_mask) per filter, indexed by ClassBench filter_no."""
    networks: list[int] = []
    host_masks: list[int] = []
    with open(path) as handle:
        for line in handle:
            if not line.startswith("@"):
                continue
            dst = ipaddress.IPv4Network(line.split("\t")[1], strict=False)
            networks.append(int(dst.network_address))
            host_masks.append((1 << (32 - dst.prefixlen)) - 1)
    return networks, host_masks


def int_to_ipv4(value: int) -> str:
    return f"{value >> 24}.{(value >> 16) & 255}.{(value >> 8) & 255}.{value & 255}"


def main() -> None:
    args = parse_args()
    networks, host_masks = load_dst_prefixes(args.filters)
    rng = random.Random(args.seed)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = 0
    bursts = 0
    corner_network = 0
    corner_broadcast = 0
    previous_line = None
    current_dst = 0
    with open(args.trace) as src, output.open("w") as dst:
        for line in src:
            if line != previous_line:
                fields = line.split()
                cb_dst = int(fields[1])
                filter_no = int(fields[5])
                network = networks[filter_no]
                host_mask = host_masks[filter_no]
                if cb_dst == network:
                    corner_network += 1
                elif cb_dst == network | host_mask:
                    corner_broadcast += 1
                if args.fill_host == "random":
                    current_dst = network | (rng.getrandbits(32) & host_mask)
                else:
                    current_dst = cb_dst
                bursts += 1
                previous_line = line
            dst.write(
                f"{rows * args.time_step:.6f},{args.packet_len},{args.src_ip},{int_to_ipv4(current_dst)},"
                f"{args.proto},{args.src_port},{args.dst_port}\n"
            )
            rows += 1

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "classbench_trace": str(Path(args.trace).resolve()),
        "filters": str(Path(args.filters).resolve()),
        "filter_count": len(networks),
        "output": str(output.resolve()),
        "fill_host": args.fill_host,
        "fill_seed": args.seed if args.fill_host == "random" else None,
        "rows": rows,
        "bursts": bursts,
        "classbench_corner_network_bursts": corner_network,
        "classbench_corner_broadcast_bursts": corner_broadcast,
    }
    if args.meta:
        meta.update(json.loads(args.meta))
    Path(str(output) + ".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {rows} rows ({bursts} bursts) to {output}")


if __name__ == "__main__":
    main()
