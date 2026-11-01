#!/usr/bin/env bash
# issue #123：VPLC の set index を direct / XOR 畳み込み / CRC（参考）で比べる。
# 11 trace の全長について、explore の static-train（先頭 1M packet で L を選び、残りで評価）を
# 容量 1K〜16K、8-way・16-way、L = /9〜/32 で回す。
#
# 使い方（banana）:
#   researchctl run --issue 123 -- bash scripts/run_issue123_xor_index.sh GOB_DIR CAIDA_DIR OUT_DIR
#   GOB_DIR   : gob-packet（WIDE 非匿名・Chicago・San Jose・NYC・JPIX・SINET の gob）
#   CAIDA_DIR : caida100g/gob（60 秒の .mpk）
#   OUT_DIR   : CSV の出力先
# 環境変数 JOBS（既定 16）、MAXPKT（既定 0 = 全長）。
set -euo pipefail

gob_dir=${1:?GOB_DIR}
caida_dir=${2:?CAIDA_DIR}
out_dir=${3:?OUT_DIR}
jobs=${JOBS:-16}
maxpkt=${MAXPKT:-0}

repo=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$out_dir"
bin="$out_dir/variable_index_explore"
(cd "$repo" && go build -o "$bin" ./cmd/variable_index_explore)

traces=(
  "wide0927=$gob_dir/rib-20250927-0600-unique_2025-09-27.gob"
  "wide1227=$gob_dir/rib-20251227-0600-unique_2025-12-27.gob"
  "wide0327=$gob_dir/rib-20260327-0600-unique_2026-03-27.gob"
  "chicago=$gob_dir/route-views-chicago-rib-20160628-1400-unique_equinix-chicago-dirB-20140320-140100-UTC-anon.gob"
  "sanjose=$gob_dir/route-views-isc-rib-20140320-1400-unique_equinix-sanjose-dirA-20140320-132400-UTC-anon.gob"
  "nyc=$gob_dir/rrc11-bview-20190117-1600-unique_equinix-nyc-dirB-20190117-135900-UTC-anon.gob"
  "jpix=$gob_dir/rrc06-bview-20180502-0000-unique_jpix2sinet90s_5tuple.gob"
  "sinet=$gob_dir/rrc06-bview-20180502-0000-unique_sinet2jpix90s_5tuple.gob"
  "caida0320a=$caida_dir/route-views-isc-rib-20250320-1400-unique_20250320-130000-dira-anon-first60s.mpk"
  "caida0320b=$caida_dir/route-views-isc-rib-20250320-1400-unique_20250320-130000-dirb-anon-first60s.mpk"
  "caida1120a=$caida_dir/route-views-isc-rib-20251120-1400-unique_20251120-130000-dira-anon-first60s.mpk"
)

for spec in "${traces[@]}"; do
  name=${spec%%=*}
  path=${spec#*=}
  echo "[$(date +%T)] $name $path" >&2
  "$bin" -trace "$path" -name "$name" -max "$maxpkt" -mode static-train \
    -index direct,xor,crc -way 8,16 -capacity 1024,2048,4096,8192,16384 \
    -lmax 32 -train-packets 1000000 -eval-start 1000000 \
    -jobs "$jobs" -out "$out_dir"
done
rm -f "$bin"
echo "[$(date +%T)] done" >&2
