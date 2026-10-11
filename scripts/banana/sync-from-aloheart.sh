#!/usr/bin/env bash
# aloheart で実行し、git に載っていない小さなものだけを banana に送る（sudo 不要）。
# コードは GitHub/GitLab 経由で揃える（banana で setup-user.sh か git pull）。pcap と gob は送らない。
#
#   bash scripts/banana/sync-from-aloheart.sh          # 送る
#   bash scripts/banana/sync-from-aloheart.sh -n       # 何が送られるかだけ見る
#
# 送るもの:
# - research/（入口の AGENTS.md など）、research.md、tasks/、ppc-research/（git 管理外）
# - osada-ppc-simulator の gitignore された設定: exec.sh、.env、scripts/env/*.env
# - rules のうち banana で作り直せないもの（WIDE 2025-26 は setup-user.sh が RIB から作る）
set -euo pipefail

HOST="${HOST:-banana}"
SRC=/home/yuzugon
DST=yuzugon # banana の /home/tsuji/yuzugon（= /home/yuzugon）
RSYNC=(rsync -a --checksum --info=stats1,name1 "$@")

"${RSYNC[@]}" "$SRC/research.md" "$HOST:$DST/"
"${RSYNC[@]}" "$SRC/research" "$SRC/tasks" "$SRC/ppc-research" "$HOST:$DST/"

cd "$SRC/osada-ppc-simulator"
"${RSYNC[@]}" --relative exec.sh .env scripts/env/ "$HOST:$DST/osada-ppc-simulator/"
"${RSYNC[@]}" rules/ "$HOST:$DST/osada-ppc-simulator/rules/"

"${RSYNC[@]}" \
  --exclude='rib.2025*' --exclude='rib.2026*' \
  --include='*.unique.rule' --include='*.meta.md' --exclude='*' \
  "$SRC/rules/" "$HOST:$DST/rules/"
