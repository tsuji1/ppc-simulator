# osada-ppc-simulator DRAM power integration plan

## 目的

`osada-ppc-simulator` の現在の主な出力は cache hit rate、miss count、UnifiedCache の first/second miss 統計である。
これは cache の有効性を見るには十分だが、DRAM 電力を評価するには情報が足りない。

DRAMPower や Micron calculator に接続するには、少なくとも次を分けて扱う必要がある。

- cache hit で終わったアクセス
- cache miss により DRAM/FIB/外部メモリ参照が発生したアクセス
- そのアクセスが発生した cycle
- 後段の address mapping に渡せる論理 address
- read/write 種別
- miss の理由
- packet/routing context

この文書では、DRAM 電力評価へ進むために `osada-ppc-simulator` 側で必要な改善と、今回入れた初期実装をまとめる。

## 現状の不足

### 1. miss count だけでは DRAM command に落とせない

現在の DB 結果は hit/miss や UnifiedCache の集計が中心である。
しかし DRAM の動的電力は単純な `misses * constant` では決まらない。

本来は次の要素が必要になる。

- 同じ row への連続アクセスか
- bank / bank group / rank がどう分散するか
- ACT/PRE が何回必要か
- RD/WR が何回発生するか
- refresh と background の固定成分をどう足すか
- trace duration に対して電力へ正規化するか

そのため、simulator からは「集計値」だけでなく「時系列の memory request trace」を出せる必要がある。

### 2. 既存 `memorytrace` は未接続に近い

`memorytrace` package は存在していたが、主な問題があった。

- `SimpleCacheSimulator.Process()` では cycle counter だけが進み、DRAM access は記録されていなかった
- `lpctrie.GetDepth()` の `memorytrace.AddDRAMAccess()` はコメントアウトされていた
- 出力形式が `0x... R` のみで、cycle / miss reason / packet context がない
- 大規模 trace で全アクセスをメモリに保持すると危険

したがって、まず request-level trace を streaming CSV で出す仕組みが必要である。

### 3. 物理 DRAM address mapping はまだ別段階

router の cache miss が参照する対象は、パケット payload ではなく routing/FIB/cache metadata である。
現時点で simulator は実DRAM物理アドレスを持っていない。

したがって今回の初期実装では、宛先 IP の局所性を残した論理 address を出す。
この論理 address を後段で `rank/bank_group/bank/row/column` に変換し、DRAMPower command trace を作る。

## 改善方針

### Layer 0: 集計値

既存の hit rate / miss count / first miss / second miss を維持する。
これは cache policy の比較と、電力評価の sanity check に使う。

### Layer 1: request-level trace

cache miss が発生したとき、次の CSV を出す。

```text
cycle,sequence,op,address,cache_hit,miss_type,source,src_ip,dst_ip,proto,src_port,dst_port,is_leaf_index
```

この trace はまだ DRAMPower の command trace ではない。
DRAMPower に入れる前の「メモリ要求列」である。

### Layer 2: address mapping

request-level trace の `address` を次へ変換する。

```text
rank,bank_group,bank,row,column
```

ここで評価したい仮定を切り替える。

- DstIP locality を row locality として残す
- hash mapping で bank 分散を強める
- prefix 長や leaf index を row/bank に反映する

### Layer 3: controller scheduling

address mapping 後の request を DRAM command に変換する。

- close-page policy
- open-page policy
- FR-FCFS
- refresh insertion
- read/write turn-around

この出力が DRAMPower の `ACT/RD/WR/PRE/REFA/END` CSV になる。

## 今回実装した範囲

今回の branch では Layer 1 の足場を入れた。

- `memorytrace.Tracer` を request-level CSV streaming に対応
- `SimpleCacheSimulator.Process()` で cache miss 時に DRAM request を記録
- `-dram-request-trace-dir <dir>` CLI flag を追加
- DB に既存結果がある場合でも、trace flag があれば再実行して CSV を作る
- trace はメモリに溜めず、CSV へ streaming する

出力例:

```bash
./main \
  -rulefile rules/example.rule \
  -trace traces/example.pcap \
  -cachetype UnifiedCache \
  -capacity-start 10 \
  -capacity-end 10 \
  -way 8 \
  -cache-index-type 5 \
  -dram-request-trace-dir scripts/reports/dram_request_traces
```

出力 CSV は `scripts/reports/dram_request_traces/` 以下に生成される。

## 今回の論理 address

今回の `address` は実物理アドレスではない。

生成方針:

- 上位側に `DstIP` を残す
- 下位 16 bit に flow signature を入れる
- flow signature は `SrcIP, Proto, SrcPort, DstPort` の FNV-1a hash

意図:

- 宛先 prefix の局所性を後段の row locality へ渡せる
- 同じ DstIP でも flow が違う場合に少し分散する
- 後段で別の address mapping を試せる

## 次に必要な改善

### 1. request trace から DRAMPower trace への変換器

`cycle,address,op` を入力として、DRAMPower の command CSV を生成する。

最初は close-page policy でよい。

```text
ACT -> RD -> PRE
```

その後、row-hit を活かす open-page policy や FR-FCFS を追加する。

### 2. address mapping の設定化

次を CLI / JSON で切り替えられるようにする。

- rank 数
- bank group 数
- bank 数
- row bit
- column bit
- cache line / burst size
- DstIP locality を row に残すか、hash で散らすか

### 3. DRAM state residency の計算

DRAMPower の command energy だけでなく、background/static 成分も扱う。

- active standby
- precharge standby
- refresh
- self refresh / power down を使う場合の residency

cache hit rate が改善しても、background と refresh はそのまま残る。
この分離がないと、cache による電力削減を過大評価する。

### 4. packet rate による電力正規化

同じ request trace でも、処理時間をどう置くかで power が変わる。

必要な出力:

- energy per packet
- energy per miss
- power at fixed packet rate
- power at measured trace duration

### 5. read/write の精密化

現時点では cache miss を DRAM read として出す。
今後、dirty writeback や table update をモデル化する場合は write を追加する。

## まとめ

`osada-ppc-simulator` 側で最初に必要なのは、DRAMPower command を直接吐くことではない。
まず cache miss から生じる memory request を、cycle と address context 付きで保存することである。

今回の実装で `-dram-request-trace-dir` が追加され、DRAMPower 変換器へ渡す前段の trace を生成できるようになった。
次は、この CSV を input にして address mapping と controller scheduling を行う converter を追加する。
