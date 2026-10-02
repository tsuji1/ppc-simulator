#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/run_unified_advanced_24bit_xor.sh [options]

Run baseline, length-aware multi-probe, way quota, skewed associative, and
the combined policy on the nine existing 24-bit XOR transformed traces.

Options:
  --max <int>          Packets per simulation (default: 10000000)
  --jobs <int>         Concurrent simulations (default: 2)
  --trace-index <int>  Run only one trace index (0..8)
  --dry-run            Print commands only
  --no-build           Reuse ./main
  --no-dbupdate        Reuse matching MongoDB results
  -h, --help           Show this help
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

MAX_PROCESS=10000000
JOBS=2
TRACE_INDEX=""
DRY_RUN=false
NO_BUILD=false
DBUPDATE=true

while (( $# > 0 )); do
  case "$1" in
    --max) [[ -n "${2:-}" ]] || die "--max requires a value"; MAX_PROCESS="$2"; shift 2 ;;
    --jobs) [[ -n "${2:-}" ]] || die "--jobs requires a value"; JOBS="$2"; shift 2 ;;
    --trace-index) [[ -n "${2:-}" ]] || die "--trace-index requires a value"; TRACE_INDEX="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --no-build) NO_BUILD=true; shift ;;
    --no-dbupdate) DBUPDATE=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$MAX_PROCESS" =~ ^[1-9][0-9]*$ ]] || die "--max must be a positive integer"
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"
if [[ -n "$TRACE_INDEX" ]]; then
  [[ "$TRACE_INDEX" =~ ^[0-8]$ ]] || die "--trace-index must be in 0..8"
fi

DERIVED=/home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24
TRACE_LABELS=(
  "Chicago -> 2025-09" "Chicago -> 2025-12" "Chicago -> 2026-03"
  "NYC -> 2025-09" "NYC -> 2025-12" "NYC -> 2026-03"
  "anon-WIDE -> 2025-09" "anon-WIDE -> 2025-12" "anon-WIDE -> 2026-03"
)
TRACE_PATHS=(
  "$DERIVED/chicago/2025-09-27.txt" "$DERIVED/chicago/2025-12-27.txt" "$DERIVED/chicago/2026-03-27.txt"
  "$DERIVED/nyc/2025-09-27.txt" "$DERIVED/nyc/2025-12-27.txt" "$DERIVED/nyc/2026-03-27.txt"
  "$DERIVED/anon-wide/2025-09-27.txt" "$DERIVED/anon-wide/2025-12-27.txt" "$DERIVED/anon-wide/2026-03-27.txt"
)
RULE_PATHS=(
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rib.20250927.0600.unique.rule
  /home/yuzugon/rules/rib.20251227.0600.unique.rule
  /home/yuzugon/rules/rib.20260327.0600.unique.rule
)

if [[ "$DRY_RUN" != true && "$NO_BUILD" != true ]]; then
  /usr/local/go/bin/go build main.go
fi

common=(
  --no-build --no-sudo --cachetype UnifiedCache --way 8
  --cache-index-type 24 --cache-index-policy fixed
  --cache-tag-length 9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24
  --cache-insertion-policy exclusive
  --multi-probe-lengths 18,20,22,24
  --way-quota-wide-max 18
  --capacity-start 13 --capacity-end 13 --capacity-step 1
  --max "$MAX_PROCESS"
)
if [[ "$DBUPDATE" == true ]]; then common+=(--dbupdate); else common+=(--no-dbupdate); fi
if [[ "$DRY_RUN" == true ]]; then common+=(--dry-run); fi

running=0
failures=0
launch() {
  echo "==> $*"
  if [[ "$DRY_RUN" == true ]]; then
    "$@"
    return
  fi
  ("$@") &
  running=$((running + 1))
  if (( running >= JOBS )); then
    if ! wait -n; then failures=$((failures + 1)); fi
    running=$((running - 1))
  fi
}

run_configurations() {
  local rule="$1"
  local trace="$2"
  launch ./exec.sh --rulefile "$rule" --trace "$trace" --no-length-aware-multi-probe --way-quota-wide-ways 0 --no-skewed-associative "${common[@]}"
  launch ./exec.sh --rulefile "$rule" --trace "$trace" --length-aware-multi-probe --way-quota-wide-ways 0 --no-skewed-associative "${common[@]}"
  launch ./exec.sh --rulefile "$rule" --trace "$trace" --no-length-aware-multi-probe --way-quota-wide-ways 2 --no-skewed-associative "${common[@]}"
  launch ./exec.sh --rulefile "$rule" --trace "$trace" --no-length-aware-multi-probe --way-quota-wide-ways 0 --skewed-associative "${common[@]}"
  launch ./exec.sh --rulefile "$rule" --trace "$trace" --length-aware-multi-probe --way-quota-wide-ways 2 --skewed-associative "${common[@]}"
}

for i in "${!TRACE_PATHS[@]}"; do
  if [[ -n "$TRACE_INDEX" && "$i" != "$TRACE_INDEX" ]]; then
    continue
  fi
  [[ "$DRY_RUN" == true || -f "${TRACE_PATHS[$i]}" ]] || die "missing trace: ${TRACE_PATHS[$i]}"
  [[ "$DRY_RUN" == true || -f "${RULE_PATHS[$i]}" ]] || die "missing rule: ${RULE_PATHS[$i]}"
  run_configurations "${RULE_PATHS[$i]}" "${TRACE_PATHS[$i]}"
  echo "[QUEUED] ${TRACE_LABELS[$i]}"
done

while (( running > 0 )); do
  if ! wait -n; then failures=$((failures + 1)); fi
  running=$((running - 1))
done
(( failures == 0 )) || die "$failures simulation(s) failed"
echo "[DONE] UnifiedCache advanced-policy 24-bit XOR matrix"
