#!/usr/bin/env bash
set -euo pipefail

root=/home/yuzugon
sim="$root/osada-ppc-simulator"
tool="$sim/bin/fit_trace_tree_lpm"
max_packets=${MAX_PACKETS:-1000000}
sample_size=${SAMPLE_SIZE:-100000}
hill_candidates=${HILL_CANDIDATES:-4000}
hill_passes=${HILL_PASSES:-2}
output_root=${OUTPUT_ROOT:-$sim/scripts/reports/subtree-hit-fit/wide-2025-09-to-2025-09-27-pilot}

mkdir -p "$output_root" "$sim/bin"
go build -o "$tool" "$sim/cmd/fit_trace_tree_lpm"

for epsilon in 0 0.005 0.01 0.02; do
  label=${epsilon//./p}
  output_dir="$output_root/epsilon-$label"
  mkdir -p "$output_dir"
  "$tool" \
    --rulefile "$root/rules/rib.20250927.0600.unique.rule" \
    --target-trace "$root/pcap/non-anon/2025-09-27.pcap" \
    --input-trace "$root/pcap/202509271400.pcap" \
    --max "$max_packets" \
    --fit-depth 24 \
    --sample-size "$sample_size" \
    --hill-candidates "$hill_candidates" \
    --hill-passes "$hill_passes" \
    --candidate-order mass \
    --subtree-hit-fit \
    --lpm-epsilon "$epsilon" \
    --output-dir "$output_dir" \
    --output-trace "$output_dir/transformed.txt"
done

MPLCONFIGDIR=/tmp/matplotlib UV_CACHE_DIR=/tmp/uv-cache \
  uv run --script "$sim/scripts/summarize_subtree_hit_epsilon_sweep.py" \
  --input-root "$output_root" \
  --output-dir "$output_root"
