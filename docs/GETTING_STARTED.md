# 利用・引き継ぎガイド

この文書は、初めてリポジトリを受け取った人が環境を用意し、シミュレーションを実行して結果を確認するためのガイドです。

## 1. このリポジトリでできること

IPv4 の宛先アドレスを routing table に照合し、その lookup 結果をキャッシュした場合の hit/miss を評価します。主な方式は次のとおりです。

- `UnifiedCache`: 可変長 prefix を保持する set-associative cache
- `LRU` / `FullLRU`: LRU cache
- `MultiLayerCacheExclusive` / `MultiLayerCacheInclusive`: multi-layer cache

UnifiedCache では index の計算方式、挿入ポリシー、adaptive index、set extension などを指定できます。request-level DRAM trace を CSV に出力するオプションもあります。

## 2. 必要なもの

- Go **1.24.2 以降**（`go.mod` のバージョン指定）
- MongoDB（結果をDB登録する場合のみ。`-mongodb=false` なら不要）
- 評価対象の routing table rule file（`.rule`）
- 評価対象の packet trace（`.pcap` または対応する text/CSV/TSV）

trace と routing table はサイズ、利用条件、個人情報などを考慮してリポジトリに含めていません。利用者が入手・使用許可を確認したデータを別途用意してください。共有時は、元データや実験結果を Git に追加しないでください。

## 3. セットアップ

MongoDB を使って結果を保存する場合は、リポジトリのルートでローカル設定を作成します。

```bash
cp .env.example .env
```

MongoDB を使って結果を保存する場合は、`.env` の `DATABASE_URL` を接続 URI に合わせます。既定の例はローカル MongoDB 向けです。MongoDB を使わない場合、`.env` の作成や MongoDB の起動は不要です。実行時に `-mongodb=false` を指定すると、DBへの接続、既存結果の検索、結果登録をすべてスキップします。

MongoDB を使わない場合、この `.env` 作成手順は飛ばせます。どちらの場合も依存関係を取得し、ビルドします。

```bash
go mod download
mkdir -p bin
go build -o bin/osada-ppc-simulator .
```

`.env` はローカル設定として Git 管理対象外です。MongoDB を使う人には `.env.example` を渡して接続先を設定してもらってください。MongoDB を使わない実行では `-mongodb=false` を指定してください。

## 4. 入力ファイル

実行には rule file と trace の両方が必要です。

```bash
RULEFILE=/path/to/your-routing-table.unique.rule
TRACE=/path/to/a-small-trace.pcap
```

対応拡張子や parser は `main.go` を参照してください。主な入力形式は `.pcap` と、`.csv` / `.tsv` / `.txt` / `.data` / `.p7` の区切りテキストです。text trace はこのプロジェクトの parser が読める列構成である必要があります。

入力は起動時に読み込まれ、packet を内部形式へ変換します。初回は変換済み packet を `gob-packet/` に保存し、次回から再利用します。保存先を変える場合は `.env` の `GOB_PACKET_DIR` を設定してください。変換データは trace と同じ程度に大きくなることがあるため、ディスクに余裕のある場所を選んでください。

## 5. 最初のシミュレーション

まずは小さな trace または短く切り出した trace で動作を確認します。

```bash
./bin/osada-ppc-simulator \
  -rulefile "$RULEFILE" \
  -trace "$TRACE" \
  -cachetype UnifiedCache \
  -capacity-values 1024 \
  -way 4 \
  -cache-index-type 5 \
  -cache-tag-length 9-24 \
  -max 100000 \
  -mongodb=false
```

`-max` はシミュレーションで処理する packet 数を制限します。入力ファイル全体の読み込みと初回 `.gob` 生成はその前に行うため、非常に大きい trace の動作確認では、小さな trace ファイルを用意してください。

`-mongodb=false` を外すと既定動作に戻り、MongoDB に接続して既存結果を検索し、必要に応じて結果を登録します。同じ条件の結果を強制更新するには `-dbupdate` を指定します。容量を対数範囲で指定する場合は、例えば `-capacity-start 10 -capacity-end 15` とします（1024 から 32768）。`-capacity-values` は実際の容量を直接指定します。

## 6. よく使う UnifiedCache オプション

| オプション | 用途 |
| --- | --- |
| `-mongodb=false` | MongoDB 接続、既存結果検索、結果登録を無効にする |
| `-way 8` / `-way full` | associativity。`full` は全 entry を1セットにする |
| `-cache-index-type 5` | set index の計算方式 |
| `-cache-tag-length 9-24` | cache に保持する prefix length の範囲 |
| `-cache-insertion-policy exclusive` | `exclusive` または `inclusive` の挿入方式 |
| `-cache-index-policy fixed` | `fixed`、`last-inserted-prefix`、`epoch-most-frequent-prefix` |
| `-set-extension-policy off` | `off` または `epoch-full-repeat-miss` |
| `-logip` | second miss の宛先 prefix/IP 集計 CSV を出力 |
| `-loglength` | resident entry の prefix length 集計 CSV を出力 |
| `-dram-request-trace-dir DIR` | request-level DRAM trace CSV の出力先 |
| `-csv-output-dir DIR` | MongoDB 無効時の結果 CSV 出力先（既定: `output/csv`） |

index type の定義、adaptive index や set extension の全オプションと挙動は [UnifiedCache 実装メモ](cache/UnifiedCache.md) を参照してください。すべての CLI オプションは `./bin/osada-ppc-simulator -h` で確認できます。

request-level DRAM trace の CSV は DRAMPower 等の入力形式へ変換する前段のログです。DRAMPower が直接読める command trace ではありません。詳しくは [DRAM 電力評価への統合計画](dram-power-integration-plan.md) を参照してください。

## 7. 結果と生成物

- シミュレーションの要約・統計: MongoDB の `db.simulator_results`
- MongoDB を無効にした実行結果: `output/csv/`
- packet 変換キャッシュ: `gob-packet/`（`GOB_PACKET_DIR` で変更可能）
- 解析スクリプトの既定出力: `scripts/reports/` や `scripts/results/`
- `-logip` / `-loglength` / `-dram-request-trace-dir`: 指定した出力先

入力データ、変換済み `.gob`、バイナリ、`.env`、レポート、図表、CSV の実験出力は `.gitignore` で除外しています。結果を他の人と共有する場合は、必要なレポートだけを選び、入力データの共有条件を確認してください。

MongoDB 無効時は、1回の起動につき実行時刻とランダムIDを組み合わせた実行IDを作り、次のファイルを出力します。容量スイープの順序は容量の昇順です。

```text
output/csv/20261002T153000-a1b2c3d4_summary.csv
output/csv/20261002T153000-a1b2c3d4_unified_prefix_stats.csv
```

`summary.csv` は設定ごとに1行で、容量、way、index type、処理数、hit/miss、hit rate、実行時間を記録します。全パラメータと詳細統計もJSON列に格納します。`unified_prefix_stats.csv` はUnifiedCache用で、prefix lengthごとのhit・first/second miss・exclusive拒否数などを縦持ちで記録します。UnifiedCache以外ではsummaryのみを作ります。`-csv-output-dir` で保存先を変更できます。各行には複数条件をまたいで照合できる `run_id` も入ります。

## 8. 解析ツール

- Go の解析コマンド: `cmd/`。各コマンドに対応するディレクトリ内の README を参照してください。
- 実験・集計・描画スクリプト: `scripts/`。スクリプト先頭の shebang やコメントに記載された依存関係を確認してください。
- `scripts/analyze_dst_prefix_distribution` と `scripts/windowed_hitrate` は、必要に応じて Go コマンドを一時ディレクトリへビルドして実行する wrapper です。

一部の Python スクリプトは `uv run --script` を使います。Python 依存関係や入力ファイルは各スクリプトの引数・先頭コメントを確認してください。

## 9. 開発時の確認

```bash
gofmt -w main.go cache/*.go db/*.go memorytrace/*.go simulator/*.go
go test ./...
```

テストごとに MongoDB や外部 fixture などの要件が異なる場合があります。実行前に各テストと CI 設定を確認してください。大きな trace の実行は時間・メモリ・ディスクを使うため、まず小規模データで確認してください。

## 10. ディレクトリ案内

| パス | 内容 |
| --- | --- |
| `cache/` | 各種 cache と UnifiedCache |
| `memorytrace/` | DRAM request trace の記録 |
| `simulator/` | cache simulator と統計 |
| `routingtable/` | routing table の読み込みと検索 |
| `db/` | MongoDB への結果保存 |
| `cmd/` | 個別の解析コマンド |
| `scripts/` | 実験、集計、描画用ツール |
| `docs/` | 利用ガイドと設計資料 |
