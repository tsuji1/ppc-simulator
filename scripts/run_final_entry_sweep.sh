#!/usr/bin/env bash
# 最終発表用: 総 entry 数ごとの MPLC /24+/18・VPLC（direct L=8..24）・VPLC ideal のミス率（#124）。
#
# 使い方: run_final_entry_sweep.sh TRACE_LIST FLOWBENCH_DIR FB_RULE_FILE OUT_DIR [JOBS]
#   TRACE_LIST     実 trace の一覧（TSV: label <TAB> trace path <TAB> rule path。# で始まる行は無視）
#   FLOWBENCH_DIR  Flow-Bench の fork（tsuji1/Flow-Bench の routing-fib）の checkout
#   FB_RULE_FILE   FlowBench の trace を作る元の rule file（WIDE）
#   OUT_DIR        出力先。hitrate/<slug>_<容量>.csv、logs/、traces/ を作る
#   JOBS           同時に動かす windowed_hitrate の数（既定 12）
# 環境変数:
#   CAPACITIES  総 entry 数（空白区切り、既定 256〜65536 の 2 倍刻み）
#   FB_SEEDS    FlowBench の seed（既定 "1 2 3"。空にすると FlowBench を作らない）
#   FB_RD       FlowBench の -rd（既定 "0.70 1"）
#   FB_FD       FlowBench の -fd（既定 "1 1"）
#   PACKETS     1 trace で使う packet 数（既定 10000000）
#   GO          go のパス（PATH にないとき）
# MPLC は各層に半分ずつ（/24 と /18）。VPLC は先頭 1M の window と全体の両方の hit を出し、
# L の選択は集計側（research-routing-table-cache の scripts/summarize_final_entry_sweep.py）で行う。
set -euo pipefail

trace_list=$(realpath "$1")
flowbench_dir=$(realpath "$2")
fb_rule=$(realpath "$3")
out_dir=$4
jobs=${5:-12}
capacities=${CAPACITIES:-"256 512 1024 2048 4096 8192 16384 32768 65536"}
fb_seeds=${FB_SEEDS-"1 2 3"}
fb_rd=${FB_RD:-"0.70 1"}
fb_fd=${FB_FD:-"1 1"}
packets=${PACKETS:-10000000}
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(cd "$script_dir/.." && pwd)
fib_flowbench=$repo_dir/third_party/fib-flowbench
if [[ ! -f $fib_flowbench/src/fib_flowbench/cli.py ]]; then
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
  echo "fib-flowbench $(git -C "$fib_flowbench" rev-parse HEAD)"
  echo "simulator $(git -C "$repo_dir" rev-parse HEAD)"
  echo "capacities $capacities"
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

# VPLC: ideal（2）と direct prefix index L=8..24（100+L）
ps_types=2,$(seq -s, 108 124)

one() {
  local label=$1 trace=$2 rule=$3 cap=$4
  local half=$((cap / 2))
  local slug
  slug=$(printf '%s' "$label" | tr -c 'A-Za-z0-9.-' '_')
  "$tmp/bin/windowed_hitrate" -rulefile "$rule" -trace "$trace" -max "$packets" \
    -windows 1000000,"$packets" -progress-interval 0 -way 8 \
    -mp-capacities "$half,$half" -mp-refbits 24,18 -ps-capacity "$cap" -ps-index-types "$ps_types" \
    -output-dir "$out_dir/hitrate" -output-csv "$out_dir/hitrate/${slug}_$cap.csv" \
    > "$out_dir/logs/${slug}_$cap.log" 2>&1
  # 集計で trace の表示名に使う（同時に書くので 1 行ずつ追記する）
  printf '%s\t%s\t%s\n' "${slug}_$cap.csv" "$label" "$cap" >> "$out_dir/hitrate/labels.tsv"
  echo "done $label $cap"
}
export -f one
export tmp out_dir packets ps_types

: > "$out_dir/hitrate/labels.tsv"
while IFS=$'\t' read -r label trace rule; do
  for cap in $capacities; do
    printf '%s\0%s\0%s\0%s\0' "$label" "$trace" "$rule" "$cap"
  done
done < "$jobs_file" | xargs -0 -n 4 -P "$jobs" bash -c 'one "$@"' _
