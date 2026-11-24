#!/usr/bin/env bash
# CRC index の VPLC で、shadow による L の選び直し間隔（epoch）を 10k / 100k / 1M に変えて比べる。
# 切替時は flush しない（keep）。比較用に固定 L の全通り（CRC）と事前計算（先頭 1M、学習中は /18）も出す。
# 使い方: scripts/variable_index_crc_epoch.sh OUT_DIR TRACE_NAME=PATH ...
set -euo pipefail

out=${1:?OUT_DIR}
shift
mkdir -p "$out"
bin="$out/explore"
go build -o "$bin" ./cmd/variable_index_explore

caps=1024,2048,4096,8192,16384
epochs=10000,100000,1000000
common=(-index crc -capacity "$caps" -way 8 -max 10000000 -out "$out" -jobs 20)

for spec in "$@"; do
  name=${spec%%=*}
  path=${spec#*=}
  # 固定 L（/9〜/24）と ideal
  "$bin" "${common[@]}" -mode static -trace "$path" -name "$name"
  # 事前計算：先頭 1M で選んで切り替え（学習中は /18）
  "$bin" "${common[@]}" -mode static-switch -train-packets 1000000 -initial 18 -trace "$path" -name "$name"
  # shadow(traffic サンプリング 1/8、16 候補)
  "$bin" "${common[@]}" -mode shadow -cands 9-24 -sample-mode traffic -sample-div 8 \
    -epoch "$epochs" -threshold 0.002,0.01 -switch keep -tag _traffic -trace "$path" -name "$name"
  # 近傍±2+rover（全 set の shadow、部分 tag 12bit）
  "$bin" "${common[@]}" -mode shadow -cands 9-24 -neighbor 2 -rover true -sample-mode set -sample-div 1 \
    -epoch "$epochs" -threshold 0.002,0.01 -tag-bits 12 -switch keep -tag _rover -trace "$path" -name "$name"
done
rm -f "$bin"
