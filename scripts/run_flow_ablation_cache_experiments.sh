#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run_flow_ablation_cache_experiments.sh --variant-dir <dir> --rulefile <rule> --output-dir <dir> [options]

Options:
  --variant-dir <dir>       Directory created by generate_flow_ablation_traces.py
  --rulefile <path>         Rule file used by the simulator
  --output-dir <dir>        Where copied hit traces and commands are stored
  --variants <csv>          Variant names to run (default: baseline,remove-top100,cap8192,shuffle-global)
  --configs <csv>           Config names to run (default: ps-ideal-2048,ps-prefix22-8192,mp-24-20-2048-2048)
  --processed <n>           -max value for simulator (default: 0; process whole generated CSV)
  --database-url <url>      DATABASE_URL for main.go (default: current env or mongodb://localhost:27017)
  --no-build                Pass --no-build to exec.sh
  --dry-run                 Print commands but do not run
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

require_value() {
  local opt="$1"
  local value="${2:-}"
  [[ -n "$value" ]] || die "$opt requires a value"
}

VARIANT_DIR=""
RULEFILE=""
OUTPUT_DIR=""
VARIANTS="baseline,remove-top100,cap8192,shuffle-global"
CONFIGS="ps-ideal-2048,ps-prefix22-8192,mp-24-20-2048-2048"
PROCESSED=0
DATABASE_URL_VALUE="${DATABASE_URL:-mongodb://localhost:27017}"
SKIP_BUILD=false
DRY_RUN=false
UNIFIED_TAG_WAY8="9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24"

while (($# > 0)); do
  case "$1" in
    --variant-dir)
      require_value "$1" "${2:-}"
      VARIANT_DIR="$2"
      shift 2
      ;;
    --rulefile)
      require_value "$1" "${2:-}"
      RULEFILE="$2"
      shift 2
      ;;
    --output-dir)
      require_value "$1" "${2:-}"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --variants)
      require_value "$1" "${2:-}"
      VARIANTS="$2"
      shift 2
      ;;
    --configs)
      require_value "$1" "${2:-}"
      CONFIGS="$2"
      shift 2
      ;;
    --processed)
      require_value "$1" "${2:-}"
      PROCESSED="$2"
      shift 2
      ;;
    --database-url)
      require_value "$1" "${2:-}"
      DATABASE_URL_VALUE="$2"
      shift 2
      ;;
    --no-build)
      SKIP_BUILD=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

[[ -n "$VARIANT_DIR" ]] || die "--variant-dir is required"
[[ -n "$RULEFILE" ]] || die "--rulefile is required"
[[ -n "$OUTPUT_DIR" ]] || die "--output-dir is required"
[[ -d "$VARIANT_DIR/traces" ]] || die "variant traces directory not found: $VARIANT_DIR/traces"
[[ -f "$RULEFILE" ]] || die "rulefile not found: $RULEFILE"

mkdir -p "$OUTPUT_DIR/hit_traces" "$OUTPUT_DIR/bin_reports" "$OUTPUT_DIR/gob"

IFS=',' read -r -a VARIANT_VALUES <<< "$VARIANTS"
IFS=',' read -r -a CONFIG_VALUES <<< "$CONFIGS"

exec_args_common=(--rulefile "$RULEFILE" --no-sudo --record-cache-hit)
if [[ "$SKIP_BUILD" == "true" ]]; then
  exec_args_common+=(--no-build)
fi
if ((PROCESSED > 0)); then
  exec_args_common+=(--max "$PROCESSED")
fi

run_config() {
  local config="$1"
  local trace="$2"
  case "$config" in
    ps-ideal-2048)
      ./exec.sh "${exec_args_common[@]}" --trace "$trace" --cachetype UnifiedCache --way 8 \
        --cache-tag-length "$UNIFIED_TAG_WAY8" \
        --cache-index-type 2 --capacity-start 11 --capacity-end 11 --capacity-step 1 \
        --refbits-start 32 --refbits-end 32 --refbits-step 1
      ;;
    ps-prefix22-8192)
      ./exec.sh "${exec_args_common[@]}" --trace "$trace" --cachetype UnifiedCache --way 8 \
        --cache-tag-length "$UNIFIED_TAG_WAY8" \
        --cache-index-type 22 --capacity-start 13 --capacity-end 13 --capacity-step 1 \
        --refbits-start 32 --refbits-end 32 --refbits-step 1
      ;;
    ps-prefix24-2048)
      ./exec.sh "${exec_args_common[@]}" --trace "$trace" --cachetype UnifiedCache --way 8 \
        --cache-tag-length "$UNIFIED_TAG_WAY8" \
        --cache-index-type 24 --capacity-start 11 --capacity-end 11 --capacity-step 1 \
        --refbits-start 32 --refbits-end 32 --refbits-step 1
      ;;
    mp-24-20-2048-2048)
      ./exec.sh "${exec_args_common[@]}" --trace "$trace" --cachetype MultiLayerCacheExclusive --cachenum 2 --way 8 \
        --capacity-start 11 --capacity-end 11 --capacity-step 1 \
        --refbits-start 20 --refbits-end 24 --refbits-step 4
      ;;
    mp-24-18-2048-2048)
      ./exec.sh "${exec_args_common[@]}" --trace "$trace" --cachetype MultiLayerCacheExclusive --cachenum 2 --way 8 \
        --capacity-start 11 --capacity-end 11 --capacity-step 1 \
        --refbits-start 18 --refbits-end 24 --refbits-step 6
      ;;
    mp-24-16-2048-2048)
      ./exec.sh "${exec_args_common[@]}" --trace "$trace" --cachetype MultiLayerCacheExclusive --cachenum 2 --way 8 \
        --capacity-start 11 --capacity-end 11 --capacity-step 1 \
        --refbits-start 16 --refbits-end 24 --refbits-step 8
      ;;
    *)
      die "unknown config: $config"
      ;;
  esac
}

COMMAND_LOG="$OUTPUT_DIR/commands.log"
: > "$COMMAND_LOG"

for variant in "${VARIANT_VALUES[@]}"; do
  variant="$(echo "$variant" | xargs)"
  [[ -n "$variant" ]] || continue
  trace_path="$(find "$VARIANT_DIR/traces" -maxdepth 1 -type f -name "*__${variant}.csv" | head -n 1)"
  [[ -n "$trace_path" ]] || die "trace for variant not found: $variant"
  for config in "${CONFIG_VALUES[@]}"; do
    config="$(echo "$config" | xargs)"
    [[ -n "$config" ]] || continue
    echo "variant=$variant config=$config trace=$trace_path" | tee -a "$COMMAND_LOG"
    if [[ "$DRY_RUN" == "true" ]]; then
      continue
    fi
    before="$(find cachehitrace -maxdepth 1 -type f -name '*.txt' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2- || true)"
    DATABASE_URL="$DATABASE_URL_VALUE" GOB_PACKET_DIR="$OUTPUT_DIR/gob" run_config "$config" "$trace_path"
    latest="$(find cachehitrace -maxdepth 1 -type f -name '*.txt' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2- || true)"
    if [[ -z "$latest" ]]; then
      die "record-cache-hit did not produce a cachehitrace file"
    fi
    if [[ "$latest" == "$before" ]]; then
      echo "[WARN] newest cachehitrace path did not change; copying it anyway: $latest" >&2
    fi
    copied="$OUTPUT_DIR/hit_traces/${variant}__${config}.txt"
    cp "$latest" "$copied"
    python3 scripts/analyze_cache_hit_by_flow_bin.py \
      --packet-flow-map "$VARIANT_DIR/packet_flow_map.csv" \
      --hit-trace "$copied" \
      --variant "$variant" \
      --config-label "$config" \
      --output-dir "$OUTPUT_DIR/bin_reports"
  done
done

echo "wrote experiment outputs to $OUTPUT_DIR"
