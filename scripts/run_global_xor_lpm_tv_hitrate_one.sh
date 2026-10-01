#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 LABEL RULEFILE TRACE" >&2
  exit 2
fi

label=$1
rulefile=$2
trace=$3
root=/home/yuzugon/osada-ppc-simulator
output_dir="$root/scripts/reports/global-xor-lpm-tv-exhaustive24/hitrate"
binary="$root/bin/windowed_hitrate"
mkdir -p "$output_dir"

"$binary" \
  -rulefile "$rulefile" \
  -trace "$trace" \
  -output-dir "$output_dir" \
  -output-csv "$output_dir/$label.csv" \
  -max 10000000 \
  -windows 1000000 \
  -way 8 \
  -mp-refbits 24,20 \
  -mp-capacities 2048,2048 \
  -ps-index-types 5,2 \
  -ps-capacity 2048 \
  -window-mode warm
