#!/usr/bin/env bash
# Run only through researchctl. Reuses recorded packet inputs, no DB mutation.
set -euo pipefail
input=$(realpath "$1")
out=$2
mkdir -p "$out"/{csv,logs,bin,private}
out=$(realpath "$out")
go build -o "$out/bin/fib_region_index" ./cmd/index_probe_explore
while IFS=$'\t' read -r label trace rule; do
  [[ -z $label || $label == \#* ]] && continue
  slug=$(printf '%s' "$label" | tr -c 'A-Za-z0-9.-' '_')
  "$out/bin/fib_region_index" -fib-region -region-bits 8,12,16 \
    -dstleaf "$input/private/$slug.dstleaf" -rulefile "$rule" -label "$label" \
    -region-out "$out/private/$slug" -capacities 1024,8192,65536 -jobs 4 \
    -out "$out/csv/$slug.csv" > "$out/logs/$slug.log" 2>&1
  echo "done $label"
done < scripts/experiments/final_entry_sweep_traces.tsv
