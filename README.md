# README.md


## aloheart



### データ


#### ルール

通常使う rule は `/home/yuzugon/rules` にあり、sudo なしで読める。

/home/yuzugon/rules/wide.rib.20240625.1400.unique.rule
/home/yuzugon/rules/rib.20260327.0600.unique.rule
/home/yuzugon/rules/rib.20251227.0600.unique.rule
/home/yuzugon/rules/rib.20160628.1200.bz2
/home/yuzugon/rules/rib.20250927.0600.unique.rule
/home/yuzugon/rules/rrc06.bview.20180502.0000.rule
/home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule
/home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule.meta.md
/home/yuzugon/rules/bview.20190117.0800.gz
/home/yuzugon/rules/bview.20190117.1600.gz
/home/yuzugon/rules/rrc11.bview.20190117.0800.rule
/home/yuzugon/rules/rrc11.bview.20190117.0800.unique.rule
/home/yuzugon/rules/rrc11.bview.20190117.0800.unique.rule.meta.md
/home/yuzugon/rules/rrc11.bview.20190117.1600.rule
/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule
/home/yuzugon/rules/rrc11.bview.20190117.1600.unique.rule.meta.md

CAIDA Equinix San Jose / Chicago / New York 匿名化 trace 用には、以下の rule を使う。
San Jose / Chicago の同名ファイルはリポジトリ内の
`/home/yuzugon/osada-ppc-simulator/rules/` にも生成済み。
New York の RRC11 rule は `/home/yuzugon/rules/` に置く。

/home/yuzugon/rules/route-views.isc.rib.20140320.1400.rule
/home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule
/home/yuzugon/rules/route-views.isc.rib.20140320.1400.unique.rule.meta.md
/home/yuzugon/rules/route-views.chicago.rib.20160628.1400.rule
/home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule
/home/yuzugon/rules/route-views.chicago.rib.20160628.1400.unique.rule.meta.md


#### トレース

匿名化済み trace は `/home/yuzugon/pcap` にあり、sudo なしで読める。

/home/yuzugon/pcap/202509271400.pcap
/home/yuzugon/pcap/202512271400.pcap
/home/yuzugon/pcap/202603271400.pcap
/home/yuzugon/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap
/home/yuzugon/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap
/home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
/home/yuzugon/pcap/jpix2sinet90s_5tuple.txt
/home/yuzugon/pcap/sinet2jpix90s_5tuple.txt

非匿名 trace は `/research/trace` にあり、root 権限でしか読めないことがある。

/research/trace/2025-09-27.pcap
/research/trace/2025-12-27.pcap
/research/trace/2026-03-27.pcap
/research/trace/2025-09-27.pcap.zst
/research/trace/2025-12-27.pcap.xz
/research/trace/2026-03-27.pcap.xz

anonとついているものは匿名化されている.また1400(jst)など時刻が付いているものは匿名化されているものである.
匿名 trace と `/home/yuzugon/rules/` の rule はユーザー権限で扱えるため、通常は
`--no-sudo` でよい。非匿名 trace を使う作業で sudo が必要な場合、Codex には実行させず、
ユーザーにコマンドを渡して手元の shell で実行してもらう。

#### JPIX/SINET 5tuple trace と rule の対応

| trace | rule / collector | メモ |
| --- | --- | --- |
| `jpix2sinet90s_5tuple.txt` | `rrc06.bview.20180502.0000.unique.rule` | JPIX から SINET 方向の 90 秒 5tuple text trace。形式は `time src_ip src_port dst_ip dst_port proto tos len`。RIB は RIPE RIS `rrc06` の 2018-05-02 bview を使う。 |
| `sinet2jpix90s_5tuple.txt` | `rrc06.bview.20180502.0000.unique.rule` | SINET から JPIX 方向の 90 秒 5tuple text trace。RIB は同じ `rrc06.bview.20180502.0000.unique.rule` を使う。 |

`rrc06` は RIPE RIS の route collector metadata で Otemachi, JP / DIX-IE, JPIX とされているため、この JPIX/SINET trace pair の rule source に使う。
RIS raw data の bview URL 形式は `https://data.ris.ripe.net/rrcXX/YYYY.MM/bview.YYYYMMDD.HHmm.gz` で、dump は 8 時間ごとに作られる。
今回の trace はファイル名に時刻がないため、2018-05-02 00:00 UTC の
`https://data.ris.ripe.net/rrc06/2018.05/bview.20180502.0000.gz`
を既定にする。

rule の生成:

```bash
cd /home/yuzugon/osada-ppc-simulator

python3 scripts/build_trace_rules.py \
  --collector ris:rrc06 \
  --rib-utc 2018-05-02T00:00 \
  /home/yuzugon/pcap/jpix2sinet90s_5tuple.txt
```

通常権限では出力先はリポジトリ内 `rules/` になる。
共有領域に配置する場合は、生成後に手元の shell で以下のようなコマンドを実行する。

```bash
sudo install -D -m 0644 rules/rrc06.bview.20180502.0000.rule /research/rules/rrc06.bview.20180502.0000.rule
sudo install -D -m 0644 rules/rrc06.bview.20180502.0000.unique.rule /research/rules/rrc06.bview.20180502.0000.unique.rule
sudo install -D -m 0644 rules/rrc06.bview.20180502.0000.unique.rule.meta.md /research/rules/rrc06.bview.20180502.0000.unique.rule.meta.md
```

cache simulator で使う例:

```bash
./exec.sh \
  --rulefile /home/yuzugon/rules/rrc06.bview.20180502.0000.unique.rule \
  --trace /home/yuzugon/pcap/jpix2sinet90s_5tuple.txt \
  --trace /home/yuzugon/pcap/sinet2jpix90s_5tuple.txt \
  --cachetype UnifiedCache \
  --way 8 \
  --cache-index-type 5 \
  --capacity-start 10 \
  --capacity-end 15 \
  --no-sudo
```

#### CAIDA Equinix 匿名化 trace と rule の対応

| trace | rule / collector | メモ |
| --- | --- | --- |
| `equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap` | `route-views.isc.rib.20140320.1400.unique.rule` | `equinix-sanjose` の CAIDA monitor は San Jose-Los Angeles の Tier1 backbone link。2014年9月に停止。地理的に近い BGP collector は Palo Alto / PAIX 系で、`route-views.isc` または RIPE RIS `rrc14` が候補。ここでは trace 時刻 2014-03-20 13:24 UTC に最も近い 2時間粒度の RouteViews ISC RIB、2014-03-20 14:00 UTC を使う。 |
| `equinix-chicago.dirB.20140320-140100.UTC.anon.pcap` | `route-views.chicago.rib.20160628.1400.unique.rule` | `equinix-chicago` の CAIDA monitor は Chicago-Seattle の Tier1 backbone linkで、2015年3月末に停止。RouteViews `route-views.chicago` は 2016年6月以降なので、2014年の CAIDA Chicago trace とは時期が合わない。`rib.20160628.1200.bz2` は 101 byte で実データがないため、最初の空でない RouteViews Chicago RIB として 2016-06-28 14:00 UTC を使う。これは地理的対応用で、時刻対応ではない。 |
| `equinix-nyc.dirB.20190117-135900.UTC.anon.pcap` | `rrc11.bview.20190117.1600.unique.rule` | `equinix-nyc` の trace は `/home/yuzugon/pcap/` に置く。RIPE RIS `rrc11` は New York / NYIIX の collector。trace 時刻 2019-01-17 13:59 UTC に対し、8時間粒度の RIB では 2019-01-17 16:00 UTC が最寄りなので通常はこれを使う。2019-01-17 08:00 UTC の RIB も比較用に `/home/yuzugon/rules/` に保持する。 |

匿名化 Equinix trace 用 rule は `scripts/build_trace_rules.py` で生成する。
既存 rule と同じく、raw `.rule` と、3カラム目を UUID 化した `.unique.rule` の両方を出す。

```bash
cd /home/yuzugon/osada-ppc-simulator

python3 scripts/build_trace_rules.py \
  --candidate-index 0 \
  /home/yuzugon/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap

python3 scripts/build_trace_rules.py \
  --rib-utc 2016-06-28T14:00 \
  /home/yuzugon/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap

# RIPE RIS RRC11, New York / NYIIX
wget -P /home/yuzugon/rules https://data.ris.ripe.net/rrc11/2019.01/bview.20190117.0800.gz
wget -P /home/yuzugon/rules https://data.ris.ripe.net/rrc11/2019.01/bview.20190117.1600.gz

python3 scripts/build_trace_rules.py \
  --outdir /home/yuzugon/rules \
  --workdir /home/yuzugon/rules \
  --rib-utc 2019-01-17T16:00 \
  --keep-rib \
  /home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap

python3 scripts/build_trace_rules.py \
  --outdir /home/yuzugon/rules \
  --workdir /home/yuzugon/rules \
  --rib-utc 2019-01-17T08:00 \
  --keep-rib \
  /home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
```

匿名 trace の rule は `/home/yuzugon/rules` に置けば sudo は不要。`/research/rules`
など root 権限が必要な場所に配置する場合は、Codex が sudo 実行するのではなく、
ユーザーが手元の shell で `sudo install -D -m 0644 ...` を実行する。

候補だけ確認したい場合:

```bash
python3 scripts/build_trace_rules.py --plan-only \
  /home/yuzugon/pcap/equinix-sanjose.dirA.20140320-132400.UTC.anon.pcap

python3 scripts/build_trace_rules.py --plan-only \
  --rib-utc 2016-06-28T14:00 \
  /home/yuzugon/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap

python3 scripts/build_trace_rules.py --plan-only \
  /home/yuzugon/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap
```

### 宛先 prefix 分布の集計

非匿名 trace 本体の宛先 IPv4 prefix 分布は、routing rule や cache simulator を通さずに
`scripts/analyze_dst_prefix_distribution` で集計できます。出力は packet count ベースで、
`/8`, `/16`, `/24`, `/32` ごとの full CSV、top-N SVG plot、summary Markdown/CSV、
concentration CSV を作ります。

`/research/trace` は root 権限でしか読めないことがあるため、通常は `sudo` が必要です。
Codex 側では sudo 実行せず、必要なコマンドをユーザーに渡して手元の shell で実行してもらいます。

```bash
cd /home/yuzugon/osada-ppc-simulator

sudo ./scripts/analyze_dst_prefix_distribution \
  --trace /research/trace/2025-09-27.pcap \
  --prefix-lengths 8,16,24,32 \
  --output-dir scripts/reports/dst_prefix_distribution/2025-09-27

sudo ./scripts/analyze_dst_prefix_distribution \
  --trace /research/trace/2025-12-27.pcap \
  --prefix-lengths 8,16,24,32 \
  --output-dir scripts/reports/dst_prefix_distribution/2025-12-27

sudo ./scripts/analyze_dst_prefix_distribution \
  --trace /research/trace/2026-03-27.pcap \
  --prefix-lengths 8,16,24,32 \
  --output-dir scripts/reports/dst_prefix_distribution/2026-03-27

./scripts/compare_dst_prefix_distribution \
  --input 2025-09-27=scripts/reports/dst_prefix_distribution/2025-09-27 \
  --input 2025-12-27=scripts/reports/dst_prefix_distribution/2025-12-27 \
  --input 2026-03-27=scripts/reports/dst_prefix_distribution/2026-03-27 \
  --top-n 20 \
  --output-dir scripts/reports/dst_prefix_distribution
```
















## メモ

ルーティングテーブルのルールは.ruleでruleディレクトリ以下

go tool pprof -http=localhost:8080 cpu.prof

キャッシュ実装の解説: [cache/CACHE_OVERVIEW.md](cache/CACHE_OVERVIEW.md)
UnifiedCache 実装解説: [docs/cache/UnifiedCache.md](docs/cache/UnifiedCache.md)

## exec.sh の使い方

`exec.sh` は「デフォルト値 < `--config` の `.env` < CLI オプション」の順で設定を解決します。

### 1. 実験設定ファイルを作る

`simulator-settings/exp/*.env` に実験条件を書きます。

例: `simulator-settings/exp/full-lru-20260327.env`

```bash
RULEFILE="/home/yuzugon/rules/wide.rib.20240625.1400.unique.rule"
TRACES=(
  "/home/yuzugon/pcap/202603271400.pcap"
)

CACHE_TYPE="FullAssociativeLRUCache"
CAPACITY_START=10
CAPACITY_END=15
CAPACITY_STEP=1
```

### 2. 実行する

```bash
./exec.sh --config simulator-settings/exp/full-lru-20260327.env
```

匿名化 trace と `/home/yuzugon/rules` の rule だけを使う設定では sudo は不要です。

```bash
./exec.sh --config simulator-settings/exp/full-lru-20260327.env --no-sudo
```

### 3. 一部だけ CLI で上書きする

```bash
./exec.sh --config simulator-settings/exp/full-lru-20260327.env --capacity-start 12 --capacity-end 13
```

### 4. 実行せずコマンドだけ確認する

```bash
./exec.sh --config simulator-settings/exp/full-lru-20260327.env --dry-run --no-build
```

### よく使うオプション

- `--trace <path>`: 複数回指定可能
- `--cachetype <name>`
- `--way <int|full>` (`UnifiedCache` では `full` で capacity ごとに full associative)
- `--cache-index-type <int>`
- `--cache-index-types "<0,1,2,...>"` (`.env` で sweep したいとき)
- `--cache-tag-length "/24"`、`"<min-max>"`、または `"<min-max,min-max,...>"`（1個指定は全 way 共通）
- `--cache-insertion-policy <exclusive|inclusive>`: UnifiedCache の leaf-only 挿入ゲートを使うか、non-leaf も最大 tag length で挿入するか
- `--capacity-start/end/step`
- `--refbits-start/end/step`
- `--cachenum <int>`
- `--skip <int>`
- `--max <int>`
- `--dbupdate` / `--no-dbupdate`
- `--bench` / `--no-bench`
- `--record-cache-hit` / `--no-record-cache-hit`
- `--logip` / `--no-logip`
- `--logip-top <int>`: UnifiedCache の second miss IP/prefix 上位件数（default: 100）
- `--logip-output-dir <path>`: second miss IP/prefix CSV の出力先
- `--dram-request-trace-dir <path>`: DRAM 電力評価用の request-level CSV 出力先
- `--sudo` / `--no-sudo`
- `--no-build`
- `--help`

`UnifiedCache` の初期値:

- `WAY=4`
- `CACHE_TAG_LENGTH="9-24"`
- `CACHE_INDEX_TYPE=5`
- `CACHE_INSERTION_POLICY="exclusive"`
- `CACHE_INDEX_TYPES=""`（空で単一実行、例: `"0,1,2,3,4,5"` で sweep）
- `CAPACITY_START=10`, `CAPACITY_END=10`（capacity=1024）

`UnifiedCache` の index type は、`116` なら top `/16` no-hash direct index、
`20816` なら DstIP のMSB基準 bit `8..23` をno-hash direct index、`30816` なら
同じbit窓をxor-fold、`40816` なら同じbit窓をCRC32にする。中央寄りのbitを試す例:
`CACHE_INDEX_TYPES="116,118,20816,21212,30816,40816"`。


## 長田さんメモ

・環境
windows 10
GoLang ver.1.22.5

・コンパイル方法
このファイルがあるパスで下記コマンドを実行
go build main.go
生成されたmain.exeが実行ファイル

・実行方法
下記コマンドを上記パスで実行
main.exe ほげ.json ふが.txt
ほげ.jsonはキャッシュ構成のコンフィグファイル(test2.jsonがサンプル,長田の提案手法の構成)
	長田の提案手法のキャッシュ(multi_layer_cache_*)は、"Rule"でルーティング情報が書かれているファイルを指定する必要があります(zisaku_rule.txtがサンプル)
ふが.txtはネットワークトレースのファイル
	pcapからテキストに変換してください(zisaku.txtがサンプル)

・注意
routingtable.go内のCalTreeDepth()が未完成です。
理想：LPC trieに格納したときの高さ
現在：二分木に格納したときの高さ
