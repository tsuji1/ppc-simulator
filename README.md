# osada-ppc-simulator

IPv4 ルーティング検索用キャッシュを評価する Go シミュレータです。入力トレースをルーティングテーブルと照合し、複数のキャッシュ構成について hit/miss 統計を計測します。UnifiedCache、LRU、multi-layer cache を扱えます。

## はじめて使う方へ

セットアップ、入力データの準備、実行例、結果の見方は [利用・引き継ぎガイド](docs/GETTING_STARTED.md) を参照してください。トレースや routing table はリポジトリに含めていません。

最小限の準備は次のとおりです。

```bash
# MongoDB を利用する場合だけ作成
cp .env.example .env
go mod download
go build -o bin/osada-ppc-simulator .
```

MongoDB を使う場合は `.env` の `DATABASE_URL` を接続先に合わせます。MongoDB を使わない場合は、実行時に `-mongodb=false` を指定します。どちらの場合も trace と `.rule` は別途必要です。

## 主なドキュメント

- [利用・引き継ぎガイド](docs/GETTING_STARTED.md): セットアップ、実行、出力、トラブルシューティング
- [UnifiedCache 実装メモ](docs/cache/UnifiedCache.md): UnifiedCache の構成と各種ポリシー
- [DRAM 電力評価への統合計画](docs/dram-power-integration-plan.md): request-level DRAM trace と今後の連携方針

## 開発

```bash
gofmt -w main.go cache/*.go db/*.go memorytrace/*.go simulator/*.go
go test ./...
```

シミュレーション結果や入力データを含めず、ソースコードと再現用の解析ツールを Git で管理します。`.gitignore` により、ローカルデータ、実験出力、バイナリ、環境設定ファイルは通常の `git add` 対象から除外されます。
