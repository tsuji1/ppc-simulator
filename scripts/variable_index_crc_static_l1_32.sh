#!/usr/bin/env bash
# CRC index の VPLC で、固定 L を /1〜/32 の全通りで回す（8-way、5 容量、先頭 10M）。
# variable_index_crc_epoch.sh の static と同じ条件で、L の範囲だけを広げたもの。
# 使い方: scripts/variable_index_crc_static_l1_32.sh OUT_DIR TRACE_NAME=PATH ...
set -euo pipefail

out=${1:?OUT_DIR}
shift
mkdir -p "$out"
bin="$out/explore"
go build -o "$bin" ./cmd/variable_index_explore

common=(-index crc -capacity 1024,2048,4096,8192,16384 -way 8 -max 10000000 -out "$out" -jobs 20 -lmin 1 -lmax 32)

for spec in "$@"; do
  name=${spec%%=*}
  path=${spec#*=}
  "$bin" "${common[@]}" -mode static -trace "$path" -name "$name"
done
rm -f "$bin"
