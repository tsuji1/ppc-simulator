#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/yuzugon
cd "$ROOT/osada-ppc-simulator"
JOBS=${JOBS:-1}
DERIVED="$ROOT/pcap/derived/greedy-tree-lpm-cross-trace"

datasets=(jpix-sinet sinet-jpix wide-2025-09 wide-2025-12 wide-2026-03 sanjose chicago nyc)
rules=(
  "$ROOT/rules/rrc06.bview.20180502.0000.unique.rule"
  "$ROOT/rules/rrc06.bview.20180502.0000.unique.rule"
  "$ROOT/rules/rib.20250927.0600.unique.rule"
  "$ROOT/rules/rib.20251227.0600.unique.rule"
  "$ROOT/rules/rib.20260327.0600.unique.rule"
  "$ROOT/rules/route-views.isc.rib.20140320.1400.unique.rule"
  "$ROOT/rules/route-views.chicago.rib.20160628.1400.unique.rule"
  "$ROOT/rules/rrc11.bview.20190117.1600.unique.rule"
)
dates=(2025-09-27 2025-12-27 2026-03-27)
orders=(top-down bottom-up)
refbits=("24,16" "24,18" "24,18" "24,19" "24,20" "24,20")
capacities=("2048,2048" "1024,1024" "2048,2048" "1024,2048" "2048,2048" "4096,4096")

go build main.go
running=0
failures=0
launch() {
  "$@" &
  running=$((running + 1))
  if (( running >= JOBS )); then
    if ! wait -n; then failures=$((failures + 1)); fi
    running=$((running - 1))
  fi
}

for i in "${!datasets[@]}"; do
  for date in "${dates[@]}"; do
    for order in "${orders[@]}"; do
      trace="$DERIVED/${datasets[$i]}-to-${date}-${order}.txt"
      [[ -s "$trace" ]] || { echo "missing trace: $trace" >&2; exit 1; }
      common=(--rulefile "${rules[$i]}" --trace "$trace" --way 8 --no-build --no-sudo --max 10000000 --no-dbupdate)
      launch ./exec.sh "${common[@]}" \
        --cachetype UnifiedCache \
        --cache-index-types 2,16,18,20,22,24 \
        --cache-index-policy fixed \
        --cache-tag-length 9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24 \
        --cache-insertion-policy exclusive \
        --capacity-start 13 --capacity-end 13 --capacity-step 1
      for j in "${!refbits[@]}"; do
        launch ./exec.sh "${common[@]}" \
          --cachetype MultiLayerCacheExclusive --cachenum 2 \
          --mp-refbits "${refbits[$j]}" --mp-capacities "${capacities[$j]}" \
          --capacity-start 10 --capacity-end 10 --refbits-start 16 --refbits-end 24
      done
      echo "[QUEUED] ${datasets[$i]} $date $order"
    done
  done
done

while (( running > 0 )); do
  if ! wait -n; then failures=$((failures + 1)); fi
  running=$((running - 1))
done
(( failures == 0 )) || { echo "$failures simulation process(es) failed" >&2; exit 1; }
echo "[DONE] greedy capacity-8192 matrix"
