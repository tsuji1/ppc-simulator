# scripts

この README には、今のところ ClassBench・FlowBench で合成 trace を作るためのスクリプトだけをまとめている。
ほかのスクリプトの使い方は、各スクリプト冒頭の docstring と `--help` を見る。

<!-- toc -->
- [ClassBench・FlowBench で合成 trace を作る](#classbenchflowbench-で合成-trace-を作る)
  - [全体の流れ](#全体の流れ)
  - [必要なツール](#必要なツール)
  - [共通の入力：FIB の rule file](#共通の入力fib-の-rule-file)
  - [共通の出力：simulator の trace](#共通の出力simulator-の-trace)
  - [ClassBench](#classbench)
  - [FlowBench](#flowbench)
  - [制約と注意点](#制約と注意点)
<!-- /toc -->

## ClassBench・FlowBench で合成 trace を作る

ClassBench・FlowBench の rule 生成器（`db_generator` など）は使わない。
実 FIB をそのまま rule set として各ツールに渡し、trace（宛先の列）だけを作らせる。
経緯と結果は issue [#83](https://github.com/tsuji1/research-routing-table-cache/issues/83)（private）にある。

### 全体の流れ

```
RIB（Route Views）
  │ wide_rib_to_rule.py
  ▼
rib.YYYYMMDD.HHMM.unique.rule ─────────────────────────────┐
  │                                                         │
  │ rule_to_classbench.py                                   │ fib_to_flowbench.py
  ▼                                                         ▼
*.cb（5-tuple filter、重なりあり）                          *.fb（1 field、重なりなし）+ *.fb.map
  │ trace_generator（ClassBench）                           │ flowbench-trace --isolated（FlowBench）
  ▼                                                         ▼
*.cbtrace                                                   *.fbtrace
  │ classbench_trace_to_sim.py                              │ flowbench_trace_to_sim.py
  ▼                                                         ▼
simulator の trace（7 列 CSV）                              simulator の trace（7 列 CSV）
                                                            │ flowbench_widen_dst.py（任意）
                                                            ▼
                                                            宛先を到達領域全体に広げた trace
```

### 必要なツール

| ツール | 取得元 | build |
|---|---|---|
| ClassBench | [jafingerhut/classbench](https://github.com/jafingerhut/classbench) に local patch（seed 引数、`MAXFILTERS` を 13 万→400 万）。patch は aloheart の `~/tools/classbench`（commit 3f46e6f）にしかない | `cd trace_generator && make` |
| FlowBench | [tsuji1/Flow-Bench](https://github.com/tsuji1/Flow-Bench) の branch `routing-fib`（`--isolated` と FIB 向けのバグ修正）。入力検査付きは branch `verify-isolated` | `cd source && g++ -std=c++17 -O2 trace_generator.cpp -o flowbench-trace` |

元の ClassBench は filter が 13 万を超えると黙って切り捨て、元の FlowBench は FIB 全体を isolation できない。
FIB を入れるときは、必ず上の patch 済みのものを使う。

### 共通の入力：FIB の rule file

`wide_rib_to_rule.py` が Route Views（既定は `route-views.wide`）の RIB から作る。
1 行 1 prefix で `<network> <prefix長> <nexthop>`（空白区切り）。

```
0.0.0.0 0 b848d6e8-d386-420e-bec0-292cba45c389
1.0.0.0 24 202.249.2.169
1.0.4.0 24 202.249.2.169
```

- IPv4 だけ（`--ipv4-only`）。同じ prefix が複数の peer から来ても、最初の 1 行だけ残す。
- 先頭の `0.0.0.0 0 <UUID>` は既存の rule と揃えるために足した default route。下のスクリプトはどれも /0 を除く。
- 例：`wide_rib_to_rule.py --date 2026-03-27 --time 15:00 --ipv4-only` → `rib.20260327.0600.unique.rule`（1,059,159 行）

### 共通の出力：simulator の trace

`*_trace_to_sim.py` と `flowbench_widen_dst.py` が書く。1 行 1 パケットの 7 列 CSV（header なし）。

```
time,len,srcIP,dstIP,proto,srcPort,dstPort
```

```
0.000000,64,192.0.2.1,173.108.164.146,tcp,12345,80
0.000001,64,192.0.2.1,173.108.164.146,tcp,12345,80
```

- 意味があるのは宛先（dstIP）と順番だけ。ほかの列は引数で決めた固定値（`--src-ip`、`--proto`、`--packet-len`、`--src-port`、`--dst-port`）。
- 時刻は `--time-step`（既定 1 µs）ずつ進める。
- 同じ場所に `<出力>.meta.json`（入力の path、行数、生成条件）を書く。`--meta '{"pareto_a": 1}'` のように渡した JSON もここに足される。

### ClassBench

#### 1. `rule_to_classbench.py`：rule file → filter set

```
python3 scripts/rule_to_classbench.py --rule-file rib.20260327.0600.unique.rule --output rib20260327.cb
```

| 引数 | 内容 |
|---|---|
| `--rule-file` | 入力の rule file |
| `--output` | 書き出す filter file |
| `--keep-default` | /0 を残す（既定では除く） |
| `--max N` | 先頭 N 個だけ書く（0 なら全部） |

出力（`.cb`）は ClassBench の 5-tuple filter。宛先 field に prefix を入れ、ほかの field は wildcard にする。tab 区切り。

```
@0.0.0.0/0	1.0.0.0/24	0 : 65535	0 : 65535	0x00/0x00
@0.0.0.0/0	1.0.4.0/24	0 : 65535	0 : 65535	0x00/0x00
```

- 1 行を 1 行に変換するだけで、重なりのある prefix もそのまま残す（1,059,158 filter）。
- 行の順番（0 始まり）が、trace の filter 番号になる。
- `<出力>.meta.json` に filter 数と prefix 長の分布を書く。

#### 2. `trace_generator`（ClassBench）：filter set → trace

```
trace_generator <a> <b> <scale> <filter file> [seed]
# 例: trace_generator 1 0.1 10 rib20260327_a1_b0.1_s10_seed1 1
```

- `a`、`b`：Pareto 分布の parameter（局所性）。`b = 0` で局所性なし、大きいほど同じ filter が続く burst が長い。
- `scale`：trace の行数がおよそ filter 数 × scale になったら止まる（FIB 全体で scale 10 なら約 1,060 万行）。
- `seed`：local patch で追加した。省略すると時刻から決まり、再現できない。
- 出力は `<filter file>_trace` という名前になる。ほしい名前の symlink を filter file に張って実行し、出力を `.cbtrace` に rename している。

出力（`.cbtrace`）は tab 区切りの 10 進で、`src dst sport dport proto filter番号`。

```
4294967295	2415853568	65535	0	0	543309
0	2904616960	65535	65535	0	663644
```

各 field の下端か上端（corner）しか出ないので、宛先は network address（例：2415853568 = 143.255.0.0）か broadcast address になる。

#### 3. `classbench_trace_to_sim.py`：trace → simulator の trace

```
python3 scripts/classbench_trace_to_sim.py --trace rib20260327_a1_b0.1_s10_seed1.cbtrace \
  --filters rib20260327.cb --output cb_rib20260327_a1_b0.1_s10_seed1_random.txt --fill-host random --seed 1
```

| 引数 | 内容 |
|---|---|
| `--trace` | ClassBench の trace（`.cbtrace`） |
| `--filters` | trace の生成に使った filter file（`.cb`）。filter 番号から prefix を引くのに使う |
| `--output` | 書き出す simulator の trace |
| `--fill-host random` | 宛先を、その filter の prefix の中の random なアドレスに置き換える（既定）。同じ行が続く burst の間は同じ宛先にする |
| `--fill-host corner` | ClassBench の宛先（network / broadcast address）をそのまま使う |
| `--seed` | `random` のときの seed |

```
0.000000,64,192.0.2.1,143.255.1.245,tcp,12345,80   ← random
0.000000,64,192.0.2.1,143.255.0.0,tcp,12345,80     ← corner
```

`meta.json` には行数、burst 数、corner が network / broadcast だった burst 数を書く。

### FlowBench

#### 1. `fib_to_flowbench.py`：rule file → 重なりのない rule set

```
python3 scripts/fib_to_flowbench.py --rule-file rib.20260327.0600.unique.rule --output rib20260327.fb
```

| 引数 | 内容 |
|---|---|
| `--rule-file` | 入力の rule file |
| `--output` | 書き出す FlowBench の rule file |

FlowBench の isolation（各 rule を「その rule にしか当たらない領域」に切り出す処理）を、LPM 専用に O(n log n) で先に行う。

1. prefix をソートし、stack で直接の子（より長い prefix）を求める。
2. 到達領域 = prefix − 子の領域。空なら LPM の結果にならないので捨てる。
3. 到達領域の中で最大の aligned block を、その prefix の代表 rule にする。

出力は 3 つ。WIDE の FIB 全体で 6 秒程度。

- `.fb`：1 行 1 rule の、1 field の ClassBench 風書式。1,007,029 rule（完全に覆われた 52,129 個を除く）。

  ```
  @1.0.0.0/24
  @1.0.136.0/24
  ```

- `.fb.map`：出力と同じ順に `代表block 元prefix 到達領域のアドレス数`。

  ```
  1.0.0.0/24 1.0.0.0/24 256       ← 子がないので prefix そのまま
  1.0.136.0/24 1.0.128.0/19 512   ← /19 が子に削られ、残った領域の最大 block が /24
  ```

- `.fb.meta.json`：prefix 数、捨てた数、部分 block で代表した数（49,108）、block 長の分布。

#### 2. `flowbench-trace`（FlowBench）：rule set → trace

```
flowbench-trace -i rib20260327.fb --isolated -f 1 -fw 32 -ft LPM -n 10000000 -rd 0.7 1 -fd 1 1 -s 1 \
  -o rib20260327_rd0.7-1_fd1-1_n10m_s1.fbtrace
```

| 引数 | 内容 |
|---|---|
| `-i`、`-o` | 入力の rule file、出力の trace |
| `--isolated` | 入力が重なりのない rule なので、O(n²) の isolation を飛ばす（fork で追加） |
| `--no-verify` | `--isolated` のときの重なり検査を飛ばす（`verify-isolated` branch のみ） |
| `-f 1 -fw 32 -ft LPM` | field は 1 つ、32 bit、LPM |
| `-n` | パケット数 |
| `-rd a b` | rule 単位の Pareto parameter（どの rule にどれだけ当てるか） |
| `-fd a b` | flow 単位の Pareto parameter（rule の中の flow の偏り） |
| `-s` | seed |

出力（`.fbtrace`）は 1 行 1 パケットで、`0x<宛先の16進> <rule番号>`。

```
0xad6ca492  1006970
0xad6ca492  1006970
0xad63b6ff  1006970
```

rule 番号は FlowBench 内部で並べ替えた後の番号で、入力の順番と対応しない。

`verify-isolated` branch の FlowBench では、入力に重なりがあると次のように表示して終了する（rule の番号は入力順で 1 から）。
`fib_to_flowbench.py` の出力は、重なりがないことを確認済み（researchctl run `20261027-113927-c58c9b`）。

```
--isolated: input rules 8 and 9 overlap
  R 00000001000000001
  R 000000010000000010
```

#### 3. `flowbench_trace_to_sim.py`：trace → simulator の trace

```
python3 scripts/flowbench_trace_to_sim.py --trace rib20260327_rd0.7-1_fd1-1_n10m_s1.fbtrace \
  --output fb_rib20260327_rd0.7-1_fd1-1_n10m_s1.txt
```

| 引数 | 内容 |
|---|---|
| `--trace` | FlowBench の trace（`.fbtrace`） |
| `--output` | 書き出す simulator の trace |

宛先の 16 進をアドレスに直すだけで、rule 番号は使わない（LPM は解析側で計算し直す）。

```
0.000000,64,192.0.2.1,173.108.164.146,tcp,12345,80
```

#### 4. `flowbench_widen_dst.py`（任意）：宛先を到達領域全体に広げる

```
python3 scripts/flowbench_widen_dst.py --rule-file rib.20260327.0600.unique.rule \
  --trace fb_rib20260327_rd0.7-1_fd1-1_n10m_s1.txt --output fb_rib20260327_rd0.7-1_fd1-1_n10m_s1_widen.txt --seed 1
```

| 引数 | 内容 |
|---|---|
| `--rule-file` | `fib_to_flowbench.py` に渡したのと同じ rule file |
| `--trace` | `flowbench_trace_to_sim.py` の出力 |
| `--output` | 書き出す simulator の trace |
| `--seed` | 移し先を決める seed |

`fib_to_flowbench.py` は到達領域のうち最大の block しか使わない。そのため、例えば `1.0.128.0/19` に当たる宛先は、到達領域 512 アドレスのうち代表の `1.0.136.0/24` の 256 アドレスにしか出ない。
このスクリプトは、そうした prefix の宛先を到達領域全体に移す。

- 移し先は (宛先, seed) で決まる 1 対 1 の関数。同じ宛先は同じ宛先のまま、異なる宛先は異なるままで、prefix ごとのパケット数も変わらない。
- 到達領域が 1 block の prefix の宛先はそのまま。
- `meta.json` には、対象 prefix 数、移したパケット数、移した宛先の種類数を書く。

### 制約と注意点

- **ClassBench は覆われた prefix も選ぶ。** filter を一様に選ぶので、選んだ filter と実際に LPM で当たる prefix がずれることがある。また、当たる prefix のほとんどが /24 になる（平均 LPM 長 23.1、WIDE の実 trace は 18.1）。
- **FlowBench の rule は 1 prefix につき 1 block。** `flowbench_widen_dst.py` を通さない trace では、子を持つ prefix（49,108 個）の宛先が代表 block に集まる。短い prefix を /24 などに展開する cache（MP など）では、必要な entry 数が実際より少なくなり、hit 率が良く見えすぎる可能性がある（影響の大きさはまだ測っていない）。
- **宛先以外の列には意味がない。** flow 単位の 5-tuple を見る解析には使えない。
