# cache/ 実装キャッシュ解説

このディレクトリには、`Cache` インターフェースを実装した複数のキャッシュ方式が入っています。  
基本操作は共通で、`IsCached*`（参照）、`CacheFiveTuple`（挿入）、`InvalidateFiveTuple`（無効化）、`Stat`（統計）です。

## 1. 共通モデル

- キーは主に `FiveTuple`（`Proto/SrcIP/DstIP/SrcPort/DstPort/IsLeafIndex`）。
- `FiveTuple()` は実質 `TCP/UDP` のみ対象（それ以外は `nil` を返す）。
- 置換時は `CacheFiveTuple` が `evicted` エントリ（追い出し）を返す設計。
- 多くの実装で `Clear()` は未実装（`panic`）。

## 2. 単層キャッシュ（Full-Associative）

## 2.1 `FullAssociativeLRUCache`
- ヒット時（`update=true`）: エントリを先頭へ移動。
- ミス時: 末尾（最古）を追い出して先頭へ挿入。
- 典型的な LRU。

## 2.2 `FullAssociativeLFUCache`
- ヒット時: 参照回数 `Refered` を増やし、頻度順になるようリスト位置を調整。
- ミス時: 末尾（最小頻度）を追い出し、新規を頻度0/1帯に挿入。
- 典型的な LFU（リスト再配置型）。

## 2.3 `FullAssociativeFIFOCache`
- ヒットしても順序は更新しない（挿入順維持）。
- ミス時: 最古挿入を追い出し。

## 2.4 `FullAssociativeRandomCache`
- 満杯時、ランダム位置を選んで追い出す。
- 置換ポリシーは完全ランダム。

## 2.5 `FullAssociativeTreePLRUCache`
- 木ビット（擬似LRU）で追い出し候補を決定。
- ヒットで木ビット更新、ミスで木を辿って victim を決定。
- 制約: サイズは `8` または `16` のみ。

## 2.6 `FullAssociativeDstipNbitLRUCache`（1-tuple/Nbit）
- 宛先IPを `Refbits` 長でマスクしてキー化（プレフィックス単位）。
- 本質は「DstIPプレフィックス単位の LRU」。
- `debugMode` 時はルーティングテーブルの `NextHop` 一貫性チェックあり。

## 3. セット連想キャッシュ（N-way）

各 `NWaySetAssociative*` は「セット選択 + 各セット内 Full-Associative」の構造です。

## 3.1 `NWaySetAssociativeLRUCache`
- セット内: `FullAssociativeLRUCache`
- セット選択: FiveTuple 全体のバイト列を `binary.BigEndian.Uint32(...) % numSets`
- 特記事項: ルーティングテーブルはコンストラクタ引数で受け取る（固定ルールファイル依存なし）。

## 3.2 `NWaySetAssociativeLFUCache` / `FIFOCache` / `RandomCache` / `TreePLRUCache`
- セット内: 各方式の Full-Associative 実装。
- セット選択: 基本は `(SrcIP ^ DstIP) % numSets`。
- `TreePLRU` は `way` が `8` または `16` 制約。

## 3.3 `NWaySetAssociativeDstipNbitLRUCache`
- セット内: `FullAssociativeDstipNbitLRUCache`。
- セット選択: 「マスク済みDstIP」を CRC32 して `% numSets`。
- `MultiLayerCacheInclusive` 配下で使われると挿入/置換統計を親へ反映。

## 4. マルチレイヤ系

## 4.1 `MultiLayerCache`（汎用）
- 複数層キャッシュ + ポリシー（`WriteThrough`, `WriteBackInclusive`, `WriteBackExclusive`）。
- ヒット時、上位層再配置や下位層更新をポリシーに応じて処理。
- 挿入時、追い出しエントリを次層へ伝搬する設計。

## 4.2 `MultiLayerCacheExclusive`
- ルーティング木の葉判定（`isLeaf`）を使って「どの層へ入れるか」を決定。
- 基本は1層選択挿入（該当層のみ挿入）で統計を収集。
- `MatchMap`/`LongestMatchMap`/`DepthSum`/`Inserted` など詳細統計を持つ。

## 4.3 `MultiLayerCacheInclusive`
- `Exclusive` 系の統計を持ちつつ、条件成立時に上位層へも派生挿入（inclusive）するロジックあり。
- `OnceCacheLimit`、`GroupChildPrefixesByRefBits` を使って上位層投入範囲を制御。
- 追い出された要素が下位層に残る場合は `Invalidate` で整合を取る実装。

## 4.4 `DebugCache`
- `Exclusive` に近い挙動で、プレフィックス長や葉判定分布の観測を目的にした診断用キャッシュ。
- 命中率だけでなく「どの長さのprefix/leafがどれだけ来たか」を集計。

## 5. Unified 系

## 5.1 `UnifiedCache`
- セット連想の枠組みで、各セットが `UnifiedCacheLine`。
- インデックス方式を切替可能:
  - `DIRECT`
  - `HASH`
  - `IDEAL`
  - `PREFIX24 / PREFIX20 / PREFIX18`
- `cacheTagLength`（wayごとの許容プレフィックス長範囲）を見て「そのエントリをキャッシュしてよいか」を判定。

## 5.2 `UnifiedCacheLine`
- キーは「DstIPのマスク値（prefix長可変）」。
- ヒット判定は「登録済み各prefix長でマスクして一致するか」を探索。
- ヒット時:
  - LRU更新
  - `HitCount[length]` 増加
- ミス時:
  - 初回/2回目以降ミスを `FirstMissCount` / `SecondMissCount` として分離集計
  - 置換時は末尾追い出し + 先頭挿入

## 6. ラッパー

## `CacheWithLookAhead`
- `InnerCache` を包むデコレータ。
- `TCP` エントリ挿入時、逆方向5タプル（src/dst swap）も先読みで挿入する。
- 双方向通信を早期にヒットさせる狙い。

## 7. 実装上の注意点

- `Clear()` / `InvalidateFiveTuple()` が未実装（`panic`）のクラスが複数ある。
- 方式ごとにセットインデックス関数が異なるため、同一トレースでも衝突特性が変わる。
- `TreePLRU` はサイズ制約が強い（Fullは8/16、N-wayはway 8/16）。
- `FiveTuple()` が `TCP/UDP` 前提なので、他プロトコルはキャッシュ対象外になり得る。
- `NWaySetAssociativeLRUCache` はルーティングテーブル未指定（`nil`）で生成すると `panic` する。
