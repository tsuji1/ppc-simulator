#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TRACE=/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
RULE=/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
MAX_PROCESS=10000000

run_mp2_40k() {
  ./exec.sh \
    --rulefile "$RULE" \
    --trace "$TRACE" \
    --cachetype MultiLayerCacheExclusive \
    --cachenum 2 \
    --way 8 \
    --cache-index-type 5 \
    --cache-tag-length 9-24,9-24 \
    --cache-insertion-policy exclusive \
    --capacity-values 20000 \
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

run_mp2_40k &
pid_mp2=$!
run_mp3_bank 11000 &
pid_mp3_33k=$!
run_mp3_bank 12000 &
pid_mp3_36k=$!
run_mp3_bank 13000 &
pid_mp3_39k=$!

wait "$pid_mp2"
wait "$pid_mp3_33k"
wait "$pid_mp3_36k"
wait "$pid_mp3_39k"

echo "[DONE] NYC MP optimal extension: MP2 40K, MP3 33K/36K/39K"
