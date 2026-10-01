#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRACE=/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
RULE=/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
MAX_PROCESS=10000000

run_vil() {
  ./exec.sh \
    --rulefile "$RULE" \
    --trace "$TRACE" \
    --cachetype UnifiedCache \
    --way 8 \
    --cache-index-types 2,16,18,20,22,24 \
    --cache-index-policy fixed \
    --cache-tag-length 9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-values 65536,98304,131072 \
    --no-build \
    --no-sudo \
    --max "$MAX_PROCESS" \
    --dbupdate
}

run_mp2_bank() {
  local bank="$1"
  ./exec.sh \
    --rulefile "$RULE" \
    --trace "$TRACE" \
    --cachetype MultiLayerCacheExclusive \
    --cachenum 2 \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length 9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-values "$bank" \
    --refbits-start 16 \
    --refbits-end 24 \
    --refbits-step 1 \
    --no-build \
    --no-sudo \
    --max "$MAX_PROCESS" \
    --dbupdate
}

run_mp3_bank() {
  local bank="$1"
  ./exec.sh \
    --rulefile "$RULE" \
    --trace "$TRACE" \
    --cachetype MultiLayerCacheExclusive \
    --cachenum 3 \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length 9-24,9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-values "$bank" \
    --refbits-start 10 \
    --refbits-end 24 \
    --refbits-step 1 \
    --no-build \
    --no-sudo \
    --max "$MAX_PROCESS" \
    --dbupdate
}

run_vil &
pid_vil=$!

for bank in 32768 49152 65536; do
  run_mp2_bank "$bank"
done

wait "$pid_vil"

for bank in 21840 32768 43688; do
  run_mp3_bank "$bank"
done

echo "[DONE] NYC VIL/MP2/MP3 capacity sweep through about 128K total entries"
