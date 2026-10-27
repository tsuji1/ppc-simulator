#!/usr/bin/env python3
"""FlowBench の trace で、1 rule に割り当てられた flow 数と packet 数の分布を集計する。

FlowBench は rule ごとの packet 数（``-rd``）と flow ごとの packet 数（``-fd``）を決めたあと、
flow 数の多い group から順に「flow 数を収容できる rule（使える bit 数 >= log2(flow 数)）」へ
割り当てる。``fib-flowbench isolate``（third_party/fib-flowbench）は各 prefix を代表 block（多くは /24）にするので、
257 flow 以上の group は代表 /24 には入らない。その影響の大きさを trace から測る。

* 宛先 1 つを 1 flow とする（FlowBench の flow は宛先 1 点の exact rule）
* 宛先が入る代表 block を ``<rule>.map`` から求め、元 FIB の LPM 結果（元 prefix）も同じ map で得る。
  代表 block は元 prefix の到達領域の中にあるので、block 内の宛先の LPM は必ず元 prefix になる

出力:
  ``<out-dir>/<label>.rules.csv``  使われた rule ごとの 代表block, block長, 元prefix長, flow数, packet数
  ``<out-dir>/<label>.summary.json``  flow 数の区間別・prefix 長別の rule 数と packet 数
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

# flow 数の区間（上限を含む）。256 は /24 に収まる上限
FLOW_BUCKETS = [(1, 1), (2, 16), (17, 256), (257, 4096), (4097, 65536), (65537, 1 << 32)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", required=True, help="flowbench-trace の出力（0x<宛先> <rule番号>）")
    parser.add_argument("--map", required=True, help="fib-flowbench isolate が書いた <rule>.map")
    parser.add_argument("--label", required=True, help="出力 file 名に使う条件名")
    parser.add_argument("--out-dir", required=True, help="出力先")
    return parser.parse_args()


def ip_to_int(text: str) -> int:
    a, b, c, d = map(int, text.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def bucket_name(lo: int, hi: int) -> str:
    return f"{lo}" if lo == hi else (f"{lo}-" if hi >= 1 << 32 else f"{lo}-{hi}")


def main() -> None:
    args = parse_args()
    blocks = []
    with open(args.map) as handle:
        for line in handle:
            block, orig, _region = line.split()
            bnet, blen = block.split("/")
            olen = int(orig.split("/")[1])
            blocks.append((ip_to_int(bnet), int(blen), olen, block))
    blocks.sort()
    starts = [b[0] for b in blocks]
    candidate_lengths = Counter(b[1] for b in blocks)

    packets: Counter[int] = Counter()
    flows: dict[int, set[int]] = defaultdict(set)
    total = 0
    outside = 0
    with open(args.trace) as handle:
        for line in handle:
            if not line.startswith("0x"):
                continue
            dst = int(line.split()[0], 16)
            total += 1
            i = bisect.bisect_right(starts, dst) - 1
            if i < 0 or dst >= blocks[i][0] + (1 << (32 - blocks[i][1])):
                outside += 1
                continue
            packets[i] += 1
            flows[i].add(dst)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{args.label}.rules.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["block", "block_len", "orig_len", "flows", "packets"])
        for i in sorted(packets, key=lambda k: -packets[k]):
            writer.writerow([blocks[i][3], blocks[i][1], blocks[i][2], len(flows[i]), packets[i]])

    inside = total - outside
    by_bucket = []
    for lo, hi in FLOW_BUCKETS:
        rules = [i for i in packets if lo <= len(flows[i]) <= hi]
        pk = sum(packets[i] for i in rules)
        pk24 = sum(packets[i] for i in rules if blocks[i][1] == 24)
        by_bucket.append({
            "flows": bucket_name(lo, hi),
            "rules": len(rules),
            "rule_share": len(rules) / len(packets) if packets else 0,
            "packets": pk,
            "packet_share": pk / inside if inside else 0,
            "block24_packet_share_in_bucket": pk24 / pk if pk else 0,
        })

    def by_length(index: int) -> dict[str, dict[str, float]]:
        rules: Counter[int] = Counter()
        pk: Counter[int] = Counter()
        for i, count in packets.items():
            rules[blocks[i][index]] += 1
            pk[blocks[i][index]] += count
        return {
            str(length): {
                "rules": rules[length],
                "rule_share": rules[length] / len(packets),
                "packets": pk[length],
                "packet_share": pk[length] / inside,
            }
            for length in sorted(rules)
        }

    small = [i for i in packets if len(flows[i]) <= 256]
    block24_orig_shorter = sum(packets[i] for i in packets if blocks[i][1] == 24 and blocks[i][2] < 24)
    summary = {
        "label": args.label,
        "trace": str(Path(args.trace).resolve()),
        "packets": total,
        "packets_outside_blocks": outside,
        "rules_in_set": len(blocks),
        "rules_used": len(packets),
        "distinct_dst": sum(len(s) for s in flows.values()),
        "max_flows_per_rule": max((len(s) for s in flows.values()), default=0),
        "rules_le256_flows_share": len(small) / len(packets) if packets else 0,
        "packets_in_rules_le256_flows_share": sum(packets[i] for i in small) / inside if inside else 0,
        "candidate_block_length_share": {str(k): v / len(blocks) for k, v in sorted(candidate_lengths.items())},
        "by_flow_bucket": by_bucket,
        "by_block_length": by_length(1),
        "by_orig_lpm_length": by_length(2),
        "block24_but_orig_shorter_packet_share": block24_orig_shorter / inside if inside else 0,
    }
    (out_dir / f"{args.label}.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in (
        "label", "rules_used", "rules_le256_flows_share", "packets_in_rules_le256_flows_share", "max_flows_per_rule")}))


if __name__ == "__main__":
    main()
