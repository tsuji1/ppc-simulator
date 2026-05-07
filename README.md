# README.md


## aloheart



### データ


#### ルール
/research/rulesにルールが存在し、普通の権限で読める
/research/rules/wide.rib.20240625.1400.unique.rule
/research/rules/rib.20260327.0600.unique.rule
/research/rules/rib.20251227.0600.unique.rule
/research/rules/rib.20160628.1200.bz2
/research/rules/rib.20250927.0600.unique.rule


#### トレース



/research/traceにトレースデータが存在する.root権限でしか読めない
/research/trace/wget-log
/research/trace/2025-12-27.pcap.xz
/research/trace/2025-09-27.pcap.zst
/research/trace/202509271400.pcap
/research/trace/202512271400.pcap.gz
/research/trace/2025-12-27.pcap
/research/trace/2026-03-27.pcap.xz
/research/trace/202603271400-anon.pcap
/research/trace/2025-09-27.pcap
/research/trace/202512271400.pcap
/research/trace/2026-03-27.pcap

anonとついているものは匿名化されている.また1400(jst)など時刻が付いているものは匿名化されているものである.
















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
RULEFILE="/research/rules/wide.rib.20240625.1400.unique.rule"
TRACES=(
  "/research/trace/2026-03-27.pcap"
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
- `--way <int>`
- `--cache-index-type <int>`
- `--cache-index-types "<0,1,2,...>"` (`.env` で sweep したいとき)
- `--cache-tag-length "<min-max,min-max,...>"`
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
- `--sudo` / `--no-sudo`
- `--no-build`
- `--help`

`UnifiedCache` の初期値:

- `WAY=4`
- `CACHE_TAG_LENGTH="9-24,9-24,9-24,9-24"`
- `CACHE_INDEX_TYPE=5`
- `CACHE_INDEX_TYPES=""`（空で単一実行、例: `"0,1,2,3,4,5"` で sweep）
- `CAPACITY_START=10`, `CAPACITY_END=10`（capacity=1024）


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
