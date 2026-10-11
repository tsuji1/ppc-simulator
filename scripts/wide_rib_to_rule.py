#!/usr/bin/env python3
import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


CSV_HEADERS = [
    "BGP_PROTOCOL",
    "TIMESTAMP",
    "TYPE",
    "PEER_IP",
    "PEER_ASN",
    "PREFIX",
    "AS_PATH",
    "ORIGIN",
    "NEXT_HOP",
    "LOCAL_PREF",
    "MED",
    "COMMUNITY",
    "ATOMIC_AGGREGATE",
    "AGGREGATOR",
]

# aloheart の rules/rib.*.unique.rule と wide.rib.20240625.1400.unique.rule の先頭行と同じ値。
# RIB には default route が無いので、これを先頭に足すと既存 rule とバイト単位で一致する。
DEFAULT_ROUTE_NEXT_HOP = "b848d6e8-d386-420e-bec0-292cba45c389"


def ask_if_none(value: str | None, prompt: str) -> str:
    if value:
        return value
    return input(prompt).strip()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download Route Views RIB, run bgpdump -m, and generate CSV / rule / unique.rule. "
            "e.g. --date 2025-09-27 --time 15:00 --ipv4-only -> rib.20250927.0600.unique.rule"
        )
    )
    parser.add_argument("--date", help="Input date in local timezone, e.g. 2025-06-26")
    parser.add_argument("--time", help="Input time in local timezone, e.g. 05:00")
    parser.add_argument(
        "--tz",
        default="Asia/Tokyo",
        help="Timezone of input datetime (default: Asia/Tokyo)",
    )
    parser.add_argument(
        "--collector",
        default="route-views.wide",
        help="Collector name (default: route-views.wide)",
    )
    parser.add_argument(
        "--outdir",
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--ipv4-only",
        action="store_true",
        help="Skip IPv6 prefixes",
    )
    parser.add_argument(
        "--keep-bz2",
        action="store_true",
        help="Keep downloaded bz2 file",
    )
    parser.add_argument(
        "--default-next-hop",
        default=DEFAULT_ROUTE_NEXT_HOP,
        help="Next hop of the 0.0.0.0/0 line prepended to .unique.rule (default: the UUID used in /home/yuzugon/rules)",
    )
    parser.add_argument(
        "--no-add-default",
        action="store_true",
        help="Do not prepend 0.0.0.0/0 to .unique.rule",
    )
    return parser.parse_args()


def local_to_utc(date_str: str, time_str: str, tz_name: str) -> datetime:
    local_tz = ZoneInfo(tz_name)
    local_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    local_dt = local_dt.replace(tzinfo=local_tz)
    return local_dt.astimezone(ZoneInfo("UTC"))


def validate_rib_time(dt_utc: datetime):
    if dt_utc.minute != 0 or dt_utc.hour % 2 != 0:
        raise ValueError(
            f"Route Views RIB time must be every 2 hours in UTC. got={dt_utc:%Y-%m-%d %H:%M UTC}"
        )


def build_url(dt_utc: datetime, collector: str) -> tuple[str, str]:
    yyyymm = dt_utc.strftime("%Y.%m")
    stamp = dt_utc.strftime("%Y%m%d.%H%M")
    filename = f"rib.{stamp}.bz2"
    url = f"https://archive.routeviews.org/{collector}/bgpdata/{yyyymm}/RIBS/{filename}"
    return url, filename


def download_file(url: str, dst: Path):
    if dst.exists():
        print(f"[+] already exists: {dst}")
        return

    print(f"[+] downloading: {url}")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req) as resp, open(dst, "wb") as f:
        if getattr(resp, "status", 200) != 200:
            raise RuntimeError(f"download failed: HTTP {resp.status}")
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def run_bgpdump_to_csv_and_rule(
    bz2_path: Path,
    csv_path: Path,
    rule_path: Path,
    unique_rule_path: Path,
    ipv4_only: bool,
    default_next_hop: str | None,
):
    print(f"[+] running: bgpdump -m {bz2_path}")

    proc = subprocess.Popen(
        ["bgpdump", "-m", str(bz2_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert proc.stdout is not None
    assert proc.stderr is not None

    seen_prefixes = set()
    total_rule_count = 0
    unique_rule_count = 0

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile, \
         open(rule_path, "w", encoding="utf-8") as rulefile, \
         open(unique_rule_path, "w", encoding="utf-8") as unique_rulefile:

        writer = csv.writer(csvfile)
        writer.writerow(CSV_HEADERS)

        if default_next_hop:
            seen_prefixes.add("0.0.0.0/0")
            unique_rulefile.write(f"0.0.0.0 0 {default_next_hop}\n")
            unique_rule_count += 1

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue

            parts = line.split("|")

            while len(parts) < 14:
                parts.append("")
            row = parts[:14]

            prefix = row[5]
            next_hop = row[8]

            if ipv4_only and ":" in prefix:
                continue

            writer.writerow(row)

            if prefix and next_hop:
                rule_line = f"{prefix.replace('/', ' ', 1)} {next_hop}\n"
                rulefile.write(rule_line)
                total_rule_count += 1

                if prefix not in seen_prefixes:
                    seen_prefixes.add(prefix)
                    unique_rulefile.write(rule_line)
                    unique_rule_count += 1

    stderr = proc.stderr.read()
    ret = proc.wait()

    if ret != 0:
        raise RuntimeError(f"bgpdump failed (exit={ret})\n{stderr}")

    print(f"[+] wrote csv        : {csv_path}")
    print(f"[+] wrote rule       : {rule_path}")
    print(f"[+] wrote unique rule: {unique_rule_path}")
    print(f"[+] rule count       : {total_rule_count}")
    print(f"[+] unique prefixes  : {unique_rule_count}")


def main():
    args = parse_args()

    date_str = ask_if_none(args.date, "Date (YYYY-MM-DD): ")
    time_str = ask_if_none(args.time, "Time (HH:MM): ")

    dt_utc = local_to_utc(date_str, time_str, args.tz)
    validate_rib_time(dt_utc)

    url, bz2_name = build_url(dt_utc, args.collector)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    bz2_path = outdir / bz2_name
    base = bz2_name.removesuffix(".bz2")
    csv_path = outdir / f"{base}.csv"
    rule_path = outdir / f"{base}.rule"
    unique_rule_path = outdir / f"{base}.unique.rule"

    download_file(url, bz2_path)
    run_bgpdump_to_csv_and_rule(
        bz2_path=bz2_path,
        csv_path=csv_path,
        rule_path=rule_path,
        unique_rule_path=unique_rule_path,
        ipv4_only=args.ipv4_only,
        default_next_hop=None if args.no_add_default else args.default_next_hop,
    )

    if not args.keep_bz2:
        bz2_path.unlink(missing_ok=True)
        print(f"[+] removed: {bz2_path}")

    print()
    print(f"local input : {date_str} {time_str} ({args.tz})")
    print(f"utc used    : {dt_utc:%Y-%m-%d %H:%M}")
    print(f"url         : {url}")
    print(f"csv         : {csv_path}")
    print(f"rule        : {rule_path}")
    print(f"unique rule : {unique_rule_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)
