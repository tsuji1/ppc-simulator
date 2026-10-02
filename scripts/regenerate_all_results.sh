#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  scripts/regenerate_all_results.sh [options]

Runs the experiment configs used by the current result scripts, then regenerates
CSV/PNG/Markdown reports from MongoDB.

Options:
  --dry-run           Print commands without executing them.
  --skip-sim         Skip simulator reruns; only regenerate reports.
  --skip-reports     Skip report/plot regeneration; only rerun simulations.
  --skip-inclusive   Do not rerun UnifiedCache inclusive-policy experiments.
  --skip-multi       Do not rerun MultiLayerCacheExclusive experiments.
  --skip-full-lru    Do not rerun FullAssociativeLRUCache experiments.
  --no-dbupdate      Do not force DB insertion on simulator runs.
  --no-logip         Do not emit UnifiedCache second-miss IP CSVs.
  --no-sudo          Pass --no-sudo to exec.sh.
  --no-build         Skip the one-time go build and pass --no-build to exec.sh.
  -h, --help         Show this help.

Environment overrides:
  RULE_FILE_NAME     DB filter rule_file_name (default: rib.20260327.0600.unique.rule)
  TRACE_FILE_NAME    DB filter trace_file_name (default: 2026-03-27.pcap)
  PROCESSED          DB filter processed packet count (default: 10000000)
  UV_CACHE_DIR       uv cache directory (default: /tmp/uv-cache)
  MPLCONFIGDIR       matplotlib config directory (default: /tmp/matplotlib)

Notes:
  --dbupdate inserts fresh documents; it does not delete older MongoDB results.
EOF
}

DRY_RUN=false
RUN_SIM=true
RUN_REPORTS=true
RUN_INCLUSIVE=true
RUN_MULTI=true
RUN_FULL_LRU=true
DBUPDATE=true
LOGIP=true
NO_SUDO=false
NO_BUILD=false

while (( $# > 0 )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --skip-sim)
      RUN_SIM=false
      shift
      ;;
    --skip-reports)
      RUN_REPORTS=false
      shift
      ;;
    --skip-inclusive)
      RUN_INCLUSIVE=false
      shift
      ;;
    --skip-multi)
      RUN_MULTI=false
      shift
      ;;
    --skip-full-lru)
      RUN_FULL_LRU=false
      shift
      ;;
    --no-dbupdate)
      DBUPDATE=false
      shift
      ;;
    --no-logip)
      LOGIP=false
      shift
      ;;
    --no-sudo)
      NO_SUDO=true
      shift
      ;;
    --no-build)
      NO_BUILD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

RULE_FILE_NAME="${RULE_FILE_NAME:-rib.20260327.0600.unique.rule}"
TRACE_FILE_NAME="${TRACE_FILE_NAME:-2026-03-27.pcap}"
PROCESSED="${PROCESSED:-10000000}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/matplotlib}"

UNIFIED_TAG_WAY8="9-24,9-24,10-24,10-24,11-24,11-24,12-24,12-24"
UNIFIED_TAG_WAY8_FLAT="9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24"
LOGIP_OUTPUT_DIR="scripts/reports/unified_second_miss_ip_depth_lpc"

run() {
  printf '\n==> '
  printf '%q ' "$@"
  printf '\n'
  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi
  "$@"
}

run_exec_config() {
  local config="$1"
  shift
  local cmd=(./exec.sh --config "$config")

  if [[ "$DBUPDATE" == "true" ]]; then
    cmd+=(--dbupdate)
  else
    cmd+=(--no-dbupdate)
  fi
  if [[ "$NO_SUDO" == "true" ]]; then
    cmd+=(--no-sudo)
  fi
  cmd+=(--no-build)
  cmd+=("$@")

  run "${cmd[@]}"
}

run_unified_config_with_logdir() {
  local config="$1"
  local logip_output_dir="$2"
  shift 2
  local extra=()

  if [[ "$LOGIP" == "true" ]]; then
    extra+=(--logip --logip-top 100 --logip-output-dir "$logip_output_dir")
  fi

  run_exec_config "$config" "${extra[@]}" "$@"
}

run_unified_config() {
  local config="$1"
  shift
  run_unified_config_with_logdir "$config" "$LOGIP_OUTPUT_DIR" "$@"
}

run_uv() {
  run env MPLCONFIGDIR="$MPLCONFIGDIR" UV_CACHE_DIR="$UV_CACHE_DIR" uv run --script "$@"
}

common_filter_args=(
  --rule-file-name "$RULE_FILE_NAME"
  --trace-file-name "$TRACE_FILE_NAME"
)

processed_filter_args=(
  "${common_filter_args[@]}"
  --processed "$PROCESSED"
)

unified_way8_index5_args=(
  "${processed_filter_args[@]}"
  --way 8
  --cache-index-type 5
  --insertion-policy exclusive
)

if [[ "$RUN_SIM" == "true" ]]; then
  if [[ "$NO_BUILD" != "true" ]]; then
    run go build main.go
  fi

  if [[ "$RUN_FULL_LRU" == "true" ]]; then
    run_exec_config simulator-settings/exp/full-lru-20260327.env
  fi

  if [[ "$RUN_MULTI" == "true" ]]; then
    run_exec_config simulator-settings/exp/multi-exclusive-20260327.env
    run_exec_config scripts/env/multi-exclusive-128-1024.env
  fi

  run_unified_config simulator-settings/exp/unified-20260327-index-sweep.env
  run_unified_config scripts/env/unified-128-1024.env \
    --cache-tag-length "$UNIFIED_TAG_WAY8_FLAT"
  run_unified_config scripts/env/unified-way8-2p6-2p14.env
  run_unified_config scripts/env/unified-way8-2p15-2p17.env
  run_unified_config scripts/env/unified-ideal-way8-2p6-2p9.env
  run_unified_config scripts/env/unified-ideal-way8-2p14-2p17.env
fi

if [[ "$RUN_REPORTS" == "true" ]]; then
  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope cacheline \
    --plot-unit percent \
    --output scripts/unified_first_second_miss_ratio_2p6_2p14.png \
    --csv-output scripts/unified_first_second_miss_ratio_2p6_2p14.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope cacheline \
    --plot-unit absolute \
    --output scripts/unified_cacheline_first_second_miss_counts_way8_index5_2p6_2p14.png \
    --csv-output scripts/unified_cacheline_first_second_miss_counts_way8_index5_2p6_2p14.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope cacheline \
    --plot-unit absolute \
    --y-focus first \
    --output scripts/unified_cacheline_first_second_miss_counts_way8_index5_2p6_2p14_first_zoom.png \
    --csv-output scripts/unified_cacheline_first_second_miss_counts_way8_index5_2p6_2p14_first_zoom.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope whole-cache \
    --plot-unit absolute \
    --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14.png \
    --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope whole-cache \
    --plot-unit absolute \
    --y-focus first \
    --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14_first_zoom.png \
    --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14_first_zoom.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope whole-cache \
    --plot-unit absolute \
    --ymin 0 \
    --ymax 10000 \
    --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14_y0_10000.png \
    --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14_y0_10000.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --miss-scope whole-cache \
    --plot-unit absolute \
    --ymin 0 \
    --ymax 10000 \
    --tail-start-exp 14 \
    --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14_y0_10000_tail14_connected.png \
    --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p14_y0_10000_tail14_connected.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 17 \
    --miss-scope whole-cache \
    --plot-unit absolute \
    --tail-start-exp 14 \
    --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p17_tail14_connected.png \
    --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p17_tail14_connected.csv

  run_uv scripts/plot_unified_miss_ratio_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 17 \
    --miss-scope whole-cache \
    --plot-unit absolute \
    --ymin 0 \
    --ymax 10000 \
    --tail-start-exp 14 \
    --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p17_y0_10000_tail14_connected.png \
    --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p17_y0_10000_tail14_connected.csv

  run_uv scripts/plot_unified_whole_cache_counts_2p6_2p14.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --output scripts/unified_whole_cache_hit_miss_counts_way8_index5_2p6_2p14.png \
    --csv-output scripts/unified_whole_cache_hit_miss_counts_way8_index5_2p6_2p14.csv

  run_uv scripts/plot_unified_whole_cache_counts_2p6_2p14.py \
    "${processed_filter_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --output scripts/unified_whole_cache_hit_miss_counts_2p6_2p14.png \
    --csv-output scripts/unified_whole_cache_hit_miss_counts_2p6_2p14.csv

  run_uv scripts/analyze_unified_miss_details.py \
    "${processed_filter_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --output-dir scripts/reports/unified_miss_details

  run_uv scripts/analyze_unified_miss_details.py \
    "${unified_way8_index5_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --output-dir scripts/reports/unified_miss_details_way8_index5

  run_uv scripts/analyze_unified_exclusive_rejection_estimate.py \
    "${processed_filter_args[@]}" \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length "$UNIFIED_TAG_WAY8" \
    --start-exp 6 \
    --end-exp 14 \
    --output scripts/reports/unified_exclusive_rejection_estimate_way8_index5/unified_exclusive_rejection_estimate.png \
    --csv-output scripts/reports/unified_exclusive_rejection_estimate_way8_index5/unified_exclusive_rejection_estimate.csv

  run_uv scripts/plot_compare_3caches_way8_index5_立て.py \
    "${common_filter_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --unified-index-types 5 \
    --hitrate-ymins 50 98 99 \
    --missrate-ymaxes 1 2 5 98 99 \
    --output-prefix scripts/results/compare_3caches_way8_index5

  run_uv scripts/plot_compare_3caches_way8_index5_立て.py \
    "${common_filter_args[@]}" \
    --start-exp 6 \
    --end-exp 14 \
    --max-capacity 8192 \
    --unified-index-types 5 \
    --hitrate-ymins 50 \
    --missrate-ymaxes 5 \
    --output-prefix scripts/compare_3caches_way8_index5_cap8192

  run_uv scripts/plot_compare_3caches_way8_index5_立て.py \
    "${common_filter_args[@]}" \
    --start-exp 10 \
    --end-exp 13 \
    --unified-index-types 2 5 \
    --hitrate-ymins 98 99 \
    --missrate-ymaxes 2 \
    --output-prefix scripts/results/compare_3caches_way8_ideal_index18_2p10_2p13

  run_uv scripts/plot_compare_3caches_way8_index5_立て.py \
    "${common_filter_args[@]}" \
    --start-exp 10 \
    --end-exp 13 \
    --unified-index-types 2 5 \
    --hitrate-ymins 98 99 \
    --missrate-ymaxes 1 \
    --output-prefix scripts/results/compare_3caches_way8_index2_5_2p10_2p13

  run_uv scripts/plot_hitrate_way4_8_index3_4_5_立て.py \
    "${common_filter_args[@]}" \
    --output scripts/unified_way4_8_index2_3_4_5_hitrate.png

  run_uv scripts/plot_hitrate_全部盛り_立て.py \
    "${common_filter_args[@]}" \
    --output-prefix scripts/hitrate_全部盛り

  run_uv scripts/plot_hitrate_全部盛り_立て.py \
    "${common_filter_args[@]}" \
    --output-prefix scripts/hitrate_全部盛り_index2
fi

if [[ "$RUN_SIM" == "true" && "$RUN_INCLUSIVE" == "true" ]]; then
  run_unified_config_with_logdir scripts/env/unified-way8-2p6-2p14.env "${LOGIP_OUTPUT_DIR}_inclusive" \
    --cache-insertion-policy inclusive
fi

if [[ "$RUN_REPORTS" == "true" ]]; then
  run_uv scripts/plot_unified_insertion_policy_comparison.py \
    "${processed_filter_args[@]}" \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length "$UNIFIED_TAG_WAY8" \
    --start-exp 6 \
    --end-exp 14 \
    --output scripts/reports/unified_insertion_policy_comparison_way8_index5/unified_insertion_policy_comparison.png \
    --csv-output scripts/reports/unified_insertion_policy_comparison_way8_index5/unified_insertion_policy_comparison.csv
fi
