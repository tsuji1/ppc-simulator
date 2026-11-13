#!/usr/bin/env bash
set -euo pipefail
input=$(realpath "$1")
out=$2
mkdir -p "$out"/{csv,logs,bin}
out=$(realpath "$out")
go build -o "$out/bin/staged_probes" ./cmd/index_probe_explore
while IFS=$'\t' read -r label trace rule; do
  [[ -z $label || $label == \#* ]] && continue
  slug=$(printf '%s' "$label" | tr -c 'A-Za-z0-9.-' '_')
  "$out/bin/staged_probes" -dstleaf "$input/private/$slug.dstleaf" -label "$label" \
    -floor-only -staged -capacities 1024,8192,65536 -jobs 4 \
    -out "$out/csv/$slug.csv" > "$out/logs/$slug.log" 2>&1
  echo "done $label"
done < scripts/experiments/final_entry_sweep_traces.tsv
