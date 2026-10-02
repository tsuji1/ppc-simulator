#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run_lpm_exact_seeded_one.sh \
    --rulefile PATH \
    --target-distribution CSV \
    --input-trace PATH \
    --initial-mapping PATH \
    --candidate-order mass|top-down|bottom-up \
    --output-trace PATH \
    --output-dir PATH \
    [--max PACKETS] \
    [--sample-size PACKETS] \
    [--candidate-budget N] \
    [--hill-passes N] \
    [--exact-block-candidates N] \
    [--exact-rounds N] \
    [--binary PATH]

Runs the LPM-distribution fitter from a supplied greedy mapping, then applies
all-active-candidate exact block-coordinate refinement.
EOF
}

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rulefile=""
target_distribution=""
input_trace=""
initial_mapping=""
candidate_order=""
output_trace=""
output_dir=""
max_packets=10000000
sample_size=200000
candidate_budget=61440
hill_passes=2
exact_block_candidates=30
exact_rounds=10
binary="/tmp/fit_trace_tree_lpm_exact_seeded_one"

while (($#)); do
  case "$1" in
    --rulefile) rulefile="$2"; shift 2 ;;
    --target-distribution) target_distribution="$2"; shift 2 ;;
    --input-trace) input_trace="$2"; shift 2 ;;
    --initial-mapping) initial_mapping="$2"; shift 2 ;;
    --candidate-order) candidate_order="$2"; shift 2 ;;
    --output-trace) output_trace="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --max) max_packets="$2"; shift 2 ;;
    --sample-size) sample_size="$2"; shift 2 ;;
    --candidate-budget) candidate_budget="$2"; shift 2 ;;
    --hill-passes) hill_passes="$2"; shift 2 ;;
    --exact-block-candidates) exact_block_candidates="$2"; shift 2 ;;
    --exact-rounds) exact_rounds="$2"; shift 2 ;;
    --binary) binary="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for value in \
  "$rulefile" "$target_distribution" "$input_trace" "$initial_mapping" \
  "$candidate_order" "$output_trace" "$output_dir"; do
  if [[ -z "$value" ]]; then
    usage >&2
    exit 2
  fi
done

case "$candidate_order" in
  mass|top-down|bottom-up) ;;
  *) echo "invalid candidate order: $candidate_order" >&2; exit 2 ;;
esac

mkdir -p "$output_dir" "$(dirname "$output_trace")"
cd "$root_dir"

if [[ ! -x "$binary" ]]; then
  /home/yuzugon/go/bin/go build -o "$binary" ./cmd/fit_trace_tree_lpm
fi

"$binary" \
  --rulefile "$rulefile" \
  --target-distribution "$target_distribution" \
  --input-trace "$input_trace" \
  --initial-mapping "$initial_mapping" \
  --max "$max_packets" \
  --sample-size "$sample_size" \
  --fit-depth 24 \
  --hill-candidates "$candidate_budget" \
  --hill-passes "$hill_passes" \
  --candidate-order "$candidate_order" \
  --all-active-candidates \
  --exact-block-candidates "$exact_block_candidates" \
  --exact-rounds "$exact_rounds" \
  --output-trace "$output_trace" \
  --output-dir "$output_dir"
