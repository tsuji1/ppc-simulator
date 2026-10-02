#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_lpm_prefix_coverage_comparison.sh \
    NAME MAX_PACKETS SOURCE_RULE TARGET_RULE TARGET_TRACE ORIGINAL_TRACE \
    GLOBAL_XOR_TRACE GREEDY_TOP_DOWN_TRACE GREEDY_BOTTOM_UP_TRACE OUTPUT_DIR

SOURCE_RULE is used for the original and all transformed traces. TARGET_RULE is
used only for the non-anonymized target. All traces are stopped at MAX_PACKETS,
so raw distinct-prefix counts are directly comparable.
EOF
}

if [[ $# -ne 10 ]]; then
  usage >&2
  exit 2
fi

NAME=$1
MAX_PACKETS=$2
SOURCE_RULE=$3
TARGET_RULE=$4
TARGET_TRACE=$5
ORIGINAL_TRACE=$6
GLOBAL_XOR_TRACE=$7
GREEDY_TOP_DOWN_TRACE=$8
GREEDY_BOTTOM_UP_TRACE=$9
OUTPUT_DIR=${10}

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
GO=${GO:-/usr/local/go/bin/go}
UV=${UV:-uv}
BIN=${TMPDIR:-/tmp}/analyze_lpm_prefix_coverage
CHECKPOINTS=${CHECKPOINTS:-100000,300000,1000000,3000000}
PROGRESS_INTERVAL=${PROGRESS_INTERVAL:-1000000}

for path in "$SOURCE_RULE" "$TARGET_RULE" "$TARGET_TRACE" "$ORIGINAL_TRACE" \
  "$GLOBAL_XOR_TRACE" "$GREEDY_TOP_DOWN_TRACE" "$GREEDY_BOTTOM_UP_TRACE"; do
  [[ -f "$path" ]] || { echo "missing input: $path" >&2; exit 1; }
done

mkdir -p "$OUTPUT_DIR"
cd "$ROOT"
"$GO" build -o "$BIN" ./cmd/analyze_lpm_prefix_coverage

analyze() {
  local label=$1 rule=$2 trace=$3 slug=$4
  "$BIN" \
    --rulefile "$rule" \
    --trace "$trace" \
    --label "$label" \
    --max "$MAX_PACKETS" \
    --checkpoints "$CHECKPOINTS" \
    --progress-interval "$PROGRESS_INTERVAL" \
    --output-dir "$OUTPUT_DIR/$slug"
}

analyze non-anon-target "$TARGET_RULE" "$TARGET_TRACE" non-anon-target
analyze original-anon "$SOURCE_RULE" "$ORIGINAL_TRACE" original-anon
analyze global-xor "$SOURCE_RULE" "$GLOBAL_XOR_TRACE" global-xor
analyze greedy-top-down "$SOURCE_RULE" "$GREEDY_TOP_DOWN_TRACE" greedy-top-down
analyze greedy-bottom-up "$SOURCE_RULE" "$GREEDY_BOTTOM_UP_TRACE" greedy-bottom-up

MPLCONFIGDIR=${MPLCONFIGDIR:-/tmp/matplotlib} UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache} \
  "$UV" run --script scripts/plot_lpm_prefix_coverage.py \
  --input "non-anon-target=$OUTPUT_DIR/non-anon-target/lpm_prefix_coverage.csv" \
  --input "original-anon=$OUTPUT_DIR/original-anon/lpm_prefix_coverage.csv" \
  --input "global-xor=$OUTPUT_DIR/global-xor/lpm_prefix_coverage.csv" \
  --input "greedy-top-down=$OUTPUT_DIR/greedy-top-down/lpm_prefix_coverage.csv" \
  --input "greedy-bottom-up=$OUTPUT_DIR/greedy-bottom-up/lpm_prefix_coverage.csv" \
  --target non-anon-target \
  --title "$NAME" \
  --output-dir "$OUTPUT_DIR/comparison"

echo "[DONE] $OUTPUT_DIR"
