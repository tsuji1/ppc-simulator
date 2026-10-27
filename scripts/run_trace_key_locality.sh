#!/usr/bin/env bash
# MP と LTPC の hit rate の差の原因を見るため、trace を cache の key に直した特徴量
# （analyze_cache_key_locality）を、FlowBench の rd・fd 掃引の trace と実 trace で出す（#117）。
# 実 trace は windowed_hitrate の hit rate も測る（FlowBench の hit rate は run_flowbench_rd_fd_sweep.sh で測った）。
#
# 使い方: run_trace_key_locality.sh FLOWBENCH_DIR FB_RULE_FILE OUT_DIR JOBS REAL...
#   FLOWBENCH_DIR  Flow-Bench の fork（tsuji1/Flow-Bench の routing-fib）の checkout
#   FB_RULE_FILE   FlowBench の rule set を作る元の rule file
#   OUT_DIR        出力先。features/<label>.csv、hitrate/<label>.csv、logs/ を作る
#   JOBS           同時に処理する trace の数
#   REAL           実 trace を「label=trace=rule file」で並べる
# FlowBench の条件は run_flowbench_rd_fd_sweep.sh と同じで、環境変数 RD_AS・FD_AS・SEEDS で変えられる。
# go が PATH にないときは GO に go のパスを渡す。
set -euo pipefail

flowbench_dir=$1
fb_rule_file=$(realpath "$2")
out_dir=$3
jobs=$4
shift 4
rd_as=${RD_AS:-"0.70 0.75 0.80"}
fd_as=${FD_AS:-"0.70 0.75 0.80 1"}
seeds=${SEEDS:-"1 2 3 4 5"}
packets=10000000
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(cd "$script_dir/.." && pwd)
fib_flowbench=$repo_dir/third_party/fib-flowbench
if [[ ! -f $fib_flowbench/src/fib_flowbench/cli.py ]]; then
  echo "fib-flowbench がない。git submodule update --init third_party/fib-flowbench を実行する" >&2
  exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$out_dir"/{features,hitrate,logs}
out_dir=$(cd "$out_dir" && pwd)

{
  echo "flowbench $(git -C "$flowbench_dir" rev-parse HEAD)"
  git -C "$flowbench_dir" status --short --untracked-files=no
  echo "fib-flowbench $(git -C "$fib_flowbench" rev-parse HEAD)"
  echo "simulator $(git -C "$repo_dir" rev-parse HEAD)"
} > "$out_dir/versions.txt"

(cd "$flowbench_dir/source" && g++ -std=c++17 -O2 trace_generator.cpp -o "$tmp/flowbench-trace" 2> "$out_dir/logs/build.log")
mkdir -p "$tmp/bin"
for cmd in analyze_cache_key_locality windowed_hitrate; do
  (cd "$repo_dir" && "${GO:-go}" build -o "$tmp/bin/$cmd" "./cmd/$cmd")
done
PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli isolate --rule-file "$fb_rule_file" --output "$tmp/rules.fb" > /dev/null

ps_types=2,5,$(seq -s, 108 124)

features() {
  local label=$1 trace=$2 rule=$3
  "$tmp/bin/analyze_cache_key_locality" -rulefile "$rule" -trace "$trace" -label "$label" -max "$packets" \
    -output "$out_dir/features/$label.csv" > "$out_dir/logs/$label.features.log" 2>&1
}

real() {
  local label=$1 trace=$2 rule=$3
  features "$label" "$trace" "$rule"
  "$tmp/bin/windowed_hitrate" -rulefile "$rule" -trace "$trace" -max "$packets" \
    -windows 1000000,$packets -progress-interval 0 \
    -mp-capacities 2048,2048 -mp-refbits 24,18 -ps-capacity 4096 -ps-index-types "$ps_types" \
    -output-dir "$out_dir/hitrate" -output-csv "$out_dir/hitrate/$label.csv" > "$out_dir/logs/$label.hitrate.log" 2>&1
  echo "done $label"
}

fb() {
  local ra=$1 fa=$2 seed=$3
  local label="fb_rd${ra}-1_fd${fa}-1_s${seed}"
  local work="$tmp/$label"
  mkdir -p "$work"
  (cd "$tmp" && ./flowbench-trace -i rules.fb --isolated -f 1 -fw 32 -ft LPM -n "$packets" \
    -rd "$ra" 1 -fd "$fa" 1 -s "$seed" -o "$work/trace.fbtrace" > "$out_dir/logs/$label.gen.log" 2>&1)
  PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli to-sim \
    --trace "$work/trace.fbtrace" --output "$work/trace.txt" >> "$out_dir/logs/$label.gen.log" 2>&1
  rm -f "$work/trace.fbtrace"
  features "$label" "$work/trace.txt" "$fb_rule_file"
  rm -rf "$work"
  echo "done $label"
}

export -f features real fb
export tmp out_dir fb_rule_file packets ps_types fib_flowbench

{
  for spec in "$@"; do
    IFS='=' read -r label trace rule <<< "$spec"
    echo "real $label $(realpath "$trace") $(realpath "$rule")"
  done
  for ra in $rd_as; do for fa in $fd_as; do for seed in $seeds; do
    echo "fb $ra $fa $seed"
  done; done; done
} | xargs -P "$jobs" -L 1 bash -c '"$0" "$@"'
