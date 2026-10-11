#!/usr/bin/env bash
# banana で sudo が必要な準備だけをまとめたもの。ユーザ tsuji で `sudo bash setup-root.sh` と実行する。
#
# - Go を aloheart と同じ 1.26.1 にする（go.mod は 1.24.2 以上を要求、banana は 1.23.0）
# - /home/yuzugon -> /home/tsuji/yuzugon の symlink を作る
#   （scripts/*.sh や *.py が /home/yuzugon/{rules,pcap,...} を直書きしているため）
# - /research/trace を tsuji 所有で作る（中身の symlink は setup-user.sh が張る）
# - RTL 検証用の yosys / iverilog を入れる（ppc-research/rtl）
#
# 何度実行しても同じ状態になる。
set -euo pipefail

TARGET_USER="${TARGET_USER:-tsuji}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
WORKSPACE="$TARGET_HOME/yuzugon"
GO_VERSION="1.26.1"

if [[ $EUID -ne 0 ]]; then
  echo "sudo bash $0 で実行してください" >&2
  exit 1
fi

echo "== apt packages"
apt-get update
apt-get install -y yosys iverilog bgpdump zstd pigz rsync build-essential

echo "== Go $GO_VERSION"
if /usr/local/go/bin/go version 2>/dev/null | grep -q "go$GO_VERSION "; then
  echo "already installed"
else
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/go.tgz" "https://go.dev/dl/go$GO_VERSION.linux-amd64.tar.gz"
  rm -rf /usr/local/go.old
  [[ -d /usr/local/go ]] && mv /usr/local/go /usr/local/go.old
  tar -C /usr/local -xzf "$tmp/go.tgz"
  rm -rf "$tmp" /usr/local/go.old
  /usr/local/go/bin/go version
fi

echo "== /home/yuzugon -> $WORKSPACE"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$WORKSPACE"
if [[ -L /home/yuzugon ]]; then
  ln -sfn "$WORKSPACE" /home/yuzugon
elif [[ -e /home/yuzugon ]]; then
  echo "/home/yuzugon が symlink 以外で存在します。手で確認してください" >&2
  exit 1
else
  ln -s "$WORKSPACE" /home/yuzugon
fi
ls -ld /home/yuzugon

echo "== /research/trace"
install -d -o root -g root -m 755 /research
install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 /research/trace
ls -ld /research/trace

echo "done. 続けて tsuji で bash setup-user.sh を実行してください"
