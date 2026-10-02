#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/run_global_xor_anon_ps_capacity32k.sh [options]

Run only the missing 16K/32K PS UnifiedCache measurements for the 9
LPM-distribution-matched anonymous traces (San Jose, Chicago, NYC x 3 targets).

Options:
  --max <int>          Packets per simulation (default: 10000000)
  --jobs <int>         Concurrent exec.sh processes (default: 3)
  --capacities <csv>   Exact capacities (default: 16384,32768)
  --dbupdate           Force rerun/update even when a result exists
  --no-build           Reuse existing ./main
  --dry-run            Print commands only
  -h, --help           Show this help
EOF
}

die() { echo "[ERROR] $*" >&2; exit 1; }

MAX_PROCESS=10000000
JOBS=3
CAPACITIES="16384,32768"
DBUPDATE=false
NO_BUILD=false
DRY_RUN=false

while (( $# > 0 )); do
  case "$1" in
    --max) [[ -n "${2:-}" ]] || die "--max requires a value"; MAX_PROCESS="$2"; shift 2 ;;
    --jobs) [[ -n "${2:-}" ]] || die "--jobs requires a value"; JOBS="$2"; shift 2 ;;
    --capacities) [[ -n "${2:-}" ]] || die "--capacities requires a value"; CAPACITIES="$2"; shift 2 ;;
    --dbupdate) DBUPDATE=true; shift ;;
    --no-build) NO_BUILD=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$MAX_PROCESS" =~ ^[0-9]+$ ]] || die "--max must be a non-negative integer"
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"
[[ "$CAPACITIES" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "--capacities must be a CSV of integers"

DERIVED=/home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24

TRACE_LABELS=(
  "San Jose -> 2025-09" "San Jose -> 2025-12" "San Jose -> 2026-03"
  "Chicago -> 2025-09" "Chicago -> 2025-12" "Chicago -> 2026-03"
  "NYC -> 2025-09" "NYC -> 2025-12" "NYC -> 2026-03"
)
TRACE_PATHS=(
  "$DERIVED/sanjose/2025-09-27.txt" "$DERIVED/sanjose/2025-12-27.txt" "$DERIVED/sanjose/2026-03-27.txt"
  "$DERIVED/chicago/2025-09-27.txt" "$DERIVED/chicago/2025-12-27.txt" "$DERIVED/chicago/2026-03-27.txt"
  "$DERIVED/nyc/2025-09-27.txt" "$DERIVED/nyc/2025-12-27.txt" "$DERIVED/nyc/2026-03-27.txt"
)
RULE_PATHS=(
  /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule
  /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule
  /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
)

if [[ "$DRY_RUN" != true && "$NO_BUILD" != true ]]; then
  go build main.go
fi

common=(
  --no-build --no-sudo
  --max "$MAX_PROCESS"
  --cachetype UnifiedCache
  --way 8
  --cache-index-types 2,16,18,20,22,24
  --cache-index-policy fixed
  --cache-tag-length 9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24
  --cache-insertion-policy exclusive
  --capacity-values "$CAPACITIES"
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

for i in "${!TRACE_PATHS[@]}"; do
  trace="${TRACE_PATHS[$i]}"
  rule="${RULE_PATHS[$i]}"
  [[ -f "$trace" ]] || die "missing trace: $trace"
  [[ -f "$rule" ]] || die "missing rule: $rule"
  launch ./exec.sh --rulefile "$rule" --trace "$trace" "${common[@]}"
  echo "[QUEUED] ${TRACE_LABELS[$i]}"
done

while (( running > 0 )); do
  if ! wait -n; then failures=$((failures + 1)); fi
  running=$((running - 1))
done

(( failures == 0 )) || die "$failures experiment process(es) failed"
echo "[DONE] anonymous transformed PS capacity sweep through 32K"
