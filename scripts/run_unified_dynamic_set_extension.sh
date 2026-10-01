#!/usr/bin/env bash
set -euo pipefail

PHASE="${1:-smoke}"
SELECTED_EPOCH="${SELECTED_EPOCH:-4096}"
SELECTED_THRESHOLD="${SELECTED_THRESHOLD:-8}"
SELECTED_MAX_PER_SET="${SELECTED_MAX_PER_SET:-2}"

configs=(
  scripts/env/unified-set-extension-sanjose.env
  scripts/env/unified-set-extension-chicago.env
  scripts/env/unified-set-extension-nyc.env
)

run_dynamic() {
  local config="$1" max_process="$2" capacities="$3" mode="$4" ratio="$5" epoch="$6" threshold="$7" max_per_set="$8"
  ./exec.sh --config "$config" --no-sudo --no-build --max "$max_process" --capacity-values "$capacities" \
    --set-extension-policy epoch-full-repeat-miss \
    --set-extension-capacity-mode "$mode" \
    --set-extension-pool-ratio "$ratio" \
    --set-extension-epoch-length "$epoch" \
    --set-extension-pressure-threshold "$threshold" \
    --set-extension-max-per-set "$max_per_set"
}

case "$PHASE" in
  smoke)
    for config in "${configs[@]}"; do
      ./exec.sh --config "$config" --no-sudo --no-build --max 100000 --capacity-values 4096 --set-extension-policy off
      run_dynamic "$config" 100000 4096 fixed-total 0.125 4096 8 2
      run_dynamic "$config" 100000 4096 additive 0.125 4096 8 2
    done
    ;;
  tuning)
    config="${configs[0]}"
    for mode in fixed-total additive; do
      for epoch in 1024 4096 16384; do
        for threshold in 1 8 32; do
          for max_per_set in 1 2; do
            run_dynamic "$config" 1000000 4096 "$mode" 0.125 "$epoch" "$threshold" "$max_per_set"
          done
        done
      done
    done
    ;;
  full)
    for config in "${configs[@]}"; do
      ./exec.sh --config "$config" --no-sudo --no-build --max 10000000 --capacity-start 10 --capacity-end 14 --set-extension-policy off
      ./exec.sh --config "$config" --no-sudo --no-build --max 10000000 --capacity-values "1088,2176,4352,8704,17408" --set-extension-policy off
      ./exec.sh --config "$config" --no-sudo --no-build --max 10000000 --capacity-values "1152,2304,4608,9216,18432" --set-extension-policy off
      ./exec.sh --config "$config" --no-sudo --no-build --max 10000000 --capacity-values "1280,2560,5120,10240,20480" --set-extension-policy off
      for mode in fixed-total additive; do
        for ratio in 0.0625 0.125 0.25; do
          run_dynamic "$config" 10000000 "1024,2048,4096,8192,16384" "$mode" "$ratio" "$SELECTED_EPOCH" "$SELECTED_THRESHOLD" "$SELECTED_MAX_PER_SET"
        done
      done
    done
    ;;
  *)
    echo "usage: $0 [smoke|tuning|full]" >&2
    exit 2
    ;;
esac
