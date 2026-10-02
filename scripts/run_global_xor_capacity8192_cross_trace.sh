#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/run_global_xor_capacity8192_matrix.sh [options]

Run the fixed configurations used by slide 18 against the nine 24-bit global
XOR transformed traces (Chicago, NYC, anon-WIDE x three non-anonymous targets).

Options:
  --only <all|mp|ps>  Limit the cache family (default: all)
  --max <int>         Packets per simulation (default: 10000000)
  --jobs <int>        Concurrent exec.sh processes (default: 2)
  --dry-run           Print commands only
  --dbupdate          Force rerun and DB insertion even when a result exists
  --no-build          Reuse the existing ./main binary
  -h, --help          Show this help
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

ONLY=all
MAX_PROCESS=10000000
JOBS=2
DRY_RUN=false
DBUPDATE=false
NO_BUILD=false

while (( $# > 0 )); do
  case "$1" in
    --only) [[ -n "${2:-}" ]] || die "--only requires a value"; ONLY="$2"; shift 2 ;;
    --max) [[ -n "${2:-}" ]] || die "--max requires a value"; MAX_PROCESS="$2"; shift 2 ;;
    --jobs) [[ -n "${2:-}" ]] || die "--jobs requires a value"; JOBS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --dbupdate) DBUPDATE=true; shift ;;
    --no-build) NO_BUILD=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

case "$ONLY" in all|mp|ps) ;; *) die "--only must be all, mp, or ps" ;; esac
[[ "$MAX_PROCESS" =~ ^[0-9]+$ ]] || die "--max must be a non-negative integer"
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"

DERIVED=/home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24

TRACE_LABELS=(
  "Original JPIX-SINET" "Original SINET-JPIX" "Original WIDE 2025-09" "Original WIDE 2025-12" "Original WIDE 2026-03" "Original San Jose" "Original Chicago" "Original New York"
  "Target 2025-09 JPIX-SINET" "Target 2025-09 SINET-JPIX" "Target 2025-09 WIDE 2025-09" "Target 2025-09 WIDE 2025-12" "Target 2025-09 WIDE 2026-03" "Target 2025-09 San Jose" "Target 2025-09 Chicago" "Target 2025-09 New York"
  "Target 2025-12 JPIX-SINET" "Target 2025-12 SINET-JPIX" "Target 2025-12 WIDE 2025-09" "Target 2025-12 WIDE 2025-12" "Target 2025-12 WIDE 2026-03" "Target 2025-12 San Jose" "Target 2025-12 Chicago" "Target 2025-12 New York"
  "Target 2026-03 JPIX-SINET" "Target 2026-03 SINET-JPIX" "Target 2026-03 WIDE 2025-09" "Target 2026-03 WIDE 2025-12" "Target 2026-03 WIDE 2026-03" "Target 2026-03 San Jose" "Target 2026-03 Chicago" "Target 2026-03 New York"
)
TRACE_PATHS=(
  /home/yuzugon/pcap/jpix2sinet90s_5tuple.txt /home/yuzugon/pcap/sinet2jpix90s_5tuple.txt /home/yuzugon/pcap/non-anon/2025-09-27.pcap /home/yuzugon/pcap/non-anon/2025-12-27.pcap /home/yuzugon/pcap/non-anon/2026-03-27.pcap /home/yuzugon/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap /home/yuzugon/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap /home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
  /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/jpix-sinet/jpix-sinet-2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/sinet-jpix/sinet-jpix-2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2025-09/wide-2025-09-to-2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2025-12/wide-2025-12-to-2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2026-03/wide-2026-03-to-2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/sanjose/2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/chicago/2025-09-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/nyc/2025-09-27.txt
  /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/jpix-sinet/jpix-sinet-2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/sinet-jpix/sinet-jpix-2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2025-09/wide-2025-09-to-2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2025-12/wide-2025-12-to-2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2026-03/wide-2026-03-to-2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/sanjose/2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/chicago/2025-12-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/nyc/2025-12-27.txt
  /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/jpix-sinet/jpix-sinet-2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/sinet-jpix/sinet-jpix-2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2025-09/wide-2025-09-to-2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2025-12/wide-2025-12-to-2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/wide-2026-03/wide-2026-03-to-2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/sanjose/2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/chicago/2026-03-27.txt /home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24/nyc/2026-03-27.txt
)
RULE_PATHS=(
  /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rib.20250927.0600.unique.rule /home/yuzugon/rules/rib.20251227.0600.unique.rule /home/yuzugon/rules/rib.20260327.0600.unique.rule /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rib.20250927.0600.unique.rule /home/yuzugon/rules/rib.20251227.0600.unique.rule /home/yuzugon/rules/rib.20260327.0600.unique.rule /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rib.20250927.0600.unique.rule /home/yuzugon/rules/rib.20251227.0600.unique.rule /home/yuzugon/rules/rib.20260327.0600.unique.rule /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
  /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule /home/yuzugon/rules/rib.20250927.0600.unique.rule /home/yuzugon/rules/rib.20251227.0600.unique.rule /home/yuzugon/rules/rib.20260327.0600.unique.rule /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
)

MP_LABELS=(
  "MP 24-16-2048-2048"
  "MP 24-18-1024-1024"
  "MP 24-18-2048-2048"
  "MP 24-19-1024-2048"
  "MP 24-20-2048-2048"
  "MP 24-20-4096-4096"
)
MP_REFBITS=("24,16" "24,18" "24,18" "24,19" "24,20" "24,20")
MP_CAPACITIES=("2048,2048" "1024,1024" "2048,2048" "1024,2048" "2048,2048" "4096,4096")

common=(--no-build --no-sudo --max "$MAX_PROCESS")
if [[ "$DBUPDATE" == true ]]; then common+=(--dbupdate); else common+=(--no-dbupdate); fi
if [[ "$DRY_RUN" == true ]]; then common+=(--dry-run); fi

if [[ "$DRY_RUN" != true && "$NO_BUILD" != true ]]; then
  go build main.go
fi

running=0
failures=0

launch() {
  echo "==> $*"
  if [[ "$DRY_RUN" == true ]]; then
    "$@"
    return
  fi
  (
    "$@"
  ) &
  running=$((running + 1))
  if (( running >= JOBS )); then
    if ! wait -n; then failures=$((failures + 1)); fi
    running=$((running - 1))
  fi
}

for i in "${!TRACE_PATHS[@]}"; do
  trace="${TRACE_PATHS[$i]}"
  rule="${RULE_PATHS[$i]}"
  [[ -f "$trace" ]] || die "missing transformed trace: $trace"
  [[ -f "$rule" ]] || die "missing rule: $rule"

  if [[ "$ONLY" == all || "$ONLY" == ps ]]; then
    launch ./exec.sh \
      --rulefile "$rule" \
      --trace "$trace" \
      --cachetype UnifiedCache \
      --way 8 \
      --cache-index-types 2,16,18,20,22,24 \
      --cache-index-policy fixed \
      --cache-tag-length 9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24 \
      --cache-insertion-policy exclusive \
      --capacity-start 13 \
      --capacity-end 13 \
      --capacity-step 1 \
      "${common[@]}"
  fi

  if [[ "$ONLY" == all || "$ONLY" == mp ]]; then
    for j in "${!MP_LABELS[@]}"; do
      launch ./exec.sh \
        --rulefile "$rule" \
        --trace "$trace" \
        --cachetype MultiLayerCacheExclusive \
        --cachenum 2 \
        --way 8 \
        --mp-refbits "${MP_REFBITS[$j]}" \
        --mp-capacities "${MP_CAPACITIES[$j]}" \
        --capacity-start 10 \
        --capacity-end 10 \
        --refbits-start 16 \
        --refbits-end 24 \
        "${common[@]}"
    done
  fi

  echo "[QUEUED] ${TRACE_LABELS[$i]}"
done

while (( running > 0 )); do
  if ! wait -n; then failures=$((failures + 1)); fi
  running=$((running - 1))
done

if (( failures > 0 )); then
  die "$failures experiment process(es) failed"
fi

echo "[DONE] global XOR capacity-8192 matrix"
