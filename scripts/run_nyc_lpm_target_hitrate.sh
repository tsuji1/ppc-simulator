#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

rulefile="${RULEFILE:-/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule}"
input_trace="${INPUT_TRACE:-/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap}"
trace_root="${TRACE_ROOT:-/home/yuzugon/pcap/derived/anon-tree-lpm-remap/nyc-to-wide-targets-c61440}"
output_dir="${OUTPUT_DIR:-scripts/reports/anon_tree_lpm_remap/nyc-to-wide-targets-c61440/hitrate}"
binary="${BINARY:-/tmp/windowed_hitrate_nyc_lpm}"

mkdir -p "$output_dir"

labels=(
  original-nyc
  target-2025-09-27
  target-2025-12-27
  target-2026-03-27
)
traces=(
  "$input_trace"
  "$trace_root/2025-09-27-mass-10000000.txt"
  "$trace_root/2025-12-27-top-down-10000000.txt"
  "$trace_root/2026-03-27-bottom-up-10000000.txt"
)

pids=()
for index in "${!labels[@]}"; do
  "$binary" \
    -rulefile "$rulefile" \
    -trace "${traces[$index]}" \
    -output-dir "$output_dir" \
    -output-csv "$output_dir/${labels[$index]}.csv" \
    -max 10000000 \
    -windows 1000000 \
    -way 8 \
    -mp-refbits 24,20 \
    -mp-capacities 2048,2048 \
    -ps-index-types 5,2 \
    -ps-capacity 2048 \
    -window-mode warm &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    failed=1
  fi
done
exit "$failed"
