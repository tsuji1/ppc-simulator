#!/usr/bin/env bash
# aloheart で実行し、git に載っていない小さなものだけを banana に送る（sudo 不要）。
# コードは GitHub/GitLab 経由で揃える（banana で setup-user.sh か git pull）。pcap と gob は送らない。
#
#   bash scripts/banana/sync-from-aloheart.sh          # 送る
#   bash scripts/banana/sync-from-aloheart.sh -n       # 何が送られるかだけ見る
#
# 送るもの:
# - research/（入口の AGENTS.md など）、research.md、tasks/、ppc-research/（git 管理外）
# - osada-ppc-simulator の gitignore されたもの: exec.sh、.env、scripts/env/*.env、
#   c/liblctrie.{a,so}（作るには設定済みの Linux kernel source が要るので、ビルド済みを送る）
# - rules のうち banana で作り直せないもの（WIDE 2025-26 は setup-user.sh が RIB から作る）
set -euo pipefail

HOST="${HOST:-banana}"
SRC=/home/yuzugon
DST=yuzugon # banana の ~/yuzugon
RSYNC=(rsync -a --checksum --info=stats1,name1 "$@")

"${RSYNC[@]}" "$SRC/research.md" "$HOST:$DST/"
"${RSYNC[@]}" "$SRC/research" "$SRC/tasks" "$SRC/ppc-research" "$HOST:$DST/"

cd "$SRC/osada-ppc-simulator"
"${RSYNC[@]}" --relative exec.sh .env scripts/env/ c/liblctrie.a c/liblctrie.so "$HOST:$DST/osada-ppc-simulator/"
"${RSYNC[@]}" rules/ "$HOST:$DST/osada-ppc-simulator/rules/"

"${RSYNC[@]}" \
  --exclude='rib.2025*' --exclude='rib.2026*' \
  --include='*.unique.rule' --include='*.meta.md' --exclude='*' \
  "$SRC/rules/" "$HOST:$DST/rules/"
