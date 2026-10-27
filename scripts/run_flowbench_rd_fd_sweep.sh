#!/usr/bin/env bash
# FlowBench の trace を rule の Pareto a（-rd a 1）と flow の Pareto a（-fd a 1）の組と seed ごとに作り、
# 使われる prefix 数などの性質と、MP・LTPC（index 長 L=8..24、ideal）の hit rate を測る（#117、#118）。
#
# 使い方: run_flowbench_rd_fd_sweep.sh FLOWBENCH_DIR RULE_FILE REAL_TRACE OUT_DIR [JOBS]
#   FLOWBENCH_DIR  Flow-Bench の fork（tsuji1/Flow-Bench の routing-fib）の checkout。source/ を build する
#   RULE_FILE      元の rule file（<ip> <prefix長> <nexthop>）
#   REAL_TRACE     比べる実 trace（pcap など）。label は real
#   OUT_DIR        出力先。coverage/<label>/、hitrate/<label>.csv、logs/ を作る
#   JOBS           同時に処理する trace の数（既定 6）
# 条件は環境変数 RD_AS・FD_AS・SEEDS（空白区切り）で変えられる。go が PATH にないときは GO に go のパスを渡す。
# trace は大きいので一時 directory に作り、解析後に消す（同じ条件で再生成できる）。
set -euo pipefail

flowbench_dir=$1
rule_file=$(realpath "$2")
real_trace=$(realpath "$3")
out_dir=$4
jobs=${5:-6}
rd_as=${RD_AS:-"0.70 0.75 0.80"}
fd_as=${FD_AS:-"0.70 0.75 0.80 1"}
seeds=${SEEDS:-"1 2 3 4 5"}
packets=10000000
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(cd "$script_dir/.." && pwd)
# rule set の変換は submodule の fib-flowbench（git submodule update --init で取る）
fib_flowbench=$repo_dir/third_party/fib-flowbench
if [[ ! -f $fib_flowbench/src/fib_flowbench/cli.py ]]; then
  echo "fib-flowbench がない。git submodule update --init third_party/fib-flowbench を実行する" >&2
  exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$out_dir"/{coverage,hitrate,logs}
out_dir=$(cd "$out_dir" && pwd)

# 使った版を残す
{
  echo "flowbench $(git -C "$flowbench_dir" rev-parse HEAD)"
  git -C "$flowbench_dir" status --short --untracked-files=no
  echo "fib-flowbench $(git -C "$fib_flowbench" rev-parse HEAD)"
  echo "simulator $(git -C "$repo_dir" rev-parse HEAD)"
} > "$out_dir/versions.txt"

(cd "$flowbench_dir/source" && g++ -std=c++17 -O2 trace_generator.cpp -o "$tmp/flowbench-trace")
mkdir -p "$tmp/bin"
for cmd in analyze_lpm_prefix_coverage windowed_hitrate; do
  (cd "$repo_dir" && "${GO:-go}" build -o "$tmp/bin/$cmd" "./cmd/$cmd")
done

PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli isolate --rule-file "$rule_file" --output "$tmp/rules.fb"
cp "$tmp/rules.fb.meta.json" "$out_dir/rules.fb.meta.json"

# LTPC は ideal（2）、/18 の CRC（5）、direct prefix index L=8..24（100+L）
ps_types=2,5,$(seq -s, 108 124)

analyze() {
  local label=$1 trace=$2
  "$tmp/bin/analyze_lpm_prefix_coverage" -rulefile "$rule_file" -trace "$trace" -label "$label" \
    -max "$packets" -checkpoints "$packets" -progress-interval 0 \
    -output-dir "$out_dir/coverage/$label" > "$out_dir/logs/$label.coverage.log" 2>&1
  "$tmp/bin/windowed_hitrate" -rulefile "$rule_file" -trace "$trace" -max "$packets" \
    -windows 1000000,$packets -progress-interval 0 \
    -mp-capacities 2048,2048 -mp-refbits 24,18 -ps-capacity 4096 -ps-index-types "$ps_types" \
    -output-dir "$out_dir/hitrate" -output-csv "$out_dir/hitrate/$label.csv" > "$out_dir/logs/$label.hitrate.log" 2>&1
}

one() {
  local ra=$1 fa=$2 seed=$3
  local label="fb_rd${ra}-1_fd${fa}-1_s${seed}"
  local work="$tmp/$label"
  mkdir -p "$work"
  (cd "$tmp" && ./flowbench-trace -i rules.fb --isolated -f 1 -fw 32 -ft LPM -n "$packets" \
    -rd "$ra" 1 -fd "$fa" 1 -s "$seed" -o "$work/trace.fbtrace" > "$out_dir/logs/$label.gen.log" 2>&1)
  PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli to-sim \
    --trace "$work/trace.fbtrace" --output "$work/trace.txt" >> "$out_dir/logs/$label.gen.log" 2>&1
  rm -f "$work/trace.fbtrace"
  analyze "$label" "$work/trace.txt"
  rm -rf "$work"
  echo "done $label"
}

export -f analyze one
export tmp out_dir rule_file packets ps_types fib_flowbench

{
  echo "real"
  for ra in $rd_as; do for fa in $fd_as; do for seed in $seeds; do
    echo "fb $ra $fa $seed"
  done; done; done
} | xargs -P "$jobs" -L 1 bash -c '
  if [[ $0 == real ]]; then analyze real "'"$real_trace"'" && echo "done real"; else one "$1" "$2" "$3"; fi'
