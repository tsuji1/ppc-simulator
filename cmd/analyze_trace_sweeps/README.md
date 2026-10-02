# Non-anonymous trace sweep candidates

The command ranks source IPs by the number of distinct destination IPs they
contact in TCP/UDP IPv4 packets. This is a high-fanout/sweep candidate metric,
not a claim that the traffic is a port scanner. The report also counts
numerically adjacent destinations in the source's packet order.

```bash
go run ./cmd/analyze_trace_sweeps \
  --trace /home/yuzugon/pcap/non-anon/2025-09-27.pcap \
  --top 20 \
  --output-dir scripts/reports/trace-sweeps/2025-09-27
```

`destinations_*.csv` contains the complete destination IP list for each ranked
source. Use `unique_dst16` and `unique_dst24` to see whether the fan-out is
spread across many `/16` or `/24` regions.

The command also embeds a small, reviewed attribution table in
`known_hosts.csv`. `known_research_hosts.csv` reports whether each listed host
was observed as a source, its fan-out, and its five most active source
protocol/port combinations. The same attribution is appended to
`sweep_sources.csv` when a known host enters the top-N ranking.

Attribution is deliberately separate from detection: an organization, ASN, or
reverse-DNS match does not prove that traffic is benign, and high fan-out does
not by itself prove scanning. In particular, public mirror servers naturally
communicate with many clients. Use the source-port evidence and packet context
before assigning a verdict.
