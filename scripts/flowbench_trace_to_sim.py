#!/usr/bin/env python3
"""FlowBench の 1 field（宛先 LPM）の trace を simulator の trace 形式に変換する。

FlowBench の行（既定の書式）: ``0x<宛先の16進> <rule番号>``。rule番号は FlowBench 内部の
順番（使える bit 数で並べ替えた後）で、入力 file の順番と対応しないので使わない。
LPM は解析側で計算し直す。

simulator の行（7 列）: ``time,len,srcIP,dstIP,proto,srcPort,dstPort``。
出力と同じ場所に ``<output>.meta.json`` も書く。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", required=True, help="FlowBench の trace（flowbench-trace の出力）")
    parser.add_argument("--output", required=True, help="書き出す simulator の trace")
    parser.add_argument("--src-ip", default="192.0.2.1", help="固定の送信元アドレス")
    parser.add_argument("--proto", choices=("tcp", "udp"), default="tcp", help="固定の protocol")
    parser.add_argument("--packet-len", type=int, default=64, help="固定の packet 長")
    parser.add_argument("--src-port", type=int, default=12345, help="固定の送信元 port")
    parser.add_argument("--dst-port", type=int, default=80, help="固定の宛先 port")
    parser.add_argument("--time-step", type=float, default=0.000001, help="1 パケットごとに進める時刻（秒）")
    parser.add_argument("--meta", default="", help="meta.json に追加する JSON object（生成条件の記録用）")
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
