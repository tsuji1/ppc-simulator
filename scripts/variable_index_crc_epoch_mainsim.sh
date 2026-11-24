#!/usr/bin/env bash
# variable_index_crc_epoch.sh の事前計算（先頭 1M で選んだ L）を、本体シミュレータ（windowed_hitrate）の
# VPLC CRC index（CacheIndexType=L、8-way、tag 9-24）で回し、電力の計算に使う StatDetail（DepthSum、挿入できないミス）を JSON に出す。
# 使い方: scripts/variable_index_crc_epoch_mainsim.sh SUMMARY_CSV OUT_DIR NAME=TRACE=RULE ... [JOBS 環境変数、既定 6]
#   SUMMARY_CSV  summarize_variable_index_crc_epoch.py の出力（trace,capacity,...,train1M_note=/L）
set -euo pipefail

summary=$(realpath "$1")
out=$2
shift 2
jobs=${JOBS:-6}
mkdir -p "$out"/{hitrate,results,logs}
out=$(cd "$out" && pwd)
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
bin=$out/windowed_hitrate
(cd "$repo_dir" && go build -o "$bin" ./cmd/windowed_hitrate)
tag_length=$(printf "9-24,%.0s" $(seq 8)); tag_length=${tag_length%,}
git -C "$repo_dir" rev-parse HEAD > "$out/versions.txt"

declare -A trace_of rule_of
for spec in "$@"; do
  IFS='=' read -r name trace rule <<< "$spec"
  trace_of[$name]=$trace
  rule_of[$name]=$rule
done

# trace,capacity,L の一覧（train1M_note は "/L"）
col=$(head -1 "$summary" | tr ',' '\n' | grep -nx 'train1M_note' | cut -d: -f1)
tail -n +2 "$summary" | cut -d, -f1,2,"$col" | tr -d '/' > "$out/jobs.csv"

: > "$out/hitrate/labels.tsv"
while IFS=, read -r name cap l; do
  t=${trace_of[$name]:?"trace が無い: $name"}
  r=${rule_of[$name]}
  printf '%s\0%s\0%s\0%s\0%s\0' "$name" "$cap" "$l" "$t" "$r"
done < "$out/jobs.csv" | xargs -0 -n 5 -P "$jobs" sh -c '
  name=$1 cap=$2 l=$3 t=$4 r=$5
  "$0" -rulefile "$r" -trace "$t" -max 10000000 -windows 10000000 -progress-interval 0 -way 8 \
    -cache-tag-length "'"$tag_length"'" -mp-configs none -ps-capacity "$cap" -ps-index-types "$l" \
    -output-dir "'"$out"'/hitrate" -output-csv "'"$out"'/hitrate/${name}_${cap}.csv" \
    -result-json "'"$out"'/results/${name}_${cap}.json" > "'"$out"'/logs/${name}_${cap}.log" 2>&1
  printf "%s\t%s\t%s\t%s\n" "$name" "$cap" "$l" "${name}_${cap}" >> "'"$out"'/hitrate/labels.tsv"
  echo "done $name $cap /$l"
' "$bin"
rm -f "$bin"
