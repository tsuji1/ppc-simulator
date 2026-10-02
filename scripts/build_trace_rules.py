#!/usr/bin/env python3
"""Build simulator rule files from BGP RIB dumps chosen for known traces."""

from __future__ import annotations

import argparse
import bz2
import gzip
import ipaddress
import os
import re
import subprocess
import shutil
import struct
import sys
import tempfile
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TABLE_DUMP_V2 = 13
RIB_IPV4_UNICAST = 2
RIB_IPV4_MULTICAST = 3
ATTR_EXTENDED_LENGTH = 0x10
ATTR_NEXT_HOP = 3


@dataclass(frozen=True)
class CollectorCandidate:
    project: str
    collector: str
    dump_interval_hours: int
    filename_prefix: str
    compression: str
    note: str
    available_from: date | None = None
    available_until: date | None = None


@dataclass(frozen=True)
class TraceProfile:
    monitor: str
    title: str
    notes: tuple[str, ...]
    candidates: tuple[CollectorCandidate, ...]


@dataclass(frozen=True)
class RulePlan:
    trace_path: Path
    trace_time_utc: datetime
    profile: TraceProfile
    candidate: CollectorCandidate
    rib_time_utc: datetime
    url: str
    rib_filename: str
    output_path: Path
    metadata_path: Path
    time_delta: timedelta


@dataclass(frozen=True)
class RuleEntry:
    prefix_ip: str
    prefix_len: int
    next_hop: str


TRACE_RE = re.compile(
    r"(?P<monitor>equinix-[^.]+)\.[^.]+\.?"
    r"(?P<date>\d{8})-(?P<time>\d{6})\.UTC",
    re.IGNORECASE,
)


TRACE_PROFILES: dict[str, TraceProfile] = {
    "equinix-sanjose": TraceProfile(
        monitor="equinix-sanjose",
        title="CAIDA Equinix San Jose anonymized trace",
        notes=(
            "CAIDA San Jose monitor: San Jose-Los Angeles Tier-1 backbone link.",
            "The monitor stopped in September 2014.",
            "Palo Alto / PAIX collectors are geographically close to San Jose.",
            "RouteViews route-views.isc is at PAIX Palo Alto and has 2-hour RIBs.",
            "RIPE RIS rrc14 is Palo Alto / PAIX and has 8-hour legacy bview dumps.",
        ),
        candidates=(
            CollectorCandidate(
                project="routeviews",
                collector="route-views.isc",
                dump_interval_hours=2,
                filename_prefix="rib",
                compression="bz2",
                note="PAIX Palo Alto RouteViews collector; closest 2-hour snapshot.",
            ),
            CollectorCandidate(
                project="routeviews",
                collector="route-views.paix",
                dump_interval_hours=2,
                filename_prefix="rib",
                compression="bz2",
                note="PAIX RouteViews collector, if present in the historical archive.",
            ),
            CollectorCandidate(
                project="ris",
                collector="rrc14",
                dump_interval_hours=8,
                filename_prefix="bview",
                compression="gz",
                note="RIPE RIS rrc14 at Palo Alto / PAIX; legacy dumps are every 8 hours.",
            ),
        ),
    ),
    "equinix-nyc": TraceProfile(
        monitor="equinix-nyc",
        title="CAIDA Equinix New York anonymized trace",
        notes=(
            "CAIDA New York monitor trace. Local anonymized traces may be stored under /home/yuzugon/pcap.",
            "RIPE RIS rrc11 is New York / NYIIX and is the selected collector for this trace.",
            "RIPE RIS legacy bview dumps are every 8 hours; for the 2019-01-17 13:59 UTC trace, 16:00 UTC is the nearest dump.",
            "The 08:00 UTC dump is kept as the preceding same-day RIB for comparison if needed.",
        ),
        candidates=(
            CollectorCandidate(
                project="ris",
                collector="rrc11",
                dump_interval_hours=8,
                filename_prefix="bview",
                compression="gz",
                note="RIPE RIS rrc11 at New York / NYIIX; nearest 8-hour bview for the NYC trace.",
            ),
        ),
    ),
    "jpix-sinet": TraceProfile(
        monitor="jpix-sinet",
        title="JPIX/SINET 90-second 5tuple trace",
        notes=(
            "Trace files are space-separated 8-field 5tuple text: time, src IP, src port, dst IP, dst port, protocol, TOS, length.",
            "The capture date is documented as 2018-05-02; filenames do not include a clock time.",
            "RIPE RIS rrc06 is located at Otemachi, JP and covers DIX-IE/JPIX, so it is the selected collector for this trace pair.",
            "Because only a date is available, the 2018-05-02 00:00 UTC bview dump is used by default.",
        ),
        candidates=(
            CollectorCandidate(
                project="ris",
                collector="rrc06",
                dump_interval_hours=8,
                filename_prefix="bview",
                compression="gz",
                note="RIPE RIS rrc06 at Otemachi, JP for DIX-IE/JPIX; selected for JPIX/SINET trace pair.",
            ),
        ),
    ),
    "equinix-chicago": TraceProfile(
        monitor="equinix-chicago",
        title="CAIDA Equinix Chicago anonymized trace",
        notes=(
            "CAIDA Chicago monitor: Chicago-Seattle Tier-1 backbone link.",
            "The monitor stopped at the end of March 2015.",
            "RouteViews route-views.chicago starts in June 2016, so it is not time-aligned with 2008-2015 CAIDA Chicago traces.",
        ),
        candidates=(
            CollectorCandidate(
                project="routeviews",
                collector="route-views.chicago",
                dump_interval_hours=2,
                filename_prefix="rib",
                compression="bz2",
                note="RouteViews Chicago collector; unavailable for the 2014 CAIDA Chicago trace.",
                available_from=date(2016, 6, 1),
            ),
        ),
    ),
}


TRACE_FILENAME_OVERRIDES: dict[str, tuple[str, datetime]] = {
    "jpix2sinet90s_5tuple.txt": ("jpix-sinet", datetime(2018, 5, 2, tzinfo=UTC)),
    "sinet2jpix90s_5tuple.txt": ("jpix-sinet", datetime(2018, 5, 2, tzinfo=UTC)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Choose a BGP collector for known CAIDA Equinix traces, download the "
            "nearest RIB dump, parse IPv4 prefixes, and write a simulator .rule file."
        )
    )
    parser.add_argument("traces", nargs="+", help="Trace path(s), e.g. /research/trace/equinix-sanjose...pcap")
    parser.add_argument("--outdir", default="rules", help="Directory for generated .rule files")
    parser.add_argument("--workdir", default="/tmp/bgp-ribs", help="Directory for downloaded RIB files")
    parser.add_argument(
        "--collector",
        help=(
            "Override collector as project:collector, e.g. routeviews:route-views.isc "
            "or ris:rrc14"
        ),
    )
    parser.add_argument(
        "--candidate-index",
        type=int,
        help="Use the Nth usable candidate after filtering by availability (0-based)",
    )
    parser.add_argument(
        "--rib-utc",
        help=(
            "Override RIB dump time in UTC, e.g. 2016-06-28T12:00. "
            "Use this when the nearest trace-time collector dump is unavailable."
        ),
    )
    parser.add_argument(
        "--allow-unavailable",
        action="store_true",
        help="Allow candidates outside their documented availability window",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print chosen candidate(s) and URLs without downloading or writing rules",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files")
    parser.add_argument("--keep-rib", action="store_true", help="Keep the downloaded compressed RIB")
    parser.add_argument(
        "--no-add-default",
        action="store_true",
        help="Do not prepend 0.0.0.0/0 if the RIB does not contain a default route",
    )
    parser.add_argument(
        "--parser",
        choices=("bgpdump", "mrt"),
        default="bgpdump",
        help="RIB parser to use. bgpdump matches the existing rule generation flow.",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Do not write a .meta.md file next to the generated rule",
    )
    parser.add_argument(
        "--max-prefixes",
        type=int,
        default=0,
        help="Stop after N unique prefixes; intended only for parser smoke tests",
    )
    return parser.parse_args()


def parse_trace_time(trace_path: Path) -> tuple[str, datetime]:
    override = TRACE_FILENAME_OVERRIDES.get(trace_path.name.lower())
    if override:
        return override

    match = TRACE_RE.search(trace_path.name)
    if not match:
        raise ValueError(f"unsupported trace filename: {trace_path.name}")

    monitor = match.group("monitor").lower()
    dt = datetime.strptime(
        f"{match.group('date')}{match.group('time')}",
        "%Y%m%d%H%M%S",
    ).replace(tzinfo=UTC)
    return monitor, dt


def parse_collector_override(raw: str) -> CollectorCandidate:
    if ":" not in raw:
        raise ValueError("--collector must be project:collector")
    project, collector = raw.split(":", 1)
    if project not in {"routeviews", "ris"}:
        raise ValueError("--collector project must be routeviews or ris")

    if project == "routeviews":
        return CollectorCandidate(
            project=project,
            collector=collector,
            dump_interval_hours=2,
            filename_prefix="rib",
            compression="bz2",
            note="Manual RouteViews override.",
        )

    return CollectorCandidate(
        project=project,
        collector=collector,
        dump_interval_hours=8,
        filename_prefix="bview",
        compression="gz",
        note="Manual RIPE RIS override.",
    )


def parse_rib_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    normalized = raw.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y%m%d.%H%M"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError("--rib-utc must be YYYY-MM-DDTHH:MM or YYYYMMDD.HHMM")


def nearest_dump_time(dt: datetime, interval_hours: int) -> datetime:
    midnight = datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    seconds = (dt - midnight).total_seconds()
    interval = interval_hours * 3600
    rounded = int((seconds + interval / 2) // interval) * interval
    return midnight + timedelta(seconds=rounded)


def is_available(candidate: CollectorCandidate, dt: datetime) -> bool:
    day = dt.date()
    if candidate.available_from and day < candidate.available_from:
        return False
    if candidate.available_until and day > candidate.available_until:
        return False
    return True


def build_url(candidate: CollectorCandidate, rib_time: datetime) -> tuple[str, str]:
    yyyymm = rib_time.strftime("%Y.%m")
    stamp = rib_time.strftime("%Y%m%d.%H%M")

    if candidate.project == "routeviews":
        filename = f"rib.{stamp}.bz2"
        url = (
            f"https://archive.routeviews.org/{candidate.collector}/bgpdata/"
            f"{yyyymm}/RIBS/{filename}"
        )
        return url, filename

    if candidate.project == "ris":
        filename = f"bview.{stamp}.gz"
        url = f"https://data.ris.ripe.net/{candidate.collector}/{yyyymm}/{filename}"
        return url, filename

    raise ValueError(f"unsupported project: {candidate.project}")


def output_name(candidate: CollectorCandidate, rib_time: datetime) -> str:
    stamp = rib_time.strftime("%Y%m%d.%H%M")
    safe_collector = candidate.collector.replace("/", "_")
    return f"{safe_collector}.{candidate.filename_prefix}.{stamp}.unique.rule"


def build_plans_for_trace(
    trace_path: Path,
    outdir: Path,
    collector_override: CollectorCandidate | None,
    allow_unavailable: bool,
    rib_time_override: datetime | None,
) -> tuple[list[RulePlan], list[str]]:
    monitor, trace_time = parse_trace_time(trace_path)
    profile = TRACE_PROFILES.get(monitor)
    if not profile:
        raise ValueError(f"no collector profile for monitor: {monitor}")

    candidates = (collector_override,) if collector_override else profile.candidates
    plans: list[RulePlan] = []
    skipped: list[str] = []

    for candidate in candidates:
        rib_time = rib_time_override or nearest_dump_time(trace_time, candidate.dump_interval_hours)
        availability_dt = rib_time if rib_time_override else trace_time

        if not allow_unavailable and not is_available(candidate, availability_dt):
            skipped.append(f"{candidate.project}:{candidate.collector} skipped: outside availability window")
            continue

        url, rib_filename = build_url(candidate, rib_time)
        out_path = outdir / output_name(candidate, rib_time)
        plans.append(
            RulePlan(
                trace_path=trace_path,
                trace_time_utc=trace_time,
                profile=profile,
                candidate=candidate,
                rib_time_utc=rib_time,
                url=url,
                rib_filename=rib_filename,
                output_path=out_path,
                metadata_path=out_path.with_suffix(out_path.suffix + ".meta.md"),
                time_delta=abs(rib_time - trace_time),
            )
        )

    return plans, skipped


def download_file(url: str, dst: Path) -> None:
    if dst.exists():
        print(f"[+] already downloaded: {dst}")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"[+] downloading: {url}")
    req = Request(url, headers={"User-Agent": "osada-ppc-simulator rule builder"})
    with urlopen(req, timeout=60) as resp:
        if getattr(resp, "status", 200) != 200:
            raise RuntimeError(f"download failed: HTTP {resp.status}")
        with tempfile.NamedTemporaryFile(dir=dst.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            shutil.copyfileobj(resp, tmp)
    tmp_path.replace(dst)


def open_compressed(path: Path) -> BinaryIO:
    if path.suffix == ".bz2":
        return bz2.open(path, "rb")
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def parse_next_hop(attrs: bytes) -> str | None:
    off = 0
    while off + 3 <= len(attrs):
        flags = attrs[off]
        code = attrs[off + 1]
        off += 2
        if flags & ATTR_EXTENDED_LENGTH:
            if off + 2 > len(attrs):
                return None
            attr_len = struct.unpack_from("!H", attrs, off)[0]
            off += 2
        else:
            attr_len = attrs[off]
            off += 1

        value = attrs[off : off + attr_len]
        off += attr_len

        if code == ATTR_NEXT_HOP and len(value) == 4:
            return str(ipaddress.IPv4Address(value))

    return None


def prefix_from_rib_body(body: bytes, off: int) -> tuple[str, int, int]:
    if off + 1 > len(body):
        raise ValueError("truncated RIB prefix length")

    prefix_len = body[off]
    off += 1
    byte_len = (prefix_len + 7) // 8
    prefix_bytes = body[off : off + byte_len]
    if len(prefix_bytes) != byte_len:
        raise ValueError("truncated RIB prefix bytes")
    off += byte_len

    raw = int.from_bytes(prefix_bytes.ljust(4, b"\x00"), "big")
    if prefix_len < 32:
        raw &= (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF
    return str(ipaddress.IPv4Address(raw)), prefix_len, off


def parse_rib_ipv4_body(body: bytes) -> tuple[str, int, list[str]]:
    off = 4
    prefix_ip, prefix_len, off = prefix_from_rib_body(body, off)
    if off + 2 > len(body):
        raise ValueError("truncated RIB entry count")
    entry_count = struct.unpack_from("!H", body, off)[0]
    off += 2

    next_hops: list[str] = []
    for _ in range(entry_count):
        if off + 8 > len(body):
            break
        off += 2  # peer index
        off += 4  # originated time
        attr_len = struct.unpack_from("!H", body, off)[0]
        off += 2
        attrs = body[off : off + attr_len]
        off += attr_len
        next_hop = parse_next_hop(attrs)
        if next_hop:
            next_hops.append(next_hop)

    return prefix_ip, prefix_len, next_hops


def iter_mrt_records(fp: BinaryIO):
    while True:
        header = fp.read(12)
        if not header:
            return
        if len(header) != 12:
            raise ValueError("truncated MRT header")
        _timestamp, mrt_type, subtype, length = struct.unpack("!IHHI", header)
        body = fp.read(length)
        if len(body) != length:
            raise ValueError("truncated MRT body")
        yield mrt_type, subtype, body


def stable_uuid_for_prefix(
    plan: RulePlan,
    prefix: str,
    prefix_len: int,
    next_hop: str = "",
    row_index: int = 0,
) -> str:
    key = (
        f"{plan.candidate.project}:{plan.candidate.collector}:"
        f"{plan.rib_time_utc.isoformat()}:{row_index}:{prefix}/{prefix_len}:{next_hop}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def extract_ipv4_rules(
    rib_path: Path,
    plan: RulePlan,
    add_default: bool,
    max_prefixes: int,
) -> list[RuleEntry]:
    rules: OrderedDict[tuple[str, int], str] = OrderedDict()
    if add_default:
        rules[("0.0.0.0", 0)] = stable_uuid_for_prefix(plan, "0.0.0.0", 0)

    records = 0
    ipv4_records = 0
    with open_compressed(rib_path) as fp:
        for mrt_type, subtype, body in iter_mrt_records(fp):
            records += 1
            if mrt_type != TABLE_DUMP_V2 or subtype not in {RIB_IPV4_UNICAST, RIB_IPV4_MULTICAST}:
                continue
            ipv4_records += 1
            try:
                prefix_ip, prefix_len, next_hops = parse_rib_ipv4_body(body)
            except ValueError:
                continue

            key = (prefix_ip, prefix_len)
            if key in rules:
                continue

            rules[key] = next_hops[0] if next_hops else stable_uuid_for_prefix(plan, prefix_ip, prefix_len)
            if max_prefixes and len(rules) >= max_prefixes:
                break

    print(f"[+] MRT records read : {records}")
    print(f"[+] IPv4 RIB records: {ipv4_records}")
    print(f"[+] unique rules    : {len(rules)}")
    return [
        RuleEntry(prefix_ip=prefix_ip, prefix_len=prefix_len, next_hop=next_hop)
        for (prefix_ip, prefix_len), next_hop in rules.items()
    ]


def parse_bgpdump_prefix(raw_prefix: str) -> tuple[str, int] | None:
    if not raw_prefix or ":" in raw_prefix:
        return None
    try:
        network = ipaddress.ip_network(raw_prefix, strict=False)
    except ValueError:
        return None
    if network.version != 4:
        return None
    return str(network.network_address), network.prefixlen


def extract_ipv4_rules_with_bgpdump(
    rib_path: Path,
    add_default: bool,
    max_prefixes: int,
) -> list[RuleEntry]:
    bgpdump = shutil.which("bgpdump")
    if not bgpdump:
        raise RuntimeError("bgpdump not found; rerun with --parser mrt or install bgpdump")

    print(f"[+] running: {bgpdump} -m {rib_path}")
    proc = subprocess.Popen(
        [bgpdump, "-m", str(rib_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    entries: list[RuleEntry] = []
    saw_default = False
    line_count = 0

    for line in proc.stdout:
        line_count += 1
        parts = line.rstrip("\n").split("|")
        if len(parts) < 9:
            continue

        parsed = parse_bgpdump_prefix(parts[5])
        if not parsed:
            continue

        prefix_ip, prefix_len = parsed
        next_hop = parts[8].strip()
        if not next_hop or ":" in next_hop:
            continue

        if prefix_ip == "0.0.0.0" and prefix_len == 0:
            saw_default = True

        entries.append(RuleEntry(prefix_ip=prefix_ip, prefix_len=prefix_len, next_hop=next_hop))
        if max_prefixes and len(entries) >= max_prefixes:
            break

    stderr = proc.stderr.read()
    ret = proc.wait()
    if ret != 0:
        raise RuntimeError(f"bgpdump failed (exit={ret})\n{stderr}")

    if add_default and not saw_default:
        entries.insert(0, RuleEntry(prefix_ip="0.0.0.0", prefix_len=0, next_hop="0.0.0.0"))

    print(f"[+] bgpdump lines read: {line_count}")
    print(f"[+] IPv4 rule rows   : {len(entries)}")
    return entries


def write_rule_files(path: Path, rules: list[RuleEntry], plan: RulePlan, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"output exists; use --force to overwrite: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        for entry in rules:
            tmp.write(f"{entry.prefix_ip} {entry.prefix_len} {entry.next_hop}\n")
    tmp_path.replace(path)
    print(f"[+] wrote rule: {path}")

    unique_path = path.with_name(path.name.removesuffix(".rule") + ".unique.rule")
    if unique_path.exists() and not force:
        raise FileExistsError(f"output exists; use --force to overwrite: {unique_path}")

    with tempfile.NamedTemporaryFile("w", dir=unique_path.parent, encoding="utf-8", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        for idx, entry in enumerate(rules):
            next_hop = stable_uuid_for_prefix(
                plan=plan,
                prefix=entry.prefix_ip,
                prefix_len=entry.prefix_len,
                next_hop=entry.next_hop,
                row_index=idx,
            )
            tmp.write(f"{entry.prefix_ip} {entry.prefix_len} {next_hop}\n")
    tmp_path.replace(unique_path)
    print(f"[+] wrote unique rule: {unique_path}")


def write_metadata(path: Path, plan: RulePlan, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"metadata exists; use --force to overwrite: {path}")

    text = [
        f"# {plan.output_path.name}",
        "",
        f"- trace: `{plan.trace_path}`",
        f"- trace timestamp UTC: `{plan.trace_time_utc:%Y-%m-%d %H:%M:%S}`",
        f"- monitor: `{plan.profile.monitor}`",
        f"- collector: `{plan.candidate.project}:{plan.candidate.collector}`",
        f"- RIB timestamp UTC: `{plan.rib_time_utc:%Y-%m-%d %H:%M}`",
        f"- absolute trace/RIB delta: `{plan.time_delta}`",
        f"- RIB URL: `{plan.url}`",
        f"- selection note: {plan.candidate.note}",
        "",
        "## Trace Notes",
        "",
    ]
    text.extend(f"- {note}" for note in plan.profile.notes)
    text.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write("\n".join(text))
    tmp_path.replace(path)
    print(f"[+] wrote metadata: {path}")


def print_plan(plans: list[RulePlan], skipped: list[str]) -> None:
    for skipped_item in skipped:
        print(f"[-] {skipped_item}")

    for idx, plan in enumerate(plans):
        print(
            f"[{idx}] trace={plan.trace_path.name} "
            f"collector={plan.candidate.project}:{plan.candidate.collector} "
            f"trace_utc={plan.trace_time_utc:%Y-%m-%d %H:%M:%S} "
            f"rib_utc={plan.rib_time_utc:%Y-%m-%d %H:%M} "
            f"delta={plan.time_delta} "
            f"out={plan.output_path}"
        )
        print(f"    url={plan.url}")


def run_plan(plan: RulePlan, args: argparse.Namespace) -> None:
    rib_path = Path(args.workdir) / plan.rib_filename
    download_file(plan.url, rib_path)
    if args.parser == "bgpdump":
        rules = extract_ipv4_rules_with_bgpdump(
            rib_path=rib_path,
            add_default=not args.no_add_default,
            max_prefixes=args.max_prefixes,
        )
    else:
        rules = extract_ipv4_rules(
            rib_path=rib_path,
            plan=plan,
            add_default=not args.no_add_default,
            max_prefixes=args.max_prefixes,
        )
    if len(rules) <= (0 if args.no_add_default else 1):
        raise RuntimeError(f"no IPv4 prefixes parsed from {rib_path}")

    raw_output_path = plan.output_path.with_name(plan.output_path.name.removesuffix(".unique.rule") + ".rule")
    write_rule_files(raw_output_path, rules, plan, args.force)
    if not args.no_metadata:
        write_metadata(plan.metadata_path, plan, args.force)
    if not args.keep_rib:
        rib_path.unlink(missing_ok=True)
        print(f"[+] removed downloaded RIB: {rib_path}")


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir)
    collector_override = parse_collector_override(args.collector) if args.collector else None
    rib_time_override = parse_rib_utc(args.rib_utc)

    all_plans: list[RulePlan] = []
    all_skipped: list[str] = []
    for trace in args.traces:
        plans, skipped = build_plans_for_trace(
            trace_path=Path(trace),
            outdir=outdir,
            collector_override=collector_override,
            allow_unavailable=args.allow_unavailable,
            rib_time_override=rib_time_override,
        )
        all_plans.extend(plans)
        all_skipped.extend(skipped)

    if args.candidate_index is not None:
        if args.candidate_index < 0 or args.candidate_index >= len(all_plans):
            raise IndexError(f"--candidate-index out of range: {args.candidate_index}")
        all_plans = [all_plans[args.candidate_index]]

    print_plan(all_plans, all_skipped)
    if args.plan_only:
        return 0
    if not all_plans:
        raise RuntimeError("no usable collector candidate; rerun with --collector or --allow-unavailable if intentional")

    failures: list[str] = []
    for plan in all_plans:
        try:
            run_plan(plan, args)
            return 0
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            failures.append(f"{plan.candidate.project}:{plan.candidate.collector}: {exc}")
            print(f"[!] failed candidate {plan.candidate.project}:{plan.candidate.collector}: {exc}", file=sys.stderr)

    raise RuntimeError("all candidates failed:\n" + "\n".join(failures))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[!] interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"[!] {exc}", file=sys.stderr)
        raise SystemExit(1)
