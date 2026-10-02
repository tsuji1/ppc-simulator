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
- キーは最終的に `DstIP` のマスク値と prefix 長（prefix 長はエントリごとに可変）

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

- `Entries map[unifiedCacheLineEntryKey]*list.Element`: キーはマスク済み `DstIP` と prefix 長
- `evictList *list.List`: 先頭が新しい、末尾が追い出し対象
- `Size`: セット容量（= `Way`）
- `HitCount`, `FirstMissCount`, `SecondMissCount` などの統計

`evictList` は初期化時にダミー要素で `Size` 個埋められます。

## 3. アクセスフロー

## 3.1 ヒット判定 (`IsCachedWithFiveTuple`)

1. `setIdx()` でセットを選択
2. セット内 `Entries` を走査
3. エントリごとの `Length` で `DstIP` をマスクし、キー一致候補を集める
4. 一致候補のうち最も長い `Length` のエントリをヒットとして扱う
5. `update=true` の場合は LRU 更新（先頭へ移動）と `HitCount[length]` 加算を行う

## 3.2 挿入 (`CacheFiveTuple`)

### トップレベル (`UnifiedCache.CacheFiveTuple`)

1. ルーティングテーブルで最長一致検索
2. `DepthSum` 更新
3. `cacheTagLength` 条件 (`isLeaf`) を満たすか判定
4. 満たす場合のみ該当セットへ挿入

満たさない場合、`exclusive` では挿入せず終了します（返り値は空）。
`inclusive` では routing table 上で `DstIP` に一致する prefix のうち、`cacheTagLength`
範囲内の prefix をそれぞれ exact length で挿入します。例えば `127.0.0.0/8` と
`127.0.0.0/24` が両方存在する場合、同じ cache line に `/8` と `/24` を別 entry
として保持できます。

### セット内 (`UnifiedCacheLine.CacheFiveTuple`)

1. 既存ヒットなら何も追い出さず終了
2. 使う `cacheLength` を決定
3. 末尾要素を追い出し（LRU）
4. 新規要素を先頭へ挿入
5. `Entries[{maskedDstIP, length}]` を更新

追い出しが実データだった場合のみ `evictedFiveTuples` に返します。

`inclusive` では、より具体的な prefix が LRU で追い出されたとき、その prefix を包含する
ancestor prefix も同じ cache line から削除します。これにより、例えば `/24` が追い出された後に
同じ宛先が古い `/8` entry へ fallback hit することを防ぎます。

## 4. セットインデクス (`CacheIndexType`)

`cache/unified_cache.go` の定義:

- `0`: `DIRECT`
- `1`: `HASH`
- `2`: `IDEAL`
- `3`: `PREFIX24`
- `4`: `PREFIX20`
- `5`: `PREFIX18`

加えて、`6..24` は「そのビット長で `DstIP` を切って CRC32 ハッシュ」の特別扱いがあります。
`116..124` は「そのビット長で `DstIP` を切り、CRC32 ハッシュせずに prefix value の
index bits を直接 set index として使う」方式です。例えば `116` は `/16` prefix
direct index、`124` は `/24` prefix direct index です。

さらに任意の連続bit窓を使う実験用に、`base + start*100 + width` 形式を使えます。
`start` は `DstIP` のMSB側を0とする開始bit、`width` は連続bit数です。

- `20000 + start*100 + width`: bit window をCRC32ハッシュせず直接set indexに使う
- `30000 + start*100 + width`: bit window をset index幅ごとにxor-foldして使う
- `40000 + start*100 + width`: bit window をCRC32ハッシュして使う

例: `20816` は bit `8..23` の16bitをno-hash direct index、`30816` は同じbit窓の
xor-fold、`40816` は同じbit窓のCRC32です。`21212` はIPアドレス中央寄りの
bit `12..23` を使います。

注意: `CacheIndexType` はセットを選ぶための index 計算方式です。`PREFIX18` は
`DstIP` の上位 `/18` を index 計算に使うという意味であり、保存する tag が 18 bit
になるという意味ではありません。電力・面積評価で CACTI に渡す tag 幅は
`cacheTagLength` の上限と prefix 長を保持する `Length` 4 bit で決まり、典型的な
`cacheTagLength=9-24,...` では `24 + 4 = 28 bit` です。

`116..124` の direct index 方式では、set index bits は tag に保存しない前提です。
そのため result viewer 側の CACTI 入力では `effective_tag_bits = max_tag_bits - log2(Size / Way)`
として扱い、CACTI key bits は `effective_tag_bits + LengthBits` になります。
例: `Size=8192, Way=8, cacheTagLength=9-24` では set 数が1024で index bits が10なので、
CACTI の prefix tag は `24 - 10 = 14 bit`、物理 tag は `14 + 4 = 18 bit` になります。

## 5. 設定パラメータ

`main.go` の CLI で `UnifiedCache` に関連する主な項目:

- `-capacity-start/-capacity-end/-capacity-step`
- `-way`（default: `4`, `full` で capacity ごとに full associative）
- `-cache-index-type`（default: `5`）
- `-cache-index-policy`（`fixed` or `last-inserted-prefix`, default: `fixed`）
- `-adaptive-index-initial`（default: `18`）
- `-adaptive-index-min/-adaptive-index-max`（default: `6/24`）
- `-adaptive-index-epoch-length`（default: `1024`）
- `-cache-tag-length`（default: `9-24`）
- `-cache-insertion-policy`（`exclusive` or `inclusive`, default: `exclusive`）
- `-logip`（有効時、second miss した宛先prefix/IPの上位をCSV出力）
- `-logip-top`（default: `100`）
- `-logip-output-dir`（default: `scripts/reports/unified_second_miss_ip`）

`-cache-tag-length` は単一指定または個別指定:

- 形式: `/N`, `N`, `min-max`, または `min-max,min-max,...`
- 要素数が1なら全 way 共通、複数なら `way` と一致必須
- 各要素は `0 <= min <= max <= 32`

`exec.sh` からも同名オプションで `main` にそのまま転送します。
複数の index type を連続実行したい場合は `.env` に `CACHE_INDEX_TYPES=\"0,1,2,3,4,5\"` を指定できます。
direct prefix index 方式を実行する場合は、例えば `CACHE_INDEX_TYPES=\"116,118,120,122,124\"`
のように指定します。
任意bit窓も同じ指定でsweepできます。例: `CACHE_INDEX_TYPES=\"116,118,20816,21212,30816,40816\"`

## 6. 実行時制約

コンストラクタ/実行時で次を検証します。

- `size % way == 0`
- `len(cacheTagLength) == 1 || len(cacheTagLength) == way`
- `sets_size = size/way` が 2 の冪
- `capacity % way == 0`（`main.go` 側チェック、`way=full` では `way=capacity`）

違反時は `panic` で停止します。

## 7. 統計

`UnifiedCache.Stat()` は以下を返します。

- `DepthSum`
- セットごとの `HitCount`
- セットごとの `FirstMissCount`
- セットごとの `SecondMissCount`
- キャッシュ全体基準の `WholeCacheFirstMissCount`
- キャッシュ全体基準の `WholeCacheSecondMissCount`
- exclusive 挿入ゲートで拒否された miss の `ExclusiveRejectedFirstMissCount`
- exclusive 挿入ゲートで拒否された repeat miss の `ExclusiveRejectedSecondMissCount`
- inclusive モードで non-leaf prefix を挿入した `InclusiveNonLeafInsertedCount`
- adaptive index 長別の lookup/観測回数、切替回数、最終 index 長
- epoch policy の完了 epoch 数、index 長別決定回数、未完了 epoch のアクセス数

`FirstMissCount` / `SecondMissCount` はセット（cacheline）ごとに既出判定するため、同じ prefix/network が別セットで初めて現れた場合も first miss として数えます。
キャッシュ全体の傾向を見る場合は、`WholeCacheFirstMissCount` / `WholeCacheSecondMissCount` を使います。
こちらは UnifiedCache 全体で同じ prefix/network を一度だけ first miss とし、2回目以降を second-or-later miss とします。

`ExclusiveRejectedSecondMissCount` は、exclusive の leaf-only 条件で挿入されなかった prefix/network が再度 miss した回数です。
これは「exclusive だから発生した可能性が高い miss」の上限指標です。実際に hit rate が上がるかは、同じ条件で `-cache-insertion-policy inclusive` を実行して比較します。

`cacheDebugFileOutputEnabled` が有効なときは、条件に応じて `debug/` 配下へ補助ログを書きます（デフォルトは無効）。

## 8. DB保存（圧縮）

MongoDB 保存時（`db.InsertResult`）は、`UnifiedCache` の大きい配列を圧縮して保存します。

- `hit_count_list_compressed`
- `first_miss_count_compressed`
- `second_miss_count_compressed`

圧縮形式は `unified_stat_encoding = "gzip+uint32le[rows][32]"` です。  
`unified_stat_rows` は行数（セット数）です。

`simulator_result.statdetail` は要約のみ（`depthsum`）を保存します。
現行形式では、要約に加えて whole-cache 基準の miss count も保存します。

- `simulator_result.statdetail.wholecachefirstmisscount`
- `simulator_result.statdetail.wholecachesecondmisscount`
- `simulator_result.statdetail.exclusiverejectedfirstmisscount`
- `simulator_result.statdetail.exclusiverejectedsecondmisscount`
- `simulator_result.statdetail.inclusivenonleafinsertedcount`

この仕様により、`capacity` が大きいケースでもドキュメント肥大を抑えます。

古い UnifiedCache ドキュメントには whole-cache カウンタが無い場合があります。
`db.IsResultExist` は UnifiedCache について `wholecachefirstmisscount` の存在も確認するため、古い結果だけがある場合は `--no-dbupdate` でも再計測して新形式を保存します。

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

## 10.1 動的set拡張（Main 8-way + Extension Set Bank）

`epoch-full-repeat-miss` は、各論理setを通常8-wayで開始し、満杯状態で同じ
prefix/networkが再度missした回数をepochごとに集計します。pressureが閾値以上の
setへ、8-entryのExtension setをpressure降順・set番号順で割り当てます。割当は
1 set/epochで、一度割り当てたExtensionはrun中に回収しません。

論理setはMainと全Extensionを通した単一LRUを持ちます。entryは物理bank IDを保持するため、
Main/Extension別のhit・writeと物理set probe数を集計できます。lookupは独立bankの並列readを
想定し、レイテンシではなく `SetProbeCount` と `ExtensionSetProbeCount` で費用を評価します。

容量方式:

- `fixed-total`: `MainSize + ExtensionSize = Size`
- `additive`: `MainSize = Size`, `TotalPhysicalSize = Size + ExtensionSize`

v1は `way=8`、`exclusive`、fixed index専用です。adaptive index、multi-probe、skewed
associative、way quota、inclusiveとは併用できません。hash indexは非2冪のMain set数を
moduloで扱えますが、direct/window-direct系は2冪set数が必要です。

```bash
./exec.sh \
  --config scripts/env/unified-set-extension-sanjose.env \
  --no-sudo \
  --capacity-values 1024,2048,4096,8192,16384 \
  --set-extension-policy epoch-full-repeat-miss \
  --set-extension-capacity-mode fixed-total \
  --set-extension-pool-ratio 0.125 \
  --set-extension-epoch-length 4096 \
  --set-extension-pressure-threshold 8 \
  --set-extension-max-per-set 2
```

実験matrixは次で実行します。

```bash
scripts/run_unified_dynamic_set_extension.sh smoke
scripts/run_unified_dynamic_set_extension.sh tuning
SELECTED_EPOCH=4096 SELECTED_THRESHOLD=8 SELECTED_MAX_PER_SET=2 \
  scripts/run_unified_dynamic_set_extension.sh full
```

MongoDBにはparameterとしてMain/Extension/総物理容量と全制御値を保存し、statdetailには
割当数、epoch別割当時系列、pool残数、pool枯渇epoch、Main/Extension hit・write、
平均算出用の総probe数と1 packetあたり最大probe数を保存します。
set別Extension数は `extension_count_by_set_compressed` に
`gzip+uint32le[items]` で格納します。

## 10.2 動的 index 長 (`last-inserted-prefix`)

`-cache-index-policy last-inserted-prefix` は、直前のキャッシュミスで実際に挿入対象に
なった prefix 長を、次の lookup から index 生成に使う1レジスタ予測器です。
機械学習や RL ではなく、lookup パスは従来どおり「上位 `/N` 抽出、CRC32、1 set 参照」
だけです。

- 初期値は `-adaptive-index-initial`（既定 `/18`）
- 観測長は `-adaptive-index-min`〜`-adaptive-index-max`（既定 `/6`〜`/24`）へ clamp
- hit、`update=false` の参照、exclusive gate で拒否された miss では更新しない
- v1 は `exclusive` insertion のみ対応
- index 長を切り替えても既存 entry は移動・flush しない
- 旧 index 長で配置された entry は、その長さが再選択されるまで到達不能になり得る

統計には index 長別 lookup 回数、選択回数、切替回数、終了時の index 長を保存します。
これは予測精度と、到達不能になる既存 entry のペナルティを含めた hit rate を評価するためです。

10万アクセスの smoke 比較:

```bash
./exec.sh --config scripts/env/unified-fixed-index-smoke.env
./exec.sh --config scripts/env/unified-adaptive-smoke.env
UV_CACHE_DIR=/tmp/uv-cache uv run --script scripts/plot_unified_adaptive_index_smoke.py
```

## 10.3 Epoch最頻prefix (`epoch-most-frequent-prefix`)

`-cache-index-policy epoch-most-frequent-prefix` は、epoch中に成功挿入されたprefix長を
集計し、次epochの最初のlookup前に最頻値をindex長として適用します。epochは
`-adaptive-index-epoch-length`回の全lookupアクセスで区切ります。

- 最初のepochは`-adaptive-index-initial`を使用
- 観測がないepochでは現在値を維持
- tie時は現在値、現在値に近い長さ、短い長さの順に優先
- 既存entryは移動・flushせず、lookupは単一setのまま
- 最終未完了epochは決定せず、途中アクセス数を統計に保存

epoch長`256,1024,4096`の100k smoke比較:

```bash
./exec.sh --config scripts/env/unified-epoch-adaptive-smoke.env
UV_CACHE_DIR=/tmp/uv-cache uv run --script scripts/plot_unified_epoch_adaptive_smoke.py
```

### UnifiedCache 既定相当

```bash
./exec.sh \
  --cachetype UnifiedCache \
  --capacity-start 10 --capacity-end 10 \
  --way 4 \
  --cache-index-type 5 \
  --cache-tag-length "9-24,9-24,9-24,9-24"
```

### exclusive/inclusive 比較

```bash
./exec.sh \
  --cachetype UnifiedCache \
  --capacity-start 6 \
  --capacity-end 14 \
  --way 8 \
  --cache-index-type 5 \
  --cache-tag-length "9-24,9-24,10-24,10-24,11-24,11-24,12-24,12-24" \
  --cache-insertion-policy exclusive \
  --dbupdate

./exec.sh \
  --cachetype UnifiedCache \
  --capacity-start 6 \
  --capacity-end 14 \
  --way 8 \
  --cache-index-type 5 \
  --cache-tag-length "9-24,9-24,10-24,10-24,11-24,11-24,12-24,12-24" \
  --cache-insertion-policy inclusive \
  --dbupdate

MPLCONFIGDIR=/tmp/matplotlib UV_CACHE_DIR=/tmp/uv-cache uv run --script scripts/plot_unified_insertion_policy_comparison.py \
  --way 8 \
  --cache-index-type 5 \
  --cache-tag-length "9-24,9-24,10-24,10-24,11-24,11-24,12-24,12-24"
```

### way=8 の個別指定

```bash
./exec.sh \
  --cachetype UnifiedCache \
  --way 8 \
  --cache-tag-length "9-24,9-24,10-24,10-24,11-24,11-24,12-24,12-24"
```

### whole-cache miss の 2^6..2^17 解析

通常比較は `2^6..2^14` を主領域とし、`2^14..2^17` は容量が大きすぎるため傾向確認用として扱います。
グラフ化では `--tail-start-exp 14` を指定し、`2^14` 以降を薄い点線で描き分けます。

追加計測は既存範囲を重複実行しないよう、足りない範囲だけを指定します。

```bash
./exec.sh \
  --config scripts/env/unified-way8-2p6-2p14.env \
  --capacity-start 15 \
  --capacity-end 17 \
  --no-dbupdate
```

初期参照ミス付近を絶対値で見る例:

```bash
MPLCONFIGDIR=/tmp/matplotlib UV_CACHE_DIR=/tmp/uv-cache uv run --script scripts/plot_unified_miss_ratio_2p6_2p14.py \
  --start-exp 6 \
  --end-exp 17 \
  --miss-scope whole-cache \
  --plot-unit absolute \
  --ymin 0 \
  --ymax 10000 \
  --tail-start-exp 14 \
  --way 8 \
  --cache-index-type 5 \
  --output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p17_y0_10000_tail14.png \
  --csv-output scripts/unified_whole_cache_first_second_miss_counts_way8_index5_2p6_2p17_y0_10000_tail14.csv
```
