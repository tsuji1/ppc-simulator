#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIGS=(
  "scripts/env/multi-exclusive-chicago-anon-3layer-24-23to10.env"
  "scripts/env/multi-exclusive-wide-anon-20260327-3layer-24-23to10.env"
  "scripts/env/multi-exclusive-nyc-anon-3layer-24-23to10.env"
)

LOG_DIR="scripts/reports/mp3_sweep_23to10_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "MP3 /24 + descending /23../10 sweep"
echo "Per trace: 91 refbits pairs x 64 capacity tuples = 5824 configurations"
echo "Existing MongoDB results are skipped because dbupdate is disabled."
echo "Log: $LOG_FILE"

go build main.go

for config in "${CONFIGS[@]}"; do
  echo "Starting $config"
  ./exec.sh --config "$config" --no-build "$@"
done

echo "All MP3 /23../10 sweep configs completed."
