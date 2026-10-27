#!/usr/bin/env python3
"""routing の rule file を、互いに重ならない FlowBench の rule set（1 field の LPM）に変換する。

FlowBench の trace 生成は、まず各 rule を「その rule にしか当たらない領域」に切り出す
（isolation）。元の実装は O(n^2) で、FIB 全体（約 100 万 prefix）では実用的な時間で終わらず、
完全に覆われた rule があると isolation 自体を中止してしまう。そこで LPM 専用に
O(n log n) で切り出してから渡す:

  * prefix の到達領域 = prefix − より長い（子の）prefix の領域
  * 到達領域が空（完全に覆われている）prefix は捨てる。LPM の結果に絶対にならないため
  * 到達領域を aligned block に分け、最大の block をその prefix の代表 rule として書く
    （FlowBench も 1 rule につき切り出した片を 1 つしか使わない）

出力は 1 つの LPM field の ClassBench 風書式（``@1.0.0.0/24``）で、
``flowbench-trace --isolated -f 1 -fw 32 -ft LPM`` に渡す。
``<output>.map`` には出力順に ``代表block 元prefix 到達領域のアドレス数`` を、
``<output>.meta.json`` には件数と block 長の分布を書く。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rule-file", required=True, help="入力の rule file（<ip> <prefix長> <nexthop>）")
    parser.add_argument("--output", required=True, help="書き出す FlowBench の rule file")
    return parser.parse_args()


def ip_to_int(text: str) -> int:
    a, b, c, d = map(int, text.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def int_to_ip(value: int) -> str:
    return f"{value >> 24}.{(value >> 16) & 255}.{(value >> 8) & 255}.{value & 255}"


def largest_block(lo: int, hi: int) -> tuple[int, int]:
    """[lo, hi) に含まれる、2 のべき乗で align された最大の block を (start, size) で返す。"""
    best = (lo, 0)
    while lo < hi:
        size = lo & -lo if lo else 1 << 32
        while lo + size > hi:
            size >>= 1
        if size > best[1]:
            best = (lo, size)
        lo += size
    return best


def main() -> None:
    args = parse_args()
    prefixes = []
    with open(args.rule_file) as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 2 or int(fields[1]) == 0:
                continue
            prefixes.append((ip_to_int(fields[0]), int(fields[1])))
    prefixes.sort()

    # 各 prefix の直接の子を、包含関係の stack で求める
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

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    dropped = 0
    split = 0
    block_lengths: Counter[int] = Counter()
    with output.open("w") as rules, Path(str(output) + ".map").open("w") as mapping:
        for i, (net, length) in enumerate(prefixes):
            end = net + (1 << (32 - length))
            cursor = net
            region = 0
            best = (net, 0)
            for child in children[i]:
                cnet, clen = prefixes[child]
                if cnet > cursor:
                    region += cnet - cursor
                    candidate = largest_block(cursor, cnet)
                    if candidate[1] > best[1]:
                        best = candidate
                cursor = cnet + (1 << (32 - clen))
            if end > cursor:
                region += end - cursor
                candidate = largest_block(cursor, end)
                if candidate[1] > best[1]:
                    best = candidate
            if region == 0:
                dropped += 1
                continue
            if children[i]:
                split += 1
            block_len = 32 - (best[1].bit_length() - 1)
            block_lengths[block_len] += 1
            rules.write(f"@{int_to_ip(best[0])}/{block_len}\n")
            mapping.write(f"{int_to_ip(best[0])}/{block_len} {int_to_ip(net)}/{length} {region}\n")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_file": str(Path(args.rule_file).resolve()),
        "prefixes_without_default": len(prefixes),
        "dropped_fully_covered": dropped,
        "written": len(prefixes) - dropped,
        "represented_by_sub_block": split,
        "block_length_counts": {str(k): v for k, v in sorted(block_lengths.items())},
    }
    Path(str(output) + ".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: v for k, v in meta.items() if k != "block_length_counts"}))


if __name__ == "__main__":
    main()
