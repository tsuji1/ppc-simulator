#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_fixed_mp_missing_configs.sh [options]

Runs the fixed MP configs that were missing from the 3cache/4cache comparison:
  - WIDE anon 2026-03: 4cache /24 /21 /18 /16, 2048 each
  - San Jose: 3cache /24 /20 /16, 2048 each
  - San Jose: 4cache /24 /21 /18 /16, 2048 each
  - Chicago: 3cache /24 /20 /16, 2048 each
  - Chicago: 4cache /24 /21 /18 /16, 2048 each
  - New York: 3cache /24 /20 /16, 2048 each
  - New York: 4cache /24 /21 /18 /16, 2048 each

Options:
  --dry-run             Print exec.sh commands without running them.
  --max <int>           Override MAX_PROCESS in each env file.
  --dbupdate            Force DB insertion/rerun for existing configs.
  --no-sudo             Override env files and run without sudo.
  --no-build            Skip the one-time go build.
  -h, --help            Show this help.

After this finishes, regenerate the report with:
  cd /home/yuzugon/ppc-result-viewer
  bash scripts/generate_best_capacity_sweep_graphs.sh
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

DRY_RUN=false
DBUPDATE=false
NO_SUDO=false
NO_BUILD=false
MAX_PROCESS=""

while (( $# > 0 )); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --max)
      [[ -n "${2:-}" ]] || die "--max requires a value"
      MAX_PROCESS="$2"
      shift 2
      ;;
    --dbupdate)
      DBUPDATE=true
      shift
      ;;
    --no-sudo)
      NO_SUDO=true
      shift
      ;;
    --no-build)
      NO_BUILD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

if [[ -n "$MAX_PROCESS" && ! "$MAX_PROCESS" =~ ^[0-9]+$ ]]; then
  die "--max must be a non-negative integer: $MAX_PROCESS"
fi

CONFIGS=(
  scripts/env/fixed-mp-wide-anon-20260327-4cache.env
  scripts/env/fixed-mp-sanjose-3cache.env
  scripts/env/fixed-mp-sanjose-4cache.env
  scripts/env/fixed-mp-chicago-3cache.env
  scripts/env/fixed-mp-chicago-4cache.env
  scripts/env/fixed-mp-nyc-3cache.env
  scripts/env/fixed-mp-nyc-4cache.env
)

common_flags=(--no-build)
if [[ "$DRY_RUN" == "true" ]]; then
  common_flags+=(--dry-run)
fi
if [[ "$DBUPDATE" == "true" ]]; then
  common_flags+=(--dbupdate)
else
  common_flags+=(--no-dbupdate)
fi
if [[ "$NO_SUDO" == "true" ]]; then
  common_flags+=(--no-sudo)
fi
if [[ -n "$MAX_PROCESS" ]]; then
  common_flags+=(--max "$MAX_PROCESS")
fi

run() {
  printf '\n==> '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

if [[ "$DRY_RUN" != "true" && "$NO_BUILD" != "true" ]]; then
  run go build main.go
fi

for config in "${CONFIGS[@]}"; do
  [[ -f "$config" ]] || die "config file not found: $config"
  run ./exec.sh --config "$config" "${common_flags[@]}"
done

cat <<'EOF'

Next report command:
  cd /home/yuzugon/ppc-result-viewer
  bash scripts/generate_best_capacity_sweep_graphs.sh
EOF
