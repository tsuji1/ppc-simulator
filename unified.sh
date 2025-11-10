#!/usr/bin/env bash
set -euo pipefail

# ===== Build =====
go build main.go

# ===== Config =====
RULEFILE="rules/wide.rib.20240625.1400.unique.rule"

TRACES=(
  "/home/tsuji/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap"
  "/home/tsuji/pcap/jpix2sinet90s_5tuple.txt"
  "/home/tsuji/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap"
  "/home/tsuji/pcap/202504201400.pcap"
)

# ===== Run =====
for TRACE in "${TRACES[@]}"; do
  if [[ ! -f "$TRACE" ]]; then
    echo "[WARN] trace not found, skip: $TRACE" >&2
    continue
  fi

    cmd=( ./main -rulefile "$RULEFILE" -trace "$TRACE" -max 10000000 )

    echo "==> running: ${cmd[*]}"
    time "${cmd[@]}"
done

