#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_fixed_mp_9cache_1k_configs.sh [options]

Runs the fixed 9-layer Multi-Prefix configuration across the comparison traces:
  - 9cache: /24 /23 /22 /21 /20 /19 /18 /17 /16
  - capacity: 1024 entries per layer
  - way: 8

Options:
  --dry-run             Print exec.sh commands without running them.
  --max <int>           Value passed to exec.sh --max (default: 10000000).
  --dbupdate            Force DB insertion/rerun for existing configs.
  --no-sudo             Pass --no-sudo to exec.sh.
  --no-build            Skip the one-time go build.
  -h, --help            Show this help.

After this finishes, regenerate the report with:
  cd /home/yuzugon/ppc-result-viewer
  bash scripts/generate_best_capacity_sweep_graphs.sh
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

DRY_RUN=false
MAX_PROCESS=10000000
DBUPDATE=false
NO_SUDO=false
NO_BUILD=false

while (( $# > 0 )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
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

[[ "$MAX_PROCESS" =~ ^[0-9]+$ ]] || die "--max must be a non-negative integer: $MAX_PROCESS"

TRACE_LABELS=()
TRACE_PATHS=()
RULE_PATHS=()

add_trace() {
  TRACE_LABELS+=("$1")
  TRACE_PATHS+=("$2")
  RULE_PATHS+=("$3")
}

add_trace "WIDE non 2025-09" \
  "/research/trace/2025-09-27.pcap" \
  "/research/rules/rib.20250927.0600.unique.rule"
add_trace "WIDE non 2025-12" \
  "/research/trace/2025-12-27.pcap" \
  "/research/rules/rib.20251227.0600.unique.rule"
add_trace "WIDE non 2026-03" \
  "/research/trace/2026-03-27.pcap" \
  "/research/rules/rib.20260327.0600.unique.rule"
add_trace "JPIX to SINET 2018-05" \
  "/research/trace/jpix2sinet90s_5tuple.txt" \
  "/research/rules/rrc06.bview.20180502.0000.unique.rule"
add_trace "SINET to JPIX 2018-05" \
  "/research/trace/sinet2jpix90s_5tuple.txt" \
  "/research/rules/rrc06.bview.20180502.0000.unique.rule"
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
add_trace "Chicago anon 2014-03" \
  "/research/trace/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap" \
  "/research/rules/route-views.chicago.rib.20160628.1400.unique.rule"
add_trace "New York anon 2019-01" \
  "/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap" \
  "/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule"

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

run() {
  printf '\n==> '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

if [[ "$DRY_RUN" != "true" && "$NO_BUILD" != "true" ]]; then
  run go build main.go
fi

for i in "${!TRACE_LABELS[@]}"; do
  label="${TRACE_LABELS[$i]}"
  trace="${TRACE_PATHS[$i]}"
  rule="${RULE_PATHS[$i]}"

  run ./exec.sh \
    --rulefile "$rule" \
    --trace "$trace" \
    --cachetype MultiLayerCacheExclusive \
    --cachenum 9 \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length 9-24,9-24,9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-start 10 \
    --capacity-end 10 \
    --capacity-step 1 \
    --refbits-start 16 \
    --refbits-end 24 \
    --refbits-step 1 \
    --mp-refbits 24,23,22,21,20,19,18,17,16 \
    --mp-capacities 1024,1024,1024,1024,1024,1024,1024,1024,1024 \
    "${exec_common_flags[@]}"

  echo "[INFO] finished fixed MP 9cache /24..../16 1024 each for ${label}"
done

cat <<'EOF'

Next report command:
  cd /home/yuzugon/ppc-result-viewer
  bash scripts/generate_best_capacity_sweep_graphs.sh
EOF
