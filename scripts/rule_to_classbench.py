#!/usr/bin/env python3
"""routing の rule file を ClassBench の filter set に変換する。

入力 rule の形式: 1 行 1 prefix で ``<ip> <prefix長> <nexthop>``。
各 prefix を、宛先 field にその prefix を入れ、他の field をすべて wildcard にした
5-tuple filter にする:

    @0.0.0.0/0<TAB>1.0.0.0/24<TAB>0 : 65535<TAB>0 : 65535<TAB>0x00/0x00

default route（/0）は既定で除く。残すと ClassBench が 0.0.0.0 / 255.255.255.255 の
corner header を出すため。重なりのある prefix はそのまま残す（1 行を 1 行に変換するだけ）。

ClassBench の trace_generator は filter を入力順に 0 から番号付けするので、
trace の filter 番号はこの出力の行番号（0 始まり）に対応する（classbench_trace_to_sim.py で使う）。
出力と同じ場所に ``<output>.meta.json``（件数と prefix 長の分布）も書く。
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
    parser.add_argument("--rule-file", required=True, help="入力の rule file（<ip> <prefix長> <nexthop>）")
    parser.add_argument("--output", required=True, help="書き出す ClassBench の filter file")
    parser.add_argument("--keep-default", action="store_true", help="/0 の default route を残す")
    parser.add_argument("--max", type=int, default=0, help="書き出す filter 数の上限。0 なら全部")
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
