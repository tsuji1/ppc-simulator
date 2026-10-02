#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_mp3_24_21_18_power_compare.sh [--dry-run] [--no-build]

Runs MP 3-cache /24,/21,/18 with equal per-bank capacities
512,1024,2048,4096,8192 entries on San Jose, Chicago, and NYC.
The resulting total physical entry counts are
1536,3072,6144,12288,24576.
EOF
}

DRY_RUN=false
NO_BUILD=false
while (( $# > 0 )); do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --no-build) NO_BUILD=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

TRACE_PATHS=(
  "/home/yuzugon/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap"
  "/home/yuzugon/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap"
  "/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap"
)
RULE_PATHS=(
  "/home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule"
  "/home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule"
  "/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule"
)
CAPACITIES=(512 1024 2048 4096 8192)
CAPACITY_EXPS=(9 10 11 12 13)

if [[ "$DRY_RUN" != true && "$NO_BUILD" != true ]]; then
  /home/yuzugon/go/bin/go build main.go
fi

for i in "${!TRACE_PATHS[@]}"; do
  for j in "${!CAPACITIES[@]}"; do
    capacity="${CAPACITIES[$j]}"
    args=(
      --rulefile "${RULE_PATHS[$i]}"
      --trace "${TRACE_PATHS[$i]}"
      --cachetype MultiLayerCacheExclusive
      --cachenum 3
      --way 8
      --capacity-start "${CAPACITY_EXPS[$j]}"
      --capacity-end "${CAPACITY_EXPS[$j]}"
      --capacity-step 1
      --refbits-start 18
      --refbits-end 24
      --refbits-step 1
      --mp-refbits 24,21,18
      --mp-capacities "$capacity,$capacity,$capacity"
      --max 10000000
      --no-dbupdate
      --no-build
      --no-sudo
    )
    if [[ "$DRY_RUN" == true ]]; then
      args+=(--dry-run)
    fi
    ./exec.sh "${args[@]}"
  done
done
