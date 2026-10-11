#!/usr/bin/env bash
# banana で aloheart と同じものを揃える（sudo 不要）。tsuji で実行する。何度実行してもよい。
#
#   bash setup-user.sh            # repo の clone/pull、Go/uv、trace の symlink、WIDE rule の生成、build
#   SKIP_RULES=1 bash setup-user.sh
#
# 置き場所は ~/yuzugon/{osada-ppc-simulator,ppc-result-viewer,pcap,rules,...}。aloheart とパスは揃えない。
# trace は NAS（/mnt/nas_readonly/network-trace）と既存の ~/pcap を参照する。
# git 管理外のもの（exec.sh、scripts/env/*.env、tasks、ppc-research、WIDE 以外の rule）は
# aloheart 側で sync-from-aloheart.sh を実行して送る。
set -euo pipefail

WS="${WS:-$HOME/yuzugon}"
NAS=/mnt/nas_readonly/network-trace
BRANCH="${BRANCH:-wip/aloheart-sync}"

mkdir -p "$WS"
export PATH="/usr/local/go/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

clone_or_pull() { # clone_or_pull <url> <dir> <branch> [remote 名]
  local url=$1 dir=$2 branch=$3 remote=${4:-origin}
  if [[ -d $dir/.git ]]; then
    git -C "$dir" fetch "$remote" --prune
    git -C "$dir" switch "$branch"
    git -C "$dir" pull --ff-only
  elif [[ -d $dir ]]; then
    # sync-from-aloheart.sh が先に gitignore された設定を置いた場合
    git -C "$dir" init -q
    git -C "$dir" remote add "$remote" "$url"
    git -C "$dir" fetch "$remote"
    git -C "$dir" checkout -f -b "$branch" --track "$remote/$branch"
  else
    git clone -o "$remote" -b "$branch" "$url" "$dir"
  fi
}

echo "== git repos"
# banana の GitHub は ssh 鍵が未登録なので gh の https 認証を使う
gh auth setup-git
clone_or_pull https://github.com/tsuji1/ppc-simulator.git "$WS/osada-ppc-simulator" "$BRANCH" origin-github
clone_or_pull git@gitlab.com:yamaki-lab/ppc/ppc-result-viewer.git "$WS/ppc-result-viewer" "$BRANCH"
clone_or_pull https://github.com/tsuji1/research-routing-table-cache.git "$WS/research-routing-table-cache" main
clone_or_pull https://github.com/tsuji1/research-routing-table-cache.wiki.git "$WS/research-routing-table-cache.wiki" master

echo "== Go / uv"
# /usr/local/go は 1.23 だが go.mod は 1.24.2 以上。sudo せず、go が 1.26.1（aloheart と同じ）を自動で取ってくるようにする
go env -w GOTOOLCHAIN=go1.26.1
go version
# banana の ~/.cargo/bin/uv は 0.4 系で self update できないので、公式 installer で ~/.local/bin に入れる
if [[ ! -x $HOME/.local/bin/uv ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi

echo "== traces"
mkdir -p "$WS/pcap/non-anon"
link() { # link <実体> <リンク>
  if [[ -e $1 ]]; then ln -sfn "$1" "$2"; else echo "  missing: $1" >&2; fi
}
# 匿名化 WIDE（MAWI samplepoint-F）。banana の ~/pcap にあるものはサイズが aloheart と一致した
link "$HOME/pcap/202509271400.pcap" "$WS/pcap/202509271400.pcap"
link "$HOME/pcap/202603271400.pcap" "$WS/pcap/202603271400.pcap"
if [[ ! -s $WS/pcap/202512271400.pcap ]]; then
  echo "  downloading MAWI 202512271400"
  curl -fL https://mawi.wide.ad.jp/mawi/samplepoint-F/2025/202512271400.pcap.gz \
    | gzip -dc > "$WS/pcap/202512271400.pcap.part"
  mv "$WS/pcap/202512271400.pcap.part" "$WS/pcap/202512271400.pcap"
fi
# CAIDA
link "$HOME/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap" "$WS/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap"
link "$HOME/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap" "$WS/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap"
nyc=equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
if [[ ! -s $WS/pcap/$nyc ]]; then
  echo "  gunzip $nyc"
  pigz -dc "$NAS/CAIDA/2019-equinix/data.caida.org/datasets/passive-2019/equinix-nyc/20190117-130000.UTC/$nyc.gz" \
    > "$WS/pcap/$nyc.part"
  mv "$WS/pcap/$nyc.part" "$WS/pcap/$nyc"
fi
# SINET/JPIX
link "$NAS/SINET/jpix2sinet90s_5tuple.txt" "$WS/pcap/jpix2sinet90s_5tuple.txt"
link "$NAS/SINET/sinet2jpix90s_5tuple.txt" "$WS/pcap/sinet2jpix90s_5tuple.txt"
# 非匿名 WIDE
for d in 2025-09-27 2025-12-27 2026-03-27; do
  link "$NAS/WIDE/unanoymized/$d.pcap" "$WS/pcap/non-anon/$d.pcap"
done
link "$NAS/WIDE/unanoymized/2025-12-27-ipv6.pcap" "$WS/pcap/non-anon/2025-12-27-ipv6.pcap"

echo "== rules"
mkdir -p "$WS/rules" "$WS/osada-ppc-simulator/rules"
# osada-ppc-simulator/rules（gitignore）は banana の旧 checkout と aloheart で中身が一致する。足りない分は sync で届く
cp -n "$HOME"/osada-ppc-simulator/rules/* "$WS/osada-ppc-simulator/rules/" 2>/dev/null || true
if [[ -z ${SKIP_RULES:-} ]]; then
  # WIDE（route-views.wide）の RIB から作り直す。JST 15:00 = UTC 06:00 の RIB
  declare -A want=(
    [20250927]=b85a8a934ea3aea5bf6b0d3c2e69ed17
    [20251227]=dd6484605828a937006797ff8f579f82
    [20260327]=0210bbfa778c7a94a594b3fc38d08f9d
  )
  for ymd in "${!want[@]}"; do
    out="$WS/rules/rib.$ymd.0600.unique.rule"
    if [[ ! -s $out ]]; then
      python3 "$WS/osada-ppc-simulator/scripts/wide_rib_to_rule.py" \
        --date "${ymd:0:4}-${ymd:4:2}-${ymd:6:2}" --time 15:00 --ipv4-only --keep-bz2 --outdir "$WS/rules"
    fi
    got=$(md5sum "$out" | cut -d' ' -f1)
    if [[ $got == "${want[$ymd]}" ]]; then echo "  OK  $out"; else echo "  MISMATCH $out ($got)" >&2; fi
  done
fi
# 2024-06-25 の WIDE rule は next hop が乱数 UUID で再生成できない。banana の既存ファイルが aloheart と一致する
[[ -s $WS/rules/wide.rib.20240625.1400.unique.rule ]] || \
  cp "$HOME/osada-ppc-simulator/rules/wide.rib.20240625.1400.unique.rule" "$WS/rules/"

echo "== build"
(cd "$WS/osada-ppc-simulator" && go build -o main . && echo "  simulator OK")
(cd "$WS/ppc-result-viewer" && uv sync && echo "  viewer venv OK")
cacti="$WS/ppc-result-viewer/scripts/cacti70/cacti"
if [[ ! -x $cacti/cacti ]]; then
  (cd "$cacti" && make -j"$(nproc)" >/dev/null && echo "  CACTI OK")
fi

echo "done"
