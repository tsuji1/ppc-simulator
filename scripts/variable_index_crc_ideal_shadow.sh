#!/usr/bin/env bash
# 理想的な動的選択：L=1〜32 の全候補を、全 set・全 tag の shadow で 1M packet ごとに数え、
# いちばんヒットの多い L に次の epoch から切り替える（閾値 0、切替時は flush しない）。CRC index の VPC。
# 比較用に固定 L（/9〜/32）の全通りと、事前計算（先頭 1M で選ぶ、学習中は /18）も出す。
# 使い方: scripts/variable_index_crc_ideal_shadow.sh OUT_DIR TRACE_NAME=PATH ...
set -euo pipefail

out=${1:?OUT_DIR}
shift
mkdir -p "$out"
bin="$out/explore"
go build -o "$bin" ./cmd/variable_index_explore

caps=1024,2048,4096,8192,16384
common=(-index crc -capacity "$caps" -way 8 -max 10000000 -out "$out" -jobs 16)

for spec in "$@"; do
  name=${spec%%=*}
  path=${spec#*=}
  "$bin" "${common[@]}" -mode static -lmax 32 -trace "$path" -name "$name"
  "$bin" "${common[@]}" -mode static-switch -train-packets 1000000 -initial 18 -trace "$path" -name "$name"
  # 理想の shadow：全候補・全 set（sample-div 1）・全 tag（tag-bits 0）、epoch 1M、閾値 0
  "$bin" "${common[@]}" -mode shadow -cands 1-32 -sample-mode set -sample-div 1 -tag-bits 0 \
    -epoch 1000000 -threshold 0 -switch keep -initial 18 -series-window 1000000 \
    -tag _ideal -trace "$path" -name "$name"
done
rm -f "$bin"
