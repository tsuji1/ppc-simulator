#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRACE="${TRACE:-/research/trace/2026-03-27.pcap}"
RULEFILE="${RULEFILE:-/research/rules/rib.20260327.0600.unique.rule}"
OUTDIR="${OUTDIR:-scripts/reports/windowed_hitrate_wide_nonanon}"
MAX_PACKETS="${MAX_PACKETS:-10000000}"
WINDOWS="${WINDOWS:-10000,100000,1000000}"
MP_REFBITS="${MP_REFBITS:-24,18}"
MP_CAPACITIES="${MP_CAPACITIES:-2048,2048}"
PS_INDEX_TYPES="${PS_INDEX_TYPES:-21,2}"
PS_CAPACITY="${PS_CAPACITY:-8192}"
CACHE_TAG_LENGTH="${CACHE_TAG_LENGTH:-9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24}"
WINDOW_MODE="${WINDOW_MODE:-warm}"

trace_stem="$(basename "$TRACE")"
trace_stem="${trace_stem%.*}"
output_base="$OUTDIR/windowed_hitrate_${trace_stem}_${WINDOW_MODE}"
output_csv="${output_base}.csv"
if [[ -e "$output_csv" ]]; then
  output_base="${output_base}_$(date +%Y%m%dT%H%M%S)"
  output_csv="${output_base}.csv"
fi
output_prefix="$(basename "$output_base")"
summary_md="${output_base}_summary.md"

mkdir -p "$OUTDIR"

runner=(scripts/windowed_hitrate)
if [[ "${EUID:-$(id -u)}" -ne 0 && ! -r "$TRACE" ]]; then
  runner=(sudo "${runner[@]}")
fi

"${runner[@]}" \
  -rulefile "$RULEFILE" \
  -trace "$TRACE" \
  -output-dir "$OUTDIR" \
  -output-csv "$output_csv" \
  -max "$MAX_PACKETS" \
  -windows "$WINDOWS" \
  -mp-refbits "$MP_REFBITS" \
  -mp-capacities "$MP_CAPACITIES" \
  -ps-index-types "$PS_INDEX_TYPES" \
  -ps-capacity "$PS_CAPACITY" \
  -cache-tag-length "$CACHE_TAG_LENGTH" \
  -window-mode "$WINDOW_MODE"

python3 scripts/summarize_windowed_hitrate.py \
  --input "$output_csv" \
  --output "$summary_md"

MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/matplotlib}" \
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" \
uv run --script scripts/plot_windowed_hitrate.py \
  --input "$output_csv" \
  --output-dir "$OUTDIR" \
  --output-prefix "$output_prefix" \
  --title "WIDE non-anonymized (${WINDOW_MODE})"
