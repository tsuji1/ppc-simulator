#!/usr/bin/env bash
# CAIDA 100G の 1 時間 trace（potato NAS の gz 3 本）から、複数の 10 秒窓を切り出す。
# gz は 1 本 580〜820 GB あり NAS から約 107 MB/s でしか読めないので、1 本につき 1 回だけ展開して全部の窓を書く。
#
# 使い方: cut_caida100g_windows.sh OUT_DIR [OFFSETS] [DUR]
#   OUT_DIR  出力先（researchctl run では "$RESEARCHCTL_OUT/caida100g" を渡す）
#   OFFSETS  13:00:00 UTC からの窓の開始（既定 0m,10m,20m,30m,40m,50m）
#   DUR      窓の長さ（既定 10s）
# 出力: OUT_DIR/<trace>.t<秒>s.pcap、<trace>.windows.tsv（窓ごとの packet 数）、SHA256SUMS、capinfos.tsv
# 先頭の窓（t0s）は 2026-10-12 に切り出した *.first10s.pcap と同じになるはずなので、sha256 を比べて check.txt に書く。
set -euo pipefail

out_dir=$1
offsets=${2:-0m,10m,20m,30m,40m,50m}
dur=${3:-10s}
src=${CAIDA_SRC:-/mnt/potato_nas_readonly/network-trace/caida}
old_dir=${OLD_DIR:-$HOME/yuzugon/pcap/caida100g}
script_dir=$(cd "$(dirname "$0")" && pwd)
repo_dir=$(cd "$script_dir/.." && pwd)

mkdir -p "$out_dir"
out_dir=$(cd "$out_dir" && pwd)
bin=$(mktemp -d)
trap 'rm -rf "$bin"' EXIT
(cd "$repo_dir" && "${GO:-go}" build -o "$bin/cut_pcap_windows" ./cmd/cut_pcap_windows)

cut_one() { # gz base prefix
  pigz -dc "$src/$1" | "$bin/cut_pcap_windows" -base "$2" -offsets "$offsets" -dur "$dur" -out "$out_dir" -prefix "$3" \
    2> "$out_dir/$3.log"
}
# pigz は cut_pcap_windows が止まると SIGPIPE で終わるので、pipefail の失敗を cut_pcap_windows の結果で判定する
run_one() {
  set +o pipefail
  cut_one "$@" || true
  if ! grep -q '^read=' "$out_dir/$3.log"; then
    echo "失敗: $3（log: $out_dir/$3.log）" >&2
    return 1
  fi
  echo "done $3"
}

run_one 20250320-130000.dira.anon.pcap.gz 2025-03-20T13:00:00Z 20250320-130000.dira.anon &
p1=$!
run_one 20250320130000b.pcap.gz 2025-03-20T13:00:00Z 20250320-130000.dirb.anon &
p2=$!
run_one 20251120-130000.dira.anon.pcap.gz 2025-11-20T13:00:00Z 20251120-130000.dira.anon &
p3=$!
fail=0
for p in $p1 $p2 $p3; do wait "$p" || fail=1; done
[[ $fail == 0 ]] || exit 1

cd "$out_dir"
sha256sum ./*.pcap > SHA256SUMS
capinfos -T -c -u -a -e -y -i -z -E ./*.pcap > capinfos.tsv

# 先頭の窓と 2026-10-12 の切り出しを比べる
: > check.txt
for t in 20250320-130000.dira.anon 20250320-130000.dirb.anon 20251120-130000.dira.anon; do
  new=$(awk -v f="./$t.t0s.pcap" '$2 == f {print $1}' SHA256SUMS)
  old=$(awk -v f="$t.first10s.pcap" '$2 == f {print $1}' "$old_dir/SHA256SUMS" 2>/dev/null || true)
  if [[ -n $old && $new == "$old" ]]; then
    echo "$t t0s == first10s ($new)" >> check.txt
  else
    echo "$t t0s != first10s (new=$new old=${old:-なし})" >> check.txt
  fi
done
cat check.txt
