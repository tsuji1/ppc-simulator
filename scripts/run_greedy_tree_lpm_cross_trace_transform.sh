#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/yuzugon
SIM="$ROOT/osada-ppc-simulator"
BINARY="$SIM/bin/fit_trace_tree_lpm"
DERIVED="$ROOT/pcap/derived/greedy-tree-lpm-cross-trace"
REPORTS="$SIM/scripts/reports/greedy-tree-lpm-cross-trace/transforms"
JOBS=${JOBS:-2}

datasets=(jpix-sinet sinet-jpix wide-2025-09 wide-2025-12 wide-2026-03 sanjose chicago nyc)
inputs=(
  "$ROOT/pcap/jpix2sinet90s_5tuple.txt"
  "$ROOT/pcap/sinet2jpix90s_5tuple.txt"
  "$ROOT/pcap/non-anon/2025-09-27.pcap"
  "$ROOT/pcap/non-anon/2025-12-27.pcap"
  "$ROOT/pcap/non-anon/2026-03-27.pcap"
  "$ROOT/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap"
  "$ROOT/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap"
  "$ROOT/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap"
)
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

mkdir -p "$(dirname "$BINARY")" "$DERIVED" "$REPORTS"
cd "$SIM"
go build -o "$BINARY" ./cmd/fit_trace_tree_lpm

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
  dataset=${datasets[$i]}
  for date in "${dates[@]}"; do
    target="$SIM/scripts/reports/global-xor-lpm-tv-exhaustive24/chicago/$date/reference_lpm_distribution.csv"
    [[ -f "$target" ]] || { echo "missing target distribution: $target" >&2; exit 1; }
    for order in "${orders[@]}"; do
      output="$DERIVED/${dataset}-to-${date}-${order}.txt"
      report="$REPORTS/$dataset/$date/$order"
      if [[ -s "$output" && -s "$report/REPORT.md" ]]; then
        echo "[SKIP] $dataset $date $order"
        continue
      fi
      mkdir -p "$report"
      echo "[RUN] $dataset $date $order"
      launch "$BINARY" \
        --rulefile "${rules[$i]}" \
        --target-distribution "$target" \
        --input-trace "${inputs[$i]}" \
        --max 10000000 \
        --fit-depth 24 \
        --sample-size 100000 \
        --hill-candidates 15360 \
        --hill-passes 1 \
        --candidate-order "$order" \
        --full-trace-greedy \
        --output-trace "$output" \
        --output-dir "$report"
    done
  done
done

while (( running > 0 )); do
  if ! wait -n; then failures=$((failures + 1)); fi
  running=$((running - 1))
done
(( failures == 0 )) || { echo "$failures transform(s) failed" >&2; exit 1; }
echo "[DONE] 48 greedy transforms"
