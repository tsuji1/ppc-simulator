#!/usr/bin/env python3
"""ClassBench の trace_generator の出力を simulator の trace 形式に変換する。

ClassBench の trace の行（tab 区切り、10 進）:
    src_ip dst_ip src_port dst_port proto filter番号

simulator の trace の行（7 列）:
    time,len,srcIP,dstIP,proto,srcPort,dstPort

trace_generator は各 field の下端か上端（corner）しか出さないので、宛先 prefix だけの
filter set からは network address か broadcast address しか出ない。
``--fill-host random`` は宛先を、filter番号の prefix（生成に使った filter。LPM の結果ではない）
の中の random なアドレスに置き換える。random なアドレスは burst ごとに 1 つ選ぶ:
ClassBench の同じ行が続く間は同じ宛先にするので、Pareto の局所性は保たれる。
``--fill-host corner`` は ClassBench の宛先をそのまま使う。

src・port・proto は filter set で wildcard なので固定値にする。
出力と同じ場所に ``<output>.meta.json`` も書く。
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
    parser.add_argument("--trace", required=True, help="ClassBench の trace（trace_generator の *_trace）")
    parser.add_argument("--filters", required=True, help="trace の生成に使った ClassBench の filter file")
    parser.add_argument("--output", required=True, help="書き出す simulator の trace")
    parser.add_argument("--fill-host", choices=("random", "corner"), default="random", help="宛先の host 部の埋め方")
    parser.add_argument("--seed", type=int, default=1, help="--fill-host random の seed")
    parser.add_argument("--src-ip", default="192.0.2.1", help="固定の送信元アドレス")
    parser.add_argument("--proto", choices=("tcp", "udp"), default="tcp", help="固定の protocol")
    parser.add_argument("--packet-len", type=int, default=64, help="固定の packet 長")
    parser.add_argument("--src-port", type=int, default=12345, help="固定の送信元 port")
    parser.add_argument("--dst-port", type=int, default=80, help="固定の宛先 port")
    parser.add_argument("--time-step", type=float, default=0.000001, help="1 パケットごとに進める時刻（秒）")
    parser.add_argument("--meta", default="", help="meta.json に追加する JSON object（生成条件の記録用）")
    return parser.parse_args()


def load_dst_prefixes(path: str) -> tuple[list[int], list[int]]:
    """filter ごとの (network, host_mask) を ClassBench の filter番号順に返す。"""
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
