#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

rulefile="/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule"
input_trace="/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap"
target_root="scripts/reports/anon_tree_lpm_remap/order-experiment-c61440"
seed_root="scripts/reports/anon_tree_lpm_remap/nyc-to-wide-targets-c61440"
output_root="${OUTPUT_ROOT:-scripts/reports/anon_tree_lpm_remap/nyc-to-wide-exact-seeded-k30-r10}"
trace_root="${TRACE_ROOT:-/home/yuzugon/pcap/derived/anon-tree-lpm-remap/nyc-to-wide-exact-seeded-k30-r10}"
binary="/tmp/fit_trace_tree_lpm_exact_seeded"

dates=(2025-09-27 2025-12-27 2026-03-27)
orders=(mass top-down bottom-up)

mkdir -p "$output_root" "$trace_root"
/home/yuzugon/go/bin/go build -o "$binary" ./cmd/fit_trace_tree_lpm

pids=()
for index in "${!dates[@]}"; do
  date_value="${dates[$index]}"
  order="${orders[$index]}"
  target_distribution="$target_root/$date_value/mass/lpm_distribution_comparison.csv"
  initial_mapping="$seed_root/$date_value/$order/best_mapping.gob.gz"
  output_dir="$output_root/$date_value/exact-seeded"
  output_trace="$trace_root/$date_value-exact-seeded-k30-r10-10000000.txt"
  mkdir -p "$output_dir"
  "$binary" \
    --rulefile "$rulefile" \
    --target-distribution "$target_distribution" \
    --input-trace "$input_trace" \
    --initial-mapping "$initial_mapping" \
    --max 10000000 \
    --sample-size 200000 \
    --fit-depth 24 \
    --hill-candidates 61440 \
    --hill-passes 2 \
    --candidate-order "$order" \
    --all-active-candidates \
    --exact-block-candidates 30 \
    --exact-rounds 10 \
    --output-trace "$output_trace" \
    --output-dir "$output_dir" &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    failed=1
  fi
done
exit "$failed"
