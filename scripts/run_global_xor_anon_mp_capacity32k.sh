#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MAX_PROCESS=10000000
JOBS=3
DRY_RUN=false
NO_BUILD=false

usage() {
  cat <<'EOF'
Usage: scripts/run_global_xor_anon_mp_capacity32k.sh [options]

Runs the anonymous/or LPM-distribution-matched traces with:
  MP 2-cache: /24,/18, equal banks 512..16384 entries
  MP 3-cache: /24,/21,/18, equal banks 512..8192 entries

The total physical capacities are 1K..32K for MP2 and 1.5K..24K for MP3.

Options:
  --max <N>       Packet limit (default: 10000000)
  --jobs <N>      Parallel traces (default: 3)
  --no-build      Reuse ./main
  --dry-run       Print commands only
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --max) MAX_PROCESS="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --no-build) NO_BUILD=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$MAX_PROCESS" =~ ^[0-9]+$ ]] || { echo "--max must be an integer" >&2; exit 2; }
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo "--jobs must be positive" >&2; exit 2; }

DERIVED=/home/yuzugon/pcap/derived/global-xor-lpm-tv-exhaustive24
TRACE_PATHS=(
  /home/yuzugon/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap
  /home/yuzugon/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap
  /home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
  "$DERIVED/sanjose/2025-09-27.txt" "$DERIVED/sanjose/2025-12-27.txt" "$DERIVED/sanjose/2026-03-27.txt"
  "$DERIVED/chicago/2025-09-27.txt" "$DERIVED/chicago/2025-12-27.txt" "$DERIVED/chicago/2026-03-27.txt"
  "$DERIVED/nyc/2025-09-27.txt" "$DERIVED/nyc/2025-12-27.txt" "$DERIVED/nyc/2026-03-27.txt"
)
RULE_PATHS=(
  /home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule
  /home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
  /home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
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
  if command -v go >/dev/null 2>&1; then
    go build main.go
  elif [[ ! -x ./main ]]; then
    echo "go is unavailable and ./main is missing" >&2
    exit 1
  fi
fi

run_trace() {
  local trace="$1" rule="$2" bank
  for bank in 512 1024 2048 4096 8192 16384; do
    args=(
      --rulefile "$rule" --trace "$trace" --no-build --no-sudo
      --max "$MAX_PROCESS" --cachetype MultiLayerCacheExclusive --cachenum 2 --way 8
      --mp-refbits 24,18 --mp-capacities "$bank,$bank"
      --capacity-values "$bank" --refbits-start 18 --refbits-end 24 --refbits-step 1
      --no-dbupdate
    )
    [[ "$DRY_RUN" == true ]] && args+=(--dry-run)
    ./exec.sh "${args[@]}"
  done
  for bank in 512 1024 2048 4096 8192; do
    args=(
      --rulefile "$rule" --trace "$trace" --no-build --no-sudo
      --max "$MAX_PROCESS" --cachetype MultiLayerCacheExclusive --cachenum 3 --way 8
      --mp-refbits 24,21,18 --mp-capacities "$bank,$bank,$bank"
      --capacity-values "$bank" --refbits-start 18 --refbits-end 24 --refbits-step 1
      --no-dbupdate
    )
    [[ "$DRY_RUN" == true ]] && args+=(--dry-run)
    ./exec.sh "${args[@]}"
  done
}

active=0
for i in "${!TRACE_PATHS[@]}"; do
  run_trace "${TRACE_PATHS[$i]}" "${RULE_PATHS[$i]}" &
  ((active += 1))
  if (( active >= JOBS )); then
    wait -n
    ((active -= 1))
  fi
done
wait

echo "[DONE] MP2/MP3 anonymous capacity sweep"
