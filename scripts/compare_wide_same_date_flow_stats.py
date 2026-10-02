#!/usr/bin/env python3
"""Compare WIDE anonymized and non-anonymized flow statistics by date."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLOW_ROOT = ROOT / "reports" / "flow_stats_wide_same_date"
NO_ICMP = ROOT / "reports" / "flow_stats_wide_same_date_no_icmp" / "flow_trace_summary_no_icmp.csv"
THREE = ROOT / "reports" / "flow_stats_wide_same_date_3tuple" / "flow_trace_summary_3tuple.csv"
OUT = ROOT / "reports" / "flow_stats_wide_same_date_compare"

DATES = ["2025-09-27", "2025-12-27", "2026-03-27"]


def read_metric_csv(path: Path) -> dict[str, str]:
    with path.open(newline="") as f:
        return {row["metric"]: row["value"] for row in csv.DictReader(f)}


def read_summary_csv(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(newline="") as f:
        return {(row["trace"], row.get("mode", "")): row for row in csv.DictReader(f)}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def packet_bin_tail(path: Path, lower_bound: int) -> float:
    rows = read_rows(path)
    packet_key = "packets" if "packets" in rows[0] else "packet_sum"
    lower_key = "lower" if "lower" in rows[0] else "packet_count_lower"
    total_packets = sum(int(row[packet_key]) for row in rows)
    tail_packets = sum(int(row[packet_key]) for row in rows if int(row[lower_key]) >= lower_bound)
    return tail_packets / total_packets if total_packets else 0.0


def cutoff(path: Path, threshold: float) -> str:
    rows = read_rows(path)
    if rows and "cumulative_flow_ratio" not in rows[0]:
        flow_key = "flow_count"
        lower_key = "packet_count_lower"
        upper_key = "packet_count_upper"
        total_flows = sum(int(row[flow_key]) for row in rows)
        cumulative = 0
        for row in rows:
            cumulative += int(row[flow_key])
            if ratio(cumulative, total_flows) >= threshold:
                lower = int(row[lower_key])
                upper = int(row[upper_key])
                return f"{lower:,}" if lower == upper else f"{lower:,}-{upper:,}"
        return ""
    for row in rows:
        if float(row["cumulative_flow_ratio"]) >= threshold:
            return row["bin"]
    return ""


def pfloat(row: dict[str, str], key: str) -> float:
    return float(row[key])


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def pct(value: float, digits: int = 2) -> str:
    return f"{value * 100:.{digits}f}%"


def delta_pct(anon: float, nonanon: float) -> float:
    return ratio(anon - nonanon, nonanon)


def base_metric(date: str, kind: str) -> dict[str, object]:
    trace = f"{date}-{kind}"
    directory = FLOW_ROOT / trace
    summary = read_metric_csv(directory / "flow_summary.csv")
    ipv4 = int(summary["ipv4_packets"])
    flows = int(summary["unique_flow_count"])
    return {
        "trace": trace,
        "ipv4_packets": ipv4,
        "flows": flows,
        "flow_density": flows * 1_000_000 / ipv4,
        "one_packet_flow_ratio": float(summary["one_packet_flow_ratio"]),
        "top100_packet_share": float(summary["top100_flow_packet_share"]),
        "p99_packets_per_flow": float(summary["p99_packets_per_flow"]),
        "ge8192_packet_share": packet_bin_tail(directory / "flow_length_bins.csv", 8192),
        "cutoff99": cutoff(directory / "flow_length_bins.csv", 0.99),
        "top_flow": read_rows(directory / "top_flows.csv")[0],
    }


def load_no_icmp() -> dict[str, dict[str, str]]:
    with NO_ICMP.open(newline="") as f:
        return {row["trace"]: row for row in csv.DictReader(f)}


def load_three_no_icmp() -> dict[str, dict[str, str]]:
    with THREE.open(newline="") as f:
        return {
            row["trace"]: row
            for row in csv.DictReader(f)
            if row["mode"] == "3tuple_no_icmp"
        }


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize_pair(date: str) -> dict[str, object]:
    non = base_metric(date, "nonanon")
    anon = base_metric(date, "anon")
    return {
        "date": date,
        "nonanon_ipv4_packets": non["ipv4_packets"],
        "anon_ipv4_packets": anon["ipv4_packets"],
        "ipv4_delta_ratio": delta_pct(anon["ipv4_packets"], non["ipv4_packets"]),
        "nonanon_flows": non["flows"],
        "anon_flows": anon["flows"],
        "flow_delta_ratio": delta_pct(anon["flows"], non["flows"]),
        "nonanon_flow_density": non["flow_density"],
        "anon_flow_density": anon["flow_density"],
        "density_delta_ratio": delta_pct(anon["flow_density"], non["flow_density"]),
        "nonanon_one_packet_flow_ratio": non["one_packet_flow_ratio"],
        "anon_one_packet_flow_ratio": anon["one_packet_flow_ratio"],
        "nonanon_top100_packet_share": non["top100_packet_share"],
        "anon_top100_packet_share": anon["top100_packet_share"],
        "nonanon_ge8192_packet_share": non["ge8192_packet_share"],
        "anon_ge8192_packet_share": anon["ge8192_packet_share"],
        "nonanon_cutoff99": non["cutoff99"],
        "anon_cutoff99": anon["cutoff99"],
    }


def summarize_no_icmp(date: str, rows: dict[str, dict[str, str]]) -> dict[str, object]:
    non = rows[f"{date}-nonanon"]
    anon = rows[f"{date}-anon"]
    return {
        "date": date,
        "nonanon_included_packets": int(non["included_packets"]),
        "anon_included_packets": int(anon["included_packets"]),
        "packet_delta_ratio": delta_pct(float(anon["included_packets"]), float(non["included_packets"])),
        "nonanon_flows": int(non["included_flow_count"]),
        "anon_flows": int(anon["included_flow_count"]),
        "flow_delta_ratio": delta_pct(float(anon["included_flow_count"]), float(non["included_flow_count"])),
        "nonanon_flow_density": pfloat(non, "flows_per_million_included_packets"),
        "anon_flow_density": pfloat(anon, "flows_per_million_included_packets"),
        "density_delta_ratio": delta_pct(
            pfloat(anon, "flows_per_million_included_packets"),
            pfloat(non, "flows_per_million_included_packets"),
        ),
        "nonanon_icmp_packet_share": pfloat(non, "excluded_icmp_packet_ratio_of_source_ipv4"),
        "anon_icmp_packet_share": pfloat(anon, "excluded_icmp_packet_ratio_of_source_ipv4"),
        "nonanon_icmp_flow_share": pfloat(non, "excluded_icmp_flow_ratio_of_source_flows"),
        "anon_icmp_flow_share": pfloat(anon, "excluded_icmp_flow_ratio_of_source_flows"),
        "nonanon_ge8192_packet_share": pfloat(non, "ge8192_packet_share"),
        "anon_ge8192_packet_share": pfloat(anon, "ge8192_packet_share"),
        "nonanon_cutoff99": non["cutoff99_flow_count_bin"],
        "anon_cutoff99": anon["cutoff99_flow_count_bin"],
    }


def summarize_three(date: str, rows: dict[str, dict[str, str]]) -> dict[str, object]:
    non = rows[f"{date}-nonanon"]
    anon = rows[f"{date}-anon"]
    return {
        "date": date,
        "nonanon_flows": int(non["flow_count"]),
        "anon_flows": int(anon["flow_count"]),
        "flow_delta_ratio": delta_pct(float(anon["flow_count"]), float(non["flow_count"])),
        "nonanon_flow_density": pfloat(non, "flows_per_million_packets"),
        "anon_flow_density": pfloat(anon, "flows_per_million_packets"),
        "density_delta_ratio": delta_pct(
            pfloat(anon, "flows_per_million_packets"),
            pfloat(non, "flows_per_million_packets"),
        ),
        "nonanon_packets_per_flow": pfloat(non, "packets_per_flow"),
        "anon_packets_per_flow": pfloat(anon, "packets_per_flow"),
        "nonanon_ge8192_packet_share": pfloat(non, "ge8192_packet_share"),
        "anon_ge8192_packet_share": pfloat(anon, "ge8192_packet_share"),
        "nonanon_cutoff99": non["cutoff99_flow_count_bin"],
        "anon_cutoff99": anon["cutoff99_flow_count_bin"],
    }


def write_markdown(
    base_rows: list[dict[str, object]],
    no_icmp_rows: list[dict[str, object]],
    three_rows: list[dict[str, object]],
) -> None:
    path = OUT / "wide_same_date_flow_analysis.md"
    lines = [
        "# WIDE same-date anonymized vs non-anonymized flow analysis",
        "",
        "同じ日付の WIDE 非匿名 trace と WIDE 匿名 trace を、先頭 10,000,000 packets で比較した。",
        "フロー定義は向きあり IPv4 5要素を基本とし、ICMP 除外版と 3要素版も併記する。",
        "",
        "## Summary",
        "",
        "- 匿名版と非匿名版のフロー分布はほぼ一致する。",
        "- 2025-09-27 は匿名版の IPv4 packets / flows が約 0.25-0.40% 少ないが、分布形状はほぼ同じ。",
        "- 2025-12-27 と 2026-03-27 は、匿名版と非匿名版の差が 0.01% 未満で、実質同じ分布。",
        "- したがって WIDE については、匿名化そのものがフロー密度・短命フロー比率・巨大フロー占有率を大きく変えているとは言いにくい。",
        "",
        "## 5-tuple, ICMP included",
        "",
        "| date | nonanon flows | anon flows | flow delta | nonanon density | anon density | density delta | one-pkt ratio non/anon | top100 share non/anon | 8192+ share non/anon | 99% cutoff non/anon |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in base_rows:
        lines.append(
            "| {date} | {nf:,} | {af:,} | {fd} | {nd:,.0f} | {ad:,.0f} | {dd} | {n1} / {a1} | {nt} / {at} | {ng} / {ag} | {nc} / {ac} |".format(
                date=row["date"],
                nf=int(row["nonanon_flows"]),
                af=int(row["anon_flows"]),
                fd=pct(float(row["flow_delta_ratio"])),
                nd=float(row["nonanon_flow_density"]),
                ad=float(row["anon_flow_density"]),
                dd=pct(float(row["density_delta_ratio"])),
                n1=pct(float(row["nonanon_one_packet_flow_ratio"])),
                a1=pct(float(row["anon_one_packet_flow_ratio"])),
                nt=pct(float(row["nonanon_top100_packet_share"])),
                at=pct(float(row["anon_top100_packet_share"])),
                ng=pct(float(row["nonanon_ge8192_packet_share"])),
                ag=pct(float(row["anon_ge8192_packet_share"])),
                nc=row["nonanon_cutoff99"],
                ac=row["anon_cutoff99"],
            )
        )

    lines += [
        "",
        "## 5-tuple, excluding ICMP",
        "",
        "| date | nonanon flows | anon flows | flow delta | nonanon density | anon density | density delta | ICMP pkt share non/anon | ICMP flow share non/anon | 8192+ share non/anon | 99% cutoff non/anon |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in no_icmp_rows:
        lines.append(
            "| {date} | {nf:,} | {af:,} | {fd} | {nd:,.0f} | {ad:,.0f} | {dd} | {nip} / {aip} | {nif} / {aif} | {ng} / {ag} | {nc} / {ac} |".format(
                date=row["date"],
                nf=int(row["nonanon_flows"]),
                af=int(row["anon_flows"]),
                fd=pct(float(row["flow_delta_ratio"])),
                nd=float(row["nonanon_flow_density"]),
                ad=float(row["anon_flow_density"]),
                dd=pct(float(row["density_delta_ratio"])),
                nip=pct(float(row["nonanon_icmp_packet_share"])),
                aip=pct(float(row["anon_icmp_packet_share"])),
                nif=pct(float(row["nonanon_icmp_flow_share"])),
                aif=pct(float(row["anon_icmp_flow_share"])),
                ng=pct(float(row["nonanon_ge8192_packet_share"])),
                ag=pct(float(row["anon_ge8192_packet_share"])),
                nc=row["nonanon_cutoff99"],
                ac=row["anon_cutoff99"],
            )
        )

    lines += [
        "",
        "## 3-tuple, excluding ICMP",
        "",
        "| date | nonanon flows | anon flows | flow delta | nonanon density | anon density | density delta | pkts/flow non/anon | 8192+ share non/anon | 99% cutoff non/anon |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in three_rows:
        lines.append(
            "| {date} | {nf:,} | {af:,} | {fd} | {nd:,.0f} | {ad:,.0f} | {dd} | {np:.2f} / {ap:.2f} | {ng} / {ag} | {nc} / {ac} |".format(
                date=row["date"],
                nf=int(row["nonanon_flows"]),
                af=int(row["anon_flows"]),
                fd=pct(float(row["flow_delta_ratio"])),
                nd=float(row["nonanon_flow_density"]),
                ad=float(row["anon_flow_density"]),
                dd=pct(float(row["density_delta_ratio"])),
                np=float(row["nonanon_packets_per_flow"]),
                ap=float(row["anon_packets_per_flow"]),
                ng=pct(float(row["nonanon_ge8192_packet_share"])),
                ag=pct(float(row["anon_ge8192_packet_share"])),
                nc=row["nonanon_cutoff99"],
                ac=row["anon_cutoff99"],
            )
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "- WIDE の匿名 trace は、少なくとも flow count / flow length の観点では非匿名 trace とほぼ同じ性質を保っている。",
        "- 匿名化は IP address を置き換えるが、protocol と port を保ち、IP mapping がほぼ一対一なら 5-tuple の個数や packets/flow は大きく変わらない。",
        "- 2025-09-27 のみ、匿名版の IPv4 packet count が非匿名版より約 0.40% 少ない。これは匿名化の効果というより、入力ファイルの前処理・packet set の差と見るのが自然。",
        "- ICMP 除外後も、匿名/非匿名の差は同じく小さい。ICMP が WIDE の flow density を押し上げるという前回の結論は匿名版でも成立する。",
        "- 3要素版でも差は小さい。IP ペア単位で見ても匿名版と非匿名版の flow shape はほぼ一致する。",
        "- したがって、WIDE と Equinix/CAIDA の差を議論するときに「匿名だから違う」とは言いにくい。WIDE 匿名と WIDE 非匿名はほぼ同じで、Equinix との差は trace の観測地点・時刻・traffic mix の違いとして扱う方が妥当。",
        "",
        "## Files",
        "",
        "- `wide_same_date_5tuple_compare.csv`",
        "- `wide_same_date_no_icmp_compare.csv`",
        "- `wide_same_date_3tuple_no_icmp_compare.csv`",
        "- source: `scripts/reports/flow_stats_wide_same_date/`",
        "- source: `scripts/reports/flow_stats_wide_same_date_no_icmp/`",
        "- source: `scripts/reports/flow_stats_wide_same_date_3tuple/`",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base_rows = [summarize_pair(date) for date in DATES]
    no_icmp = load_no_icmp()
    no_icmp_rows = [summarize_no_icmp(date, no_icmp) for date in DATES]
    three = load_three_no_icmp()
    three_rows = [summarize_three(date, three) for date in DATES]

    write_csv(OUT / "wide_same_date_5tuple_compare.csv", base_rows, list(base_rows[0].keys()))
    write_csv(OUT / "wide_same_date_no_icmp_compare.csv", no_icmp_rows, list(no_icmp_rows[0].keys()))
    write_csv(OUT / "wide_same_date_3tuple_no_icmp_compare.csv", three_rows, list(three_rows[0].keys()))
    write_markdown(base_rows, no_icmp_rows, three_rows)


if __name__ == "__main__":
    main()
