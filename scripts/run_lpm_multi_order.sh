#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run_lpm_multi_order.sh \
    --date YYYY-MM-DD \
    --rulefile PATH \
    (--target-trace PATH | --target-distribution CSV) \
    --input-trace PATH \
    [--output-root PATH] \
    [--trace-root PATH] \
    [--max PACKETS] \
    [--sample-size PACKETS] \
    [--candidate-budget N] \
    [--hill-passes N] \
    [--all-active-candidates] \
    [--exact-block-candidates N] \
    [--exact-rounds N] \
    [--initial-mapping PATH]

Runs mass, top-down, and bottom-up LPM tree-rotation searches in parallel.
EOF
}

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
date_value=""
rulefile=""
target_trace=""
target_distribution=""
input_trace=""
output_root="$root_dir/scripts/reports/anon_tree_lpm_remap/order-experiment-c61440"
trace_root="/home/yuzugon/pcap/derived/anon-tree-lpm-remap/order-experiment-c61440"
max_packets=10000000
sample_size=200000
candidate_budget=61440
hill_passes=2
all_active_candidates=false
exact_block_candidates=0
exact_rounds=1
initial_mapping=""

while (($#)); do
  case "$1" in
    --date) date_value="$2"; shift 2 ;;
    --rulefile) rulefile="$2"; shift 2 ;;
    --target-trace) target_trace="$2"; shift 2 ;;
    --target-distribution) target_distribution="$2"; shift 2 ;;
    --input-trace) input_trace="$2"; shift 2 ;;
    --output-root) output_root="$2"; shift 2 ;;
    --trace-root) trace_root="$2"; shift 2 ;;
    --max) max_packets="$2"; shift 2 ;;
    --sample-size) sample_size="$2"; shift 2 ;;
    --candidate-budget) candidate_budget="$2"; shift 2 ;;
    --hill-passes) hill_passes="$2"; shift 2 ;;
    --all-active-candidates) all_active_candidates=true; shift ;;
    --exact-block-candidates) exact_block_candidates="$2"; shift 2 ;;
    --exact-rounds) exact_rounds="$2"; shift 2 ;;
    --initial-mapping) initial_mapping="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$date_value" || -z "$rulefile" || -z "$input_trace" ]]; then
  usage >&2
  exit 2
fi
if [[ -n "$target_trace" && -n "$target_distribution" ]] || [[ -z "$target_trace" && -z "$target_distribution" ]]; then
  echo "exactly one of --target-trace and --target-distribution is required" >&2
  usage >&2
  exit 2
fi

mkdir -p "$output_root/$date_value" "$trace_root"

binary="/tmp/fit_trace_tree_lpm_multi_order"
cd "$root_dir"
/home/yuzugon/go/bin/go build -o "$binary" ./cmd/fit_trace_tree_lpm

orders=(mass top-down bottom-up)
pids=()
for order in "${orders[@]}"; do
  output_dir="$output_root/$date_value/$order"
  output_trace="$trace_root/$date_value-$order-${max_packets}.txt"
  mkdir -p "$output_dir"
  target_args=()
  if [[ -n "$target_distribution" ]]; then
    target_args=(--target-distribution "$target_distribution")
  else
    target_args=(--target-trace "$target_trace")
  fi
  search_args=()
  if [[ "$all_active_candidates" == true ]]; then
    search_args+=(--all-active-candidates)
  fi
  if ((exact_block_candidates > 0)); then
    search_args+=(--exact-block-candidates "$exact_block_candidates" --exact-rounds "$exact_rounds")
  fi
  if [[ -n "$initial_mapping" ]]; then
    search_args+=(--initial-mapping "$initial_mapping")
  fi
  "$binary" \
    --rulefile "$rulefile" \
    "${target_args[@]}" \
    --input-trace "$input_trace" \
    --max "$max_packets" \
    --sample-size "$sample_size" \
    --fit-depth 24 \
    --hill-candidates "$candidate_budget" \
    --hill-passes "$hill_passes" \
    --candidate-order "$order" \
    "${search_args[@]}" \
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
if ((failed)); then
  echo "one or more rotation searches failed" >&2
  exit 1
fi

env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/matplotlib \
  /home/yuzugon/.local/bin/uv run --script scripts/summarize_lpm_rotation_order_experiment.py \
  --input-root "$output_root" \
  --output-dir "$output_root"

awk -F, -v target_date="$date_value" '
  NR == 1 { next }
  $1 == target_date && (best == "" || $6 + 0 < best + 0) {
    best=$6; order=$2; method=$4; trace=$17; report=$18
  }
  END {
    if (best == "") exit 1
    gsub(/\r/, "", report)
    printf "selected date=%s order=%s method=%s TV=%s\n", target_date, order, method, best
    printf "trace=%s\nreport=%s/REPORT.md\n", trace, report
  }
' "$output_root/rotation_order_results.csv"
