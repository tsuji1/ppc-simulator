# UnifiedCache 実装メモ

このドキュメントは、現行コードの `UnifiedCache` 実装を対象にした技術メモです。

- 実装本体: `cache/unified_cache.go`
- 1セット実装: `cache/unified_cache_cacheline.go`
- ビルド/配線: `simulator/simple_cache_simulator.go`, `main.go`

## 1. 概要

`UnifiedCache` は「セット連想 + 可変プレフィックス長キャッシュ」を組み合わせた実装です。

- 全体容量 `Size`
- way 数 `Way`
- セット数 `numSets = Size / Way`
- 各セットは `UnifiedCacheLine` が担当
- キーは最終的に `DstIP` のマスク値（prefix 長はエントリごとに可変）

通常の固定長タグ方式と違い、`cacheTagLength` により「どの prefix 長で保持するか/保持できるか」を制御します。

## 2. データ構造

## 2.1 UnifiedCache

主なフィールド:

- `Sets []UnifiedCacheLine`: セット本体（長さは `Size/Way`）
- `Way`, `Size`
- `CacheIndexType`: セットインデクス計算方式
- `cacheTagLength [][2]int`: way ごとの許容 prefix 範囲
- `RoutingTable`: 最長一致検索に利用
- `DepthSum`: 参照パケットの深さ統計

## 2.2 UnifiedCacheLine

1セット内の置換管理を行います。

- `Entries map[uint32]*list.Element`: キーはマスク済み `DstIP`
- `evictList *list.List`: 先頭が新しい、末尾が追い出し対象
- `Size`: セット容量（= `Way`）
- `HitCount`, `FirstMissCount`, `SecondMissCount` などの統計

`evictList` は初期化時にダミー要素で `Size` 個埋められます。

## 3. アクセスフロー

## 3.1 ヒット判定 (`IsCachedWithFiveTuple`)

1. `setIdx()` でセットを選択
2. セット内 `Entries` を走査
3. エントリごとの `Length` で `DstIP` をマスクし、キー一致でヒット
4. `update=true` の場合は LRU 更新（先頭へ移動）と `HitCount[length]` 加算を行う

## 3.2 挿入 (`CacheFiveTuple`)

### トップレベル (`UnifiedCache.CacheFiveTuple`)

1. ルーティングテーブルで最長一致検索
2. `DepthSum` 更新
3. `cacheTagLength` 条件 (`isLeaf`) を満たすか判定
4. 満たす場合のみ該当セットへ挿入

満たさない場合は挿入せず終了します（返り値は空）。

### セット内 (`UnifiedCacheLine.CacheFiveTuple`)

1. 既存ヒットなら何も追い出さず終了
2. 使う `cacheLength` を決定
3. 末尾要素を追い出し（LRU）
4. 新規要素を先頭へ挿入
5. `Entries[maskedDstIP]` を更新

追い出しが実データだった場合のみ `evictedFiveTuples` に返します。

## 4. セットインデクス (`CacheIndexType`)

`cache/unified_cache.go` の定義:

- `0`: `DIRECT`
- `1`: `HASH`
- `2`: `IDEAL`
- `3`: `PREFIX24`
- `4`: `PREFIX20`
- `5`: `PREFIX18`

加えて、`6..24` は「そのビット長で `DstIP` を切って CRC32 ハッシュ」の特別扱いがあります。

## 5. 設定パラメータ

`main.go` の CLI で `UnifiedCache` に関連する主な項目:

- `-capacity-start/-capacity-end/-capacity-step`
- `-way`（default: `4`）
- `-cache-index-type`（default: `5`）
- `-cache-tag-length`（default: `9-24,9-24,9-24,9-24`）
- `-logip`（有効時、second miss した宛先prefix/IPの上位をCSV出力）
- `-logip-top`（default: `100`）
- `-logip-output-dir`（default: `scripts/reports/unified_second_miss_ip`）

`-cache-tag-length` は **個別指定のみ**:

- 形式: `min-max,min-max,...`
- 要素数は `way` と一致必須
- 各要素は `0 <= min <= max <= 32`

`exec.sh` からも同名オプションで `main` にそのまま転送します。
複数の index type を連続実行したい場合は `.env` に `CACHE_INDEX_TYPES=\"0,1,2,3,4,5\"` を指定できます。

## 6. 実行時制約

コンストラクタ/実行時で次を検証します。

- `size % way == 0`
- `len(cacheTagLength) == way`
- `sets_size = size/way` が 2 の冪
- `capacity % way == 0`（`main.go` 側チェック）

違反時は `panic` で停止します。

## 7. 統計

`UnifiedCache.Stat()` は以下を返します。

- `DepthSum`
- セットごとの `HitCount`
- セットごとの `FirstMissCount`
- セットごとの `SecondMissCount`

`cacheDebugFileOutputEnabled` が有効なときは、条件に応じて `debug/` 配下へ補助ログを書きます（デフォルトは無効）。

## 8. DB保存（圧縮）

MongoDB 保存時（`db.InsertResult`）は、`UnifiedCache` の大きい配列を圧縮して保存します。

- `hit_count_list_compressed`
- `first_miss_count_compressed`
- `second_miss_count_compressed`

圧縮形式は `unified_stat_encoding = "gzip+uint32le[rows][32]"` です。  
`unified_stat_rows` は行数（セット数）です。

`simulator_result.statdetail` は要約のみ（`depthsum`）を保存します。

この仕様により、`capacity` が大きいケースでもドキュメント肥大を抑えます。

## 8.1 second miss IP/prefixログ

`-logip` を付けると、DBには保存せず、シミュレーション終了時にCSVへ直接出力します。
出力対象は second miss になった宛先prefix/IPの上位 `-logip-top` 件です。

例:

```bash
./main \
  -cachetype UnifiedCache \
  -capacity-start 6 -capacity-end 14 \
  -way 8 \
  -cache-index-type 5 \
  -logip \
  -logip-top 100
```

出力先の既定値は `scripts/reports/unified_second_miss_ip/` です。
CSVには `capacity`, `way`, `cache_index_type`, `set_idx`, `prefix_len`, `network`, `second_miss_count` が入ります。

## 9. 注意点（現状実装）

- `InvalidateFiveTuple` / `Clear` は未実装の箇所があり `panic` します。
- `UnifiedCacheLine` の `Description()` は現在 `"NbitFullAssociativeDstipLRUCache"` を返します（名称不一致）。
- `debugMode=true` でのミス時チェックには `hitElem` 参照を含むため、将来的に保守時は注意が必要です。
- 実験運用では `capacity=2^10..2^13` を基本にする設定を推奨します。

## 10. 典型設定例

### UnifiedCache 既定相当

```bash
./exec.sh \
  --cachetype UnifiedCache \
  --capacity-start 10 --capacity-end 10 \
  --way 4 \
  --cache-index-type 5 \
  --cache-tag-length "9-24,9-24,9-24,9-24"
```

### way=8 の個別指定

```bash
./exec.sh \
  --cachetype UnifiedCache \
  --way 8 \
  --cache-tag-length "9-24,9-24,10-24,10-24,11-24,11-24,12-24,12-24"
```
