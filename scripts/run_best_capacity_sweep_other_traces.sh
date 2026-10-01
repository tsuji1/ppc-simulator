#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_best_capacity_sweep_other_traces.sh [options]

Runs the broad sweep needed by the best-capacity cross-trace report for traces
that did not already have wide coverage.

Default sweep:
  - MultiLayerCacheExclusive, 2 caches, way 8
    capacity per cache: 2^9..2^15 entries
    refbits: /24 + /16..23
  - UnifiedCache, way 8
    capacity: 2^10..2^15 entries
    cache index types: 2,16,17,18,19,20,21,22,23,24
    override with UNIFIED_INDEX_TYPES=116,118,120,122,124 for prefix direct no-hash
    tag length: 9-24 for all 8 ways
    insertion policy: exclusive
  - max processed packets: 10000000
  - --no-dbupdate, so existing MongoDB results are skipped

Options:
  --dry-run             Print generated ./main commands without running them.
  --only <all|mp|unified>
                        Limit the sweep family (default: all).
  --trace-set <all|jpix-sinet|nyc|chicago|nyc-chicago>
                        Limit trace set (default: all).
  --include-20260327    Also include non-anonymized WIDE 2026-03-27.
  --max <int>           Value passed to exec.sh --max (default: 10000000).
  --dbupdate            Force DB insertion/rerun for existing configs.
  --no-sudo             Pass --no-sudo to exec.sh.
  --no-build            Skip the one-time go build.
  -h, --help            Show this help.

After this finishes, regenerate the report with:
  cd /home/yuzugon/ppc-result-viewer
  scripts/generate_best_capacity_sweep_graphs.sh
For prefix direct no-hash runs, use:
  scripts/generate_best_capacity_sweep_graphs_ps_nohash.sh
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

DRY_RUN=false
ONLY="all"
TRACE_SET="all"
INCLUDE_20260327=false
MAX_PROCESS=10000000
DBUPDATE=false
NO_SUDO=false
NO_BUILD=false
UNIFIED_INDEX_TYPES="${UNIFIED_INDEX_TYPES:-2,16,17,18,19,20,21,22,23,24}"

while (( $# > 0 )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --only)
      [[ -n "${2:-}" ]] || die "--only requires a value"
      ONLY="$2"
      shift 2
      ;;
    --trace-set)
      [[ -n "${2:-}" ]] || die "--trace-set requires a value"
      TRACE_SET="$2"
      shift 2
      ;;
    --include-20260327)
      INCLUDE_20260327=true
      shift
      ;;
    --max)
      [[ -n "${2:-}" ]] || die "--max requires a value"
      MAX_PROCESS="$2"
      shift 2
      ;;
    --dbupdate)
      DBUPDATE=true
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
      die "unknown option: $1"
      ;;
  esac
done

case "$ONLY" in
  all|mp|unified) ;;
  *) die "--only must be one of: all, mp, unified" ;;
esac
case "$TRACE_SET" in
  all|jpix-sinet|nyc|chicago|nyc-chicago) ;;
  *) die "--trace-set must be one of: all, jpix-sinet, nyc, chicago, nyc-chicago" ;;
esac

[[ "$MAX_PROCESS" =~ ^[0-9]+$ ]] || die "--max must be a non-negative integer: $MAX_PROCESS"

TRACE_LABELS=()
TRACE_PATHS=()
RULE_PATHS=()

add_trace() {
  TRACE_LABELS+=("$1")
  TRACE_PATHS+=("$2")
  RULE_PATHS+=("$3")
}

if [[ "$TRACE_SET" == "all" ]]; then
  add_trace "WIDE non 2025-09" \
    "/research/trace/2025-09-27.pcap" \
    "/research/rules/rib.20250927.0600.unique.rule"

  add_trace "WIDE non 2025-12" \
    "/research/trace/2025-12-27.pcap" \
    "/research/rules/rib.20251227.0600.unique.rule"

  if [[ "$INCLUDE_20260327" == "true" ]]; then
    add_trace "WIDE non 2026-03" \
      "/research/trace/2026-03-27.pcap" \
      "/research/rules/rib.20260327.0600.unique.rule"
  fi

  add_trace "WIDE anon 2025-09" \
    "/research/trace/202509271400.pcap" \
    "/research/rules/rib.20250927.0600.unique.rule"

  add_trace "WIDE anon 2025-12" \
    "/research/trace/202512271400.pcap" \
    "/research/rules/rib.20251227.0600.unique.rule"

  add_trace "WIDE anon 2026-03" \
    "/research/trace/202603271400.pcap" \
    "/research/rules/rib.20260327.0600.unique.rule"

  add_trace "San Jose anon 2014-03" \
    "/research/trace/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap" \
    "/research/rules/route-views.isc.rib.20140320.1400.unique.rule"

fi

if [[ "$TRACE_SET" == "all" || "$TRACE_SET" == "chicago" || "$TRACE_SET" == "nyc-chicago" ]]; then
  add_trace "Chicago anon 2014-03" \
    "/research/trace/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap" \
    "/research/rules/route-views.chicago.rib.20160628.1400.unique.rule"
fi

if [[ "$TRACE_SET" == "all" || "$TRACE_SET" == "nyc" || "$TRACE_SET" == "nyc-chicago" ]]; then
  add_trace "New York anon 2019-01" \
    "/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap" \
    "/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule"
fi

if [[ "$TRACE_SET" == "all" || "$TRACE_SET" == "jpix-sinet" ]]; then
  add_trace "JPIX to SINET 2018-05" \
    "/research/trace/jpix2sinet90s_5tuple.txt" \
    "/research/rules/rrc06.bview.20180502.0000.unique.rule"

  add_trace "SINET to JPIX 2018-05" \
    "/research/trace/sinet2jpix90s_5tuple.txt" \
    "/research/rules/rrc06.bview.20180502.0000.unique.rule"
fi

run() {
  printf '\n==> '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

exec_common_flags=(
  --no-build
  --max "$MAX_PROCESS"
)

if [[ "$DBUPDATE" == "true" ]]; then
  exec_common_flags+=(--dbupdate)
else
  exec_common_flags+=(--no-dbupdate)
fi
if [[ "$DRY_RUN" == "true" ]]; then
  exec_common_flags+=(--dry-run)
fi
if [[ "$NO_SUDO" == "true" ]]; then
  exec_common_flags+=(--no-sudo)
fi

if [[ "$DRY_RUN" != "true" && "$NO_BUILD" != "true" ]]; then
  run go build main.go
fi

run_mp() {
  local label="$1"
  local trace="$2"
  local rule="$3"

  run ./exec.sh \
    --rulefile "$rule" \
    --trace "$trace" \
    --cachetype MultiLayerCacheExclusive \
    --cachenum 2 \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length 9-24,9-24,9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-start 9 \
    --capacity-end 15 \
    --capacity-step 1 \
    --refbits-start 16 \
    --refbits-end 24 \
    --refbits-step 1 \
    "${exec_common_flags[@]}"

  echo "[INFO] finished MP sweep command for ${label}"
}

run_unified() {
  local label="$1"
  local trace="$2"
  local rule="$3"

  run ./exec.sh \
    --rulefile "$rule" \
    --trace "$trace" \
    --cachetype UnifiedCache \
    --way 8 \
    --cache-index-types "$UNIFIED_INDEX_TYPES" \
    --cache-tag-length 9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-start 10 \
    --capacity-end 15 \
    --capacity-step 1 \
    --refbits-start 32 \
    --refbits-end 32 \
    --refbits-step 1 \
    "${exec_common_flags[@]}"

  echo "[INFO] finished Unified sweep command for ${label}"
}

for i in "${!TRACE_LABELS[@]}"; do
  label="${TRACE_LABELS[$i]}"
  trace="${TRACE_PATHS[$i]}"
  rule="${RULE_PATHS[$i]}"

  case "$ONLY" in
    all)
      run_mp "$label" "$trace" "$rule"
      run_unified "$label" "$trace" "$rule"
      ;;
    mp)
      run_mp "$label" "$trace" "$rule"
      ;;
    unified)
      run_unified "$label" "$trace" "$rule"
      ;;
  esac
done

cat <<'EOF'

Next report command:
  cd /home/yuzugon/ppc-result-viewer
  scripts/generate_best_capacity_sweep_graphs.sh
  # For prefix direct no-hash runs:
  scripts/generate_best_capacity_sweep_graphs_ps_nohash.sh
EOF
