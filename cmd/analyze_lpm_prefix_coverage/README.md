# LPM prefix coverage analysis

This command counts the distinct routing-table entries actually selected by
longest-prefix matching at each `/0` through `/32` level. It also retains the
packet-weighted LPM distribution so the two views can be compared.

```bash
go run ./cmd/analyze_lpm_prefix_coverage \
  --rulefile /path/to/rib.unique.rule \
  --trace /path/to/trace.pcap \
  --label original-anon \
  --max 6338755 \
  --checkpoints 100000,300000,1000000,3000000,6338755 \
  --output-dir scripts/reports/lpm-prefix-coverage/example
```

Outputs:

- `lpm_prefix_coverage.csv`: packet share, distinct-prefix share, RIB prefix
  inventory, and RIB coverage for every level and checkpoint.
- `lpm_prefix_entries.csv`: ranked selected prefixes and packet counts. The
  default is the top 100 entries per level; pass `--entry-limit 0` for all.
- `SUMMARY.md`: input and filtering metadata.

For a target/original/XOR/greedy comparison, use
`scripts/run_lpm_prefix_coverage_comparison.sh`. Give the transformed side's RIB
and the target side's RIB separately. The runner enforces one common packet
limit and writes three graphs plus `prefix_coverage_comparison.csv`.
