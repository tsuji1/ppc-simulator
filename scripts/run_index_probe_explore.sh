#!/usr/bin/env bash
# Read-only source inputs, isolated output, no DB writes. Use via researchctl.
set -euo pipefail
list=$(realpath "$1")
out=$2
jobs=${3:-4}
mkdir -p "$out"/{csv,private,logs,bin}
out=$(realpath "$out")
go build -o "$out/bin/index_probe_explore" ./cmd/index_probe_explore
while IFS=$'\t' read -r label trace rule; do
  [[ -z $label || $label == \#* ]] && continue
  slug=$(printf '%s' "$label" | tr -c 'A-Za-z0-9.-' '_')
  "$out/bin/index_probe_explore" -trace "$trace" -rulefile "$rule" -label "$label" \
    -max "${PACKETS:-10000000}" -capacities "${CAPACITIES:-1024,8192,65536}" -jobs "$jobs" \
    -export "$out/private/$slug.dstleaf" -out "$out/csv/$slug.csv" \
    > "$out/logs/$slug.log" 2>&1
  echo "done $label"
done < "$list"
