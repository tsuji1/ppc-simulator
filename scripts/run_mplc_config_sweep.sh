#!/usr/bin/env bash
# MPLC（Multiple Prefix Length Cache）の構成を総 entry 数ごとに掃引し、最適構成を探す（#113、#124）。
# 2 層 /24 + /n で、n と /24 層への容量配分を変える。1 つの trace を 1 回読む間に、同じ総 entry 数・同じ index の全構成を回す。
#
# 使い方: run_mplc_config_sweep.sh TRACE_LIST FLOWBENCH_DIR FB_RULE_FILE OUT_DIR [JOBS]
#   TRACE_LIST     実 trace の一覧（TSV: label <TAB> trace path <TAB> rule path。# で始まる行は無視）
#   FLOWBENCH_DIR  Flow-Bench の fork（tsuji1/Flow-Bench の routing-fib）の checkout
#   FB_RULE_FILE   FlowBench の trace を作る元の rule file（WIDE）
#   OUT_DIR        出力先。hitrate/<slug>_<容量>_<index>.csv、logs/、traces/ を作る
#   JOBS           同時に動かす windowed_hitrate の数（既定 8）
# 環境変数:
#   CAPACITIES  総 entry 数（空白区切り、既定 256〜65536 の 2 倍刻み）
#   NS          /n 層の n（空白区切り、既定 8〜23）
#   SHARES      /24 層に割り当てる割合の分子（分母 SHARE_DEN、既定 "1 2 3 4 5 6 7" / 8）
#   SHARE_DEN   割合の分母（既定 8）
#   MP_INDEXES  MP の set index（空白区切り、既定 "crc direct"）
#   FB_SEEDS    FlowBench の seed（既定 "1 2 3"。空にすると FlowBench を作らない）
#   FB_RD       FlowBench の -rd（既定 "0.70 1"）
#   FB_FD       FlowBench の -fd（既定 "1 1"）
#   PACKETS     1 trace で使う packet 数（既定 10000000）
#   GO          go のパス（PATH にないとき）
# 各構成について先頭 1M の window と全体（PACKETS）の hit を出す。/24 層だけの 1 層構成（24:総 entry 数）も比較用に入れる。
# 最適構成の選択は集計側（research-routing-table-cache の scripts/summarize_mplc_config_sweep.py）で行う。
set -euo pipefail

trace_list=$(realpath "$1")
flowbench_dir=$(realpath "$2")
fb_rule=$(realpath "$3")
out_dir=$4
jobs=${5:-8}
capacities=${CAPACITIES:-"256 512 1024 2048 4096 8192 16384 32768 65536"}
ns=${NS:-"$(seq -s ' ' 8 23)"}
shares=${SHARES:-"1 2 3 4 5 6 7"}
share_den=${SHARE_DEN:-8}
mp_indexes=${MP_INDEXES:-"crc direct"}
fb_seeds=${FB_SEEDS-"1 2 3"}
fb_rd=${FB_RD:-"0.70 1"}
fb_fd=${FB_FD:-"1 1"}
packets=${PACKETS:-10000000}
way=8
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(cd "$script_dir/.." && pwd)
fib_flowbench=$repo_dir/third_party/fib-flowbench
if [[ -n $fb_seeds && ! -f $fib_flowbench/src/fib_flowbench/cli.py ]]; then
  echo "fib-flowbench がない。git submodule update --init third_party/fib-flowbench を実行する" >&2
  exit 1
fi

mkdir -p "$out_dir"/{hitrate,logs,traces}
out_dir=$(cd "$out_dir" && pwd)
# FlowBench の trace は大きいので一時 directory に置き、終わったら消す（同じ条件で再生成できる。sha256 は残す）
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

{
  echo "flowbench $(git -C "$flowbench_dir" rev-parse HEAD)"
  git -C "$flowbench_dir" status --short --untracked-files=no
  echo "fib-flowbench $(git -C "$fib_flowbench" rev-parse HEAD 2>/dev/null || echo none)"
  echo "simulator $(git -C "$repo_dir" rev-parse HEAD)"
  echo "capacities $capacities"
  echo "ns $ns"
  echo "shares $shares / $share_den"
  echo "mp_indexes $mp_indexes"
  echo "way $way"
  echo "packets $packets"
  echo "flowbench -rd $fb_rd -fd $fb_fd seeds $fb_seeds"
} > "$out_dir/versions.txt"

mkdir -p "$tmp/bin"
(cd "$repo_dir" && "${GO:-go}" build -o "$tmp/bin/windowed_hitrate" ./cmd/windowed_hitrate)

# 実 trace と FlowBench の trace を (label, trace, rule) の一覧にまとめる
jobs_file=$out_dir/traces/list.tsv
grep -v '^#' "$trace_list" | awk -F'\t' 'NF >= 3' > "$jobs_file"

if [[ -n $fb_seeds ]]; then
  (cd "$flowbench_dir/source" && g++ -std=c++17 -O2 trace_generator.cpp -o "$tmp/flowbench-trace")
  PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli isolate --rule-file "$fb_rule" --output "$tmp/rules.fb"
  cp "$tmp/rules.fb.meta.json" "$out_dir/traces/rules.fb.meta.json"
  read -r rd_a rd_b <<< "$fb_rd"
  read -r fd_a fd_b <<< "$fb_fd"
  : > "$out_dir/traces/flowbench_sha256.tsv"
  for seed in $fb_seeds; do
    label="FlowBench rd${rd_a}-${rd_b} fd${fd_a}-${fd_b} s${seed}"
    file=$tmp/fb_s$seed
    (cd "$tmp" && ./flowbench-trace -i rules.fb --isolated -f 1 -fw 32 -ft LPM -n "$packets" \
      -rd "$rd_a" "$rd_b" -fd "$fd_a" "$fd_b" -s "$seed" -o "$file.fbtrace" > "$out_dir/logs/fb_s$seed.gen.log" 2>&1)
    PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli to-sim \
      --trace "$file.fbtrace" --output "$file.txt" >> "$out_dir/logs/fb_s$seed.gen.log" 2>&1
    rm -f "$file.fbtrace"
    sha256sum "$file.txt" | awk -v l="$label" '{print l "\t" $1}' >> "$out_dir/traces/flowbench_sha256.tsv"
    printf '%s\t%s\t%s\n' "$label" "$file.txt" "$fb_rule" >> "$jobs_file"
  done
fi

# 総 entry 数ごとの MP 構成の一覧（-mp-configs の書式）。容量が way の倍数にならない配分は飛ばす
configs_file=$out_dir/traces/mp_configs.tsv
: > "$configs_file"
for cap in $capacities; do
  list="24:$cap"
  for n in $ns; do
    for s in $shares; do
      c24=$((cap * s / share_den))
      cn=$((cap - c24))
      if (( c24 * share_den != cap * s || c24 % way != 0 || cn % way != 0 || cn <= 0 )); then
        echo "skip cap=$cap n=$n share=$s/$share_den" >&2
        continue
      fi
      list+=";24:$c24,$n:$cn"
    done
  done
  printf '%s\t%s\n' "$cap" "$list" >> "$configs_file"
done

one() {
  local label=$1 trace=$2 rule=$3 cap=$4 index=$5
  local slug list
  slug=$(printf '%s' "$label" | tr -c 'A-Za-z0-9.-' '_')
  list=$(awk -F'\t' -v c="$cap" '$1 == c {print $2}' "$configs_file")
  "$tmp/bin/windowed_hitrate" -rulefile "$rule" -trace "$trace" -max "$packets" \
    -windows 1000000,"$packets" -progress-interval 0 -way "$way" \
    -mp-configs "$list" -mp-index "$index" -ps-index-types none \
    -output-dir "$out_dir/hitrate" -output-csv "$out_dir/hitrate/${slug}_${cap}_$index.csv" \
    > "$out_dir/logs/${slug}_${cap}_$index.log" 2>&1
  # 集計で trace の表示名に使う（同時に書くので 1 行ずつ追記する）
  printf '%s\t%s\t%s\t%s\n' "${slug}_${cap}_$index.csv" "$label" "$cap" "$index" >> "$out_dir/hitrate/labels.tsv"
  echo "done $label $cap $index $(date -Iseconds)"
}
export -f one
export tmp out_dir packets way configs_file

: > "$out_dir/hitrate/labels.tsv"
# 大きい容量（時間・メモリが大きい）から先に流す
caps_desc=$(printf '%s\n' $capacities | sort -rn)
for cap in $caps_desc; do
  while IFS=$'\t' read -r label trace rule; do
    for index in $mp_indexes; do
      printf '%s\0%s\0%s\0%s\0%s\0' "$label" "$trace" "$rule" "$cap" "$index"
    done
  done < "$jobs_file"
done | xargs -0 -n 5 -P "$jobs" bash -c 'one "$@"' _
