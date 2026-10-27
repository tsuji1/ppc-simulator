#!/usr/bin/env bash
# FlowBench の trace を条件ごとに生成し、1 rule あたりの flow 数・packet 数を集計する。
#
# 使い方: run_flowbench_flows_per_rule.sh FLOWBENCH_DIR RULE_FILE OUT_DIR
#   FLOWBENCH_DIR  Flow-Bench の checkout（source/ を build する）
#   RULE_FILE      元の rule file（<ip> <prefix長> <nexthop>）
#   OUT_DIR        集計結果の出力先
# trace は大きいので一時 directory に作り、集計後に消す（同じ条件で再生成できる）。
set -euo pipefail

flowbench_dir=$1
rule_file=$2
out_dir=$3
script_dir=$(cd "$(dirname "$0")" && pwd)
# rule set の変換は submodule の fib-flowbench（git submodule update --init で取る）
fib_flowbench=$script_dir/../third_party/fib-flowbench
if [[ ! -f $fib_flowbench/src/fib_flowbench/cli.py ]]; then
  echo "fib-flowbench がない。git submodule update --init third_party/fib-flowbench を実行する" >&2
  exit 1
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$out_dir"
out_dir=$(cd "$out_dir" && pwd)

git -C "$flowbench_dir" rev-parse HEAD > "$out_dir/flowbench_commit.txt"
git -C "$flowbench_dir" status --short >> "$out_dir/flowbench_commit.txt"
(cd "$flowbench_dir/source" && g++ -std=c++14 -O2 trace_generator.cpp -o "$tmp/flowbench-trace")

PYTHONPATH="$fib_flowbench/src" python3 -m fib_flowbench.cli isolate --rule-file "$rule_file" --output "$tmp/rules.fb"
cp "$tmp/rules.fb.meta.json" "$out_dir/rules.fb.meta.json"

# rule の Pareto(a, b)、flow の Pareto(a, b)
configs=(
  "2 1 1 1"
  "1 1 1 1"
  "0.9 1 1 1"
  "0.8 1 1 1"
  "0.7 1 1 1"
  "0.5 1 1 1"
  "1 0.1 1 1"
  "1 1 1 0"
)
for config in "${configs[@]}"; do
  read -r ra rb fa fb <<< "$config"
  label="rd${ra}-${rb}_fd${fa}-${fb}_n10m_s1"
  (cd "$tmp" && ./flowbench-trace -i rules.fb --isolated -f 1 -fw 32 -ft LPM \
    -n 10000000 -rd "$ra" "$rb" -fd "$fa" "$fb" -s 1 -o "$label.fbtrace" > "$out_dir/$label.gen.log")
  python3 "$script_dir/flowbench_flows_per_rule.py" --trace "$tmp/$label.fbtrace" \
    --map "$tmp/rules.fb.map" --label "$label" --out-dir "$out_dir"
  rm -f "$tmp/$label.fbtrace"
done
