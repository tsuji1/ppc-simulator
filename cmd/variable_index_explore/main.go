// variable_index_explore は Variable Index Cache（UnifiedCache の index 長を可変にしたもの）の
// ハードウェア実装案を比較するための軽量シミュレータ（issue #78）。
//
// 入力は cmd/export_dst_leaf が出力する (DstIP, IsLeafIndex) 列で、キャッシュの動作は
// UnifiedCache の exclusive / way 内 LRU と同じにしている。set index は既定で「上位 L bit の prefix の
// 下位 log2(sets) bit」（direct、CacheIndexType=100+L 相当）。CRC32(上位 L bit) % sets は deprecated。
// その上で次を比較する。
//
//   - static:  固定 index 長 L（静的最適を求める）
//   - ideal:   パケット自身の leaf 長を index 長に使う（CacheIndexType=2 相当、LPM が先に要る上限）
//   - shadow:  sampled set だけに候補 L ごとの shadow tag を置き、epoch ごとに L を選ぶ（案1）
//   - region:  宛先上位 g bit の decision table で領域ごとに L を決める（案2）
//   - split:   way を 2 群に分け、群ごとに別の index 長を使う（案4）
//
// 案1 の index 切替時の扱い（案3）は flush / keep / dual / rehash を選べる。
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/gob"
	"flag"
	"fmt"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"

	"test-module/cache"
)

const (
	minTagLen = 9
	maxTagLen = 24
)

// ---------------------------------------------------------------- trace

type trace struct {
	dst  []uint32
	clen []int8 // 挿入時の prefix 長（9..24）。挿入不可は -1
}

// loadTraces は .gob（gob-packet の []cache.MinPacket）か .dstleaf（export_dst_leaf の 5 byte/packet）を
// 順に連結して読む。gob は export_dst_leaf と同じく TCP/UDP パケットだけを使う。
func loadTraces(paths []string, maxPerFile int) *trace {
	t := &trace{}
	for _, path := range paths {
		if strings.HasSuffix(path, ".gob") {
			loadGob(t, path, maxPerFile)
		} else {
			loadDstLeaf(t, path, maxPerFile)
		}
	}
	return t
}

func (t *trace) append(dst uint32, leaf int) {
	cl := int8(-1)
	// UnifiedCache は /0.. /8 も最小 tag 長 /9 に切り上げて挿入する。
	if leaf >= 0 && leaf <= maxTagLen {
		cl = int8(max(leaf, minTagLen))
	}
	t.dst = append(t.dst, dst)
	t.clen = append(t.clen, cl)
}

func loadGob(t *trace, path string, maxPerFile int) {
	f, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	var packets []cache.MinPacket
	if err := gob.NewDecoder(bufio.NewReaderSize(f, 1<<22)).Decode(&packets); err != nil {
		panic(fmt.Errorf("decode %s: %w", path, err))
	}
	n := 0
	for i := range packets {
		if maxPerFile > 0 && n >= maxPerFile {
			break
		}
		if packets[i].FiveTuple() == nil {
			continue
		}
		t.append(packets[i].DstIP, int(packets[i].IsLeafIndex))
		n++
	}
}

func loadDstLeaf(t *trace, path string, maxPerFile int) {
	f, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	r := bufio.NewReaderSize(f, 1<<22)
	var buf [5]byte
	for n := 0; maxPerFile <= 0 || n < maxPerFile; n++ {
		if _, err := io.ReadFull(r, buf[:]); err != nil {
			break
		}
		t.append(binary.LittleEndian.Uint32(buf[:4]), int(int8(buf[4])))
	}
}

// ---------------------------------------------------------------- set-associative LRU array

// tag は key = net<<8 | len。len>=9 なので 0 は invalid を表す。
// 位置 0 が MRU、way-1 が LRU。
type setArray struct {
	way, nsets int
	tags       []uint64
}

func newSetArray(nsets, way int) *setArray {
	return &setArray{way: way, nsets: nsets, tags: make([]uint64, nsets*way)}
}

func makeKey(dst uint32, l int) uint64 { return uint64(dst>>(32-l))<<8 | uint64(l) }

// lookup は set 内で dst に最長一致する entry の位置を返す（無ければ -1）。
func (a *setArray) lookup(set int, dst uint32) int {
	base := set * a.way
	best, bestLen := -1, 0
	for i := 0; i < a.way; i++ {
		k := a.tags[base+i]
		if k == 0 {
			continue
		}
		l := int(k & 0xff)
		if l > bestLen && uint64(dst>>(32-l)) == k>>8 {
			best, bestLen = i, l
		}
	}
	return best
}

func (a *setArray) touch(set, pos int) {
	base := set * a.way
	k := a.tags[base+pos]
	copy(a.tags[base+1:base+pos+1], a.tags[base:base+pos])
	a.tags[base] = k
}

func (a *setArray) insert(set int, key uint64) {
	base := set * a.way
	copy(a.tags[base+1:base+a.way], a.tags[base:base+a.way-1])
	a.tags[base] = key
}

func (a *setArray) remove(set, pos int) {
	base := set * a.way
	copy(a.tags[base+pos:base+a.way-1], a.tags[base+pos+1:base+a.way])
	a.tags[base+a.way-1] = 0
}

// access は lookup・LRU 更新・miss 時の挿入をまとめて行い、hit したかを返す。
func (a *setArray) access(set int, dst uint32, clen int8) bool {
	if pos := a.lookup(set, dst); pos >= 0 {
		a.touch(set, pos)
		return true
	}
	if clen > 0 {
		a.insert(set, makeKey(dst, int(clen)))
	}
	return false
}

// directIndex が true なら、上位 L bit の prefix をハッシュせず、その下位 log2(nsets) bit を set index にする
// （UnifiedCache の CacheIndexType=100+L 相当）。main() の -index の既定はこちら（direct）。
// shadow 等の縮小キャッシュの nsets も 2 冪であること。
//
// Deprecated: false の CRC32(上位 L bit) % nsets（CacheIndexType=L 相当）は使わない。
// 2026-10-08 以前の結果（-index crc）との比較・再現のためだけに残している。
var directIndex bool

func indexOf(dst uint32, l, nsets int) int {
	if directIndex {
		return int(dst>>(32-l)) & (nsets - 1)
	}
	var b [4]byte
	binary.BigEndian.PutUint32(b[:], dst>>(32-l))
	return int(crc32.ChecksumIEEE(b[:]) % uint32(nsets))
}

// ---------------------------------------------------------------- result

type result struct {
	Trace, Policy, Params string
	Capacity, Way         int
	Packets, Hits         uint64
	Probes                uint64 // set read 回数（dual probe・split の追加 read を含む）
	Switches              int
	ShadowBits            int // 追加 shadow tag SRAM の bit 数
	TableBits             int // decision table / 選択用カウンタの bit 数
	FinalL                string
	LHist                 map[int]uint64 // index 長ごとの lookup 回数
	Series                []window
}

type window struct {
	Start, Len, Hits, Active int
}

func (r *result) hitRate() float64 { return float64(r.Hits) / float64(r.Packets) }

// ---------------------------------------------------------------- static / ideal

func runStatic(t *trace, from, to, capacity, way, l int) *result {
	nsets := capacity / way
	a := newSetArray(nsets, way)
	res := &result{Policy: "static", Params: fmt.Sprintf("L=%d", l), Capacity: capacity, Way: way, FinalL: strconv.Itoa(l)}
	for i := from; i < to; i++ {
		if a.access(indexOf(t.dst[i], l, nsets), t.dst[i], t.clen[i]) {
			res.Hits++
		}
	}
	res.Packets = uint64(to - from)
	res.Probes = res.Packets
	return res
}

// runStaticSwitch は、先頭 tr パケットを初期 L で転送しながら同じパケットで最良の固定 L を選び、
// tr パケット目で切り替えて（flush して）残りを流す。返すヒット率は全区間のもの。
func runStaticSwitch(t *trace, capacity, way, initial, tr int) *result {
	tr = min(tr, len(t.dst))
	best, bestHit := initial, uint64(0)
	for l := 9; l <= 24; l++ {
		if r := runStatic(t, 0, tr, capacity, way, l); r.Hits > bestHit {
			best, bestHit = l, r.Hits
		}
	}
	nsets := capacity / way
	a := newSetArray(nsets, way)
	res := &result{Policy: "static-switch", Params: fmt.Sprintf("init=%d;train=%d;L=%d", initial, tr, best),
		Capacity: capacity, Way: way, FinalL: strconv.Itoa(best), LHist: map[int]uint64{}}
	l := initial
	for i, dst := range t.dst {
		if i == tr && best != l {
			clear(a.tags) // direct index では index bit を tag から省くので flush が必要
			l = best
			res.Switches++
		}
		res.LHist[l]++
		if a.access(indexOf(dst, l, nsets), dst, t.clen[i]) {
			res.Hits++
		}
	}
	res.Packets = uint64(len(t.dst))
	res.Probes = res.Packets
	return res
}

// runIdeal は CacheIndexType=2 (IDEAL) と同様、パケットの leaf 長を index に使う（16..24 に clamp）。
func runIdeal(t *trace, capacity, way int) *result {
	nsets := capacity / way
	a := newSetArray(nsets, way)
	res := &result{Policy: "ideal-leaf", Params: "L=clamp(leaf;16;24)", Capacity: capacity, Way: way}
	for i, dst := range t.dst {
		l := clampInt(int(t.clen[i]), 16, 24)
		if a.access(indexOf(dst, l, nsets), dst, t.clen[i]) {
			res.Hits++
		}
	}
	res.Packets = uint64(len(t.dst))
	res.Probes = res.Packets
	return res
}

// ---------------------------------------------------------------- 案1: shadow tag + sampled set

type shadowConfig struct {
	Cands      []int  // 候補 index 長
	Neighbor   int    // >0 なら Lcur±Neighbor の候補だけ shadow を持つ
	Rover      bool   // Neighbor モードで、近傍外の L を 2 epoch ずつ巡回する shadow を 1 面追加する
	SampleDiv  int    // 1/SampleDiv の set（または traffic）を sampled にする
	SampleMode string // set: 候補 L の index が sampled set に落ちたパケットだけ評価（set dueling 型）
	// traffic: 上位 SampleBits bit の hash で選んだ同じパケット集合を全候補で評価（UMON 型）。
	// shadow は nsets/SampleDiv set の縮小キャッシュとして独立に index する。
	// entry: リタイア段で分かる挿入 prefix (dst/clen) の hash で選ぶ。1 つの entry のパケットは
	// 全部入るか全部入らないかなので、shadow は「entry を 1/SampleDiv に間引いた縮小キャッシュ」になる。
	// 挿入不可のパケットはどの候補でも miss なので評価しない
	SampleBits int
	Epoch      int     // epoch 長（packet）
	Threshold  float64 // 切替に必要な hit rate 差（ヒステリシス）
	Initial    int
	Switch     string // flush / keep / dual / rehash
	DualWindow int    // dual で旧 index を probe し続ける packet 数
	TagBits    int    // shadow の部分 tag bit 数（0 は full tag）
	HotEntries int    // >0 なら hot 領域テーブルを併用（hot 領域は表の L、それ以外は shadow が選ぶ L）
	HotG       int
	Decay      bool // epoch 末にカウンタを半減（true）かリセット（false）
	SeriesWin  int
}

func (c shadowConfig) String() string {
	cand := fmt.Sprintf("%d-%d", c.Cands[0], c.Cands[len(c.Cands)-1])
	if c.Neighbor > 0 {
		cand = fmt.Sprintf("cur+-%d", c.Neighbor)
		if c.Rover {
			cand += "+rover"
		}
	}
	return fmt.Sprintf("cand=%s;sample=%s;div=%d;epoch=%d;th=%g;init=%d;switch=%s;dualwin=%d;tagbits=%d;decay=%v;hot=%d@/%d",
		cand, c.SampleMode, c.SampleDiv, c.Epoch, c.Threshold, c.Initial, c.Switch, c.DualWindow, c.TagBits, c.Decay, c.HotEntries, c.HotG)
}

var koopman = crc32.MakeTable(crc32.Koopman)

// debugEpochs > 0 なら、最初の debugEpochs 個の epoch で候補別 shadow ヒット率を stderr に出す。
var debugEpochs int
var castagnoli = crc32.MakeTable(crc32.Castagnoli)

// entrySampleHash は entry サンプリング用の key {dst を clen で mask, 下位 5bit に clen} の CRC32C。
func entrySampleHash(dst uint32, clen int) uint32 {
	var b [4]byte
	binary.BigEndian.PutUint32(b[:], dst&^(uint32(0xffffffff)>>clen)|uint32(clen))
	return crc32.Checksum(b[:], castagnoli)
}

// sampleHash は traffic サンプリング用。index 用 CRC と相関しないよう別多項式を使う。
func sampleHash(dst uint32, bits int) uint32 {
	var b [4]byte
	binary.BigEndian.PutUint32(b[:], dst>>(32-bits))
	return crc32.Checksum(b[:], castagnoli)
}

// shadowKey は shadow tag の値。bits>0 なら prefix を bits 幅に hash した部分 tag（別名による誤 hit あり）。
func shadowKey(net uint32, l int, bits int) uint64 {
	if bits <= 0 {
		return uint64(net)<<8 | uint64(l)
	}
	var b [5]byte
	binary.BigEndian.PutUint32(b[:4], net)
	b[4] = byte(l)
	h := crc32.Checksum(b[:], koopman) & (1<<bits - 1)
	return uint64(h)<<8 | uint64(l)
}

type shadowArray struct {
	*setArray
	tagBits int
}

func (s *shadowArray) access(set int, dst uint32, clen int8) bool {
	base := set * s.way
	best, bestLen := -1, 0
	for i := 0; i < s.way; i++ {
		k := s.tags[base+i]
		if k == 0 {
			continue
		}
		l := int(k & 0xff)
		if l > bestLen && shadowKey(dst>>(32-l), l, s.tagBits) == k {
			best, bestLen = i, l
		}
	}
	if best >= 0 {
		s.touch(set, best)
		return true
	}
	if clen > 0 {
		s.insert(set, shadowKey(dst>>(32-int(clen)), int(clen), s.tagBits))
	}
	return false
}

func runShadow(t *trace, capacity, way int, cfg shadowConfig) *result {
	nsets := capacity / way
	mainArr := newSetArray(nsets, way)
	sampledSets := max(nsets/cfg.SampleDiv, 1)
	res := &result{Policy: "shadow", Params: cfg.String(), Capacity: capacity, Way: way, LHist: map[int]uint64{}}

	cur, old, dualUntil := cfg.Initial, -1, -1

	// Neighbor モードでは物理的な shadow は 2*Neighbor+1 個だけ。窓から外れた L の shadow は捨て、
	// 新しく入った L は空から温め直す。
	shadows := map[int]*shadowArray{}
	// rover は近傍外の L を順に回る。roverMeasuring=false の epoch は温め、true の epoch で評価する。
	rover, roverMeasuring := -1, false
	neighborCands := func() []int {
		if cfg.Neighbor <= 0 {
			return cfg.Cands
		}
		out := []int{}
		for _, l := range cfg.Cands {
			if abs(l-cur) <= cfg.Neighbor {
				out = append(out, l)
			}
		}
		return out
	}
	activeCands := func() []int {
		out := neighborCands()
		if rover >= 0 {
			out = append(out, rover)
		}
		return out
	}
	evalCands := func() []int {
		out := neighborCands()
		if rover >= 0 && roverMeasuring {
			out = append(out, rover)
		}
		return out
	}
	nextRover := func() {
		if !cfg.Rover || cfg.Neighbor <= 0 {
			return
		}
		start := rover
		if start < 0 {
			start = cfg.Cands[0] - 1
		}
		rover, roverMeasuring = -1, false
		for step := 1; step <= len(cfg.Cands); step++ {
			l := cfg.Cands[0] + (start-cfg.Cands[0]+step+len(cfg.Cands))%len(cfg.Cands)
			if abs(l-cur) > cfg.Neighbor {
				rover = l
				return
			}
		}
	}
	nextRover()
	hits, accs := map[int]float64{}, map[int]float64{}
	var hot *hotRegionTable
	if cfg.HotEntries > 0 {
		hot = newHotRegionTable(cfg.HotG, cfg.HotEntries, cfg.Cands)
	}
	syncShadows := func() {
		want := map[int]bool{}
		for _, l := range activeCands() {
			want[l] = true
			if shadows[l] == nil {
				shadows[l] = &shadowArray{setArray: newSetArray(sampledSets, way), tagBits: cfg.TagBits}
			}
		}
		for l := range shadows {
			if !want[l] {
				delete(shadows, l)
				delete(hits, l)
				delete(accs, l)
			}
		}
	}
	syncShadows()
	phys := len(cfg.Cands)
	if cfg.Neighbor > 0 {
		phys = 2*cfg.Neighbor + 1
		if cfg.Rover {
			phys++
		}
	}
	tagWidth := 24 + 4 // prefix 24bit + Length 4bit
	if cfg.TagBits > 0 {
		tagWidth = cfg.TagBits + 4
	}
	res.ShadowBits = phys * sampledSets * way * (tagWidth + 1 + 3) // +valid +LRU(3bit 相当)
	res.TableBits = phys * 2 * 20                                  // hit / access カウンタ

	win := window{Active: cur}
	epochPos := 0
	for i, dst := range t.dst {
		clen := t.clen[i]
		// hot 領域は表の L を使い、shadow の評価対象から外す
		hotL, isHot := 0, false
		if hot != nil {
			hotL, isHot = hot.override(dst)
		}

		// --- shadow 評価（候補 L の index が sampled set に落ちたときだけ）
		if isHot {
			// 評価しない
		} else if cfg.SampleMode == "traffic" || cfg.SampleMode == "entry" {
			var h uint32
			if cfg.SampleMode == "traffic" {
				h = sampleHash(dst, cfg.SampleBits)
			} else if clen > 0 {
				h = entrySampleHash(dst, int(clen))
			} else {
				h = 1
			}
			if h%uint32(cfg.SampleDiv) == 0 {
				for l, sh := range shadows {
					accs[l]++
					if sh.access(indexOf(dst, l, sampledSets), dst, clen) {
						hits[l]++
					}
				}
			}
		} else {
			for l, sh := range shadows {
				s := indexOf(dst, l, nsets)
				if s%cfg.SampleDiv != 0 || s/cfg.SampleDiv >= sampledSets {
					continue
				}
				accs[l]++
				if sh.access(s/cfg.SampleDiv, dst, clen) {
					hits[l]++
				}
			}
		}

		// --- 本体
		l := cur
		if isHot {
			l = hotL
		}
		res.LHist[l]++
		res.Probes++
		set := indexOf(dst, l, nsets)
		hit := false
		if pos := mainArr.lookup(set, dst); pos >= 0 {
			mainArr.touch(set, pos)
			hit = true
		} else if old >= 0 && i < dualUntil && !isHot {
			res.Probes++
			hit = dualProbe(mainArr, set, indexOf(dst, old, nsets), dst)
		}
		if hit {
			res.Hits++
			win.Hits++
		} else if clen > 0 {
			mainArr.insert(set, makeKey(dst, int(clen)))
			if hot != nil {
				hot.observeMiss(dst, int(clen))
			}
		}
		win.Len++
		if cfg.SeriesWin > 0 && win.Len == cfg.SeriesWin {
			res.Series = append(res.Series, win)
			win = window{Start: i + 1, Active: cur}
		}

		// --- epoch 末の選択
		if epochPos++; epochPos < cfg.Epoch {
			continue
		}
		epochPos = 0
		if debugEpochs > 0 && int(res.Packets) < debugEpochs {
			res.Packets++ // デバッグ出力した epoch 数（最後に上書きされる）
			line := fmt.Sprintf("cap=%d %s epoch@%d cur=%d:", capacity, cfg.SampleMode, i+1, cur)
			for _, l := range cfg.Cands {
				if accs[l] > 0 {
					line += fmt.Sprintf(" %d=%.4f", l, hits[l]/accs[l])
				}
			}
			fmt.Fprintln(os.Stderr, line)
		}
		curRate := 0.0
		if accs[cur] > 0 {
			curRate = hits[cur] / accs[cur]
		}
		best, bestRate := cur, curRate
		for _, l := range evalCands() {
			if accs[l] == 0 {
				continue
			}
			if r := hits[l] / accs[l]; r > bestRate {
				best, bestRate = l, r
			}
		}
		if best != cur && bestRate > curRate+cfg.Threshold {
			res.Switches++
			switchIndex(mainArr, cfg.Switch, best, nsets)
			old, cur = cur, best
			dualUntil = -1
			if cfg.Switch == "dual" {
				dualUntil = i + 1 + cfg.DualWindow
			}
		}
		// rover: 温め終わったら次の epoch で評価し、評価が済んだら（または近傍に入ったら）次の L へ
		if rover >= 0 && (roverMeasuring || abs(rover-cur) <= cfg.Neighbor) {
			nextRover()
		} else if rover >= 0 {
			roverMeasuring = true
		}
		syncShadows()
		for l := range hits {
			if cfg.Decay {
				hits[l] /= 2
				accs[l] /= 2
			} else {
				hits[l], accs[l] = 0, 0
			}
		}
	}
	if cfg.SeriesWin > 0 && win.Len > 0 {
		res.Series = append(res.Series, win)
	}
	res.Packets = uint64(len(t.dst))
	res.FinalL = strconv.Itoa(cur)
	return res
}

// dualProbe は dual 切替中、新 set で miss したパケットについて旧 set を引き、
// 見つかった entry を旧 set から外して新 set の MRU へ移す。hit したかを返す。
func dualProbe(a *setArray, set, oldSet int, dst uint32) bool {
	pos := a.lookup(oldSet, dst)
	if pos < 0 {
		return false
	}
	k := a.tags[oldSet*a.way+pos]
	a.remove(oldSet, pos)
	a.insert(set, k)
	return true
}

// switchIndex は index 長を新しい値 to に切り替えるときの本体配列の扱い。
//   - flush:  全 entry を無効化（現行 RTL の flush_req）
//   - keep:   何もしない。tag に prefix 全体を持つので誤 hit はしない（direct index で index bit を tag から
//     省く HW 実装なら flush か長さ tag が要る）が、
//     旧位置の entry は到達不能になり LRU で自然に追い出される
//   - dual:   keep と同じ。一定期間、新 set で miss したら旧 set も引き、見つかれば新 set へ移す
//   - rehash: len>=to の entry を新 set へ一括で移す（バックグラウンド掃引が瞬時に終わる上限）。
//     len<to の entry は新 index に必要な bit が tag に無いので捨てる
func switchIndex(a *setArray, method string, to, nsets int) {
	switch method {
	case "flush":
		clear(a.tags)
	case "rehash":
		old := append([]uint64(nil), a.tags...)
		clear(a.tags)
		// 旧 set の LRU 側から入れ、MRU が最後に入る（新 set でも MRU 側に来る）ようにする
		for i := a.way - 1; i >= 0; i-- {
			for s := 0; s < nsets; s++ {
				k := old[s*a.way+i]
				if k == 0 {
					continue
				}
				l := int(k & 0xff)
				if l < to {
					continue
				}
				a.insert(indexOf(uint32(k>>8)<<(32-l), to, nsets), k)
			}
		}
	}
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

func clampInt(x, lo, hi int) int { return min(max(x, lo), hi) }

// ---------------------------------------------------------------- 案2: 領域ごとの decision table

type regionTable struct {
	g int
	l []int8
}

func (rt *regionTable) lookupL(dst uint32) int {
	if rt.g == 0 {
		return int(rt.l[0])
	}
	return int(rt.l[dst>>(32-rt.g)])
}

// trainRegionOracle は静的 L ごとの per-packet hit を領域に配分し、領域ごとに hit 最大の L を選ぶ。
// コントロールプレーンがオフラインで計算する想定（Rajan & Govindarajan PACT'06 と同様）。
// 領域どうしが同じ set を共有することによる干渉は無視するので近似。
func trainRegionOracle(t *trace, n, capacity, way, g int, cands []int) *regionTable {
	nsets := capacity / way
	nreg := 1 << g
	hitsBy := make([][]uint32, len(cands))
	var wg sync.WaitGroup
	for ci, l := range cands {
		wg.Add(1)
		go func() {
			defer wg.Done()
			h := make([]uint32, nreg)
			a := newSetArray(nsets, way)
			for i := 0; i < n; i++ {
				if a.access(indexOf(t.dst[i], l, nsets), t.dst[i], t.clen[i]) {
					h[t.dst[i]>>(32-g)]++
				}
			}
			hitsBy[ci] = h
		}()
	}
	wg.Wait()
	rt := &regionTable{g: g, l: make([]int8, nreg)}
	for r := 0; r < nreg; r++ {
		best, bh := -1, uint32(0)
		for ci := range cands {
			if hitsBy[ci][r] > bh {
				best, bh = ci, hitsBy[ci][r]
			}
		}
		rt.l[r] = -1
		if best >= 0 {
			rt.l[r] = int8(cands[best])
		}
	}
	fillDefault(rt, cands)
	return rt
}

// trainRegionMode は領域内で挿入対象になった prefix 長の最頻値を使う（候補範囲に clamp）。
// 領域×長さのカウンタだけで作れるので、データプレーンでも集計できる。
func trainRegionMode(t *trace, n, g int, cands []int) *regionTable {
	nreg := 1 << g
	hist := make([][25]uint32, nreg)
	for i := 0; i < n; i++ {
		if cl := int(t.clen[i]); cl > 0 {
			hist[t.dst[i]>>(32-g)][cl]++
		}
	}
	rt := &regionTable{g: g, l: make([]int8, nreg)}
	for r := 0; r < nreg; r++ {
		best, bc := -1, uint32(0)
		for l := 0; l <= 24; l++ {
			if hist[r][l] > bc {
				best, bc = l, hist[r][l]
			}
		}
		rt.l[r] = -1
		if best >= 0 {
			rt.l[r] = int8(clampInt(best, cands[0], cands[len(cands)-1]))
		}
	}
	fillDefault(rt, cands)
	return rt
}

// fillDefault は観測の無い領域を、領域数で最も多い L で埋める。
func fillDefault(rt *regionTable, cands []int) {
	count := map[int8]int{}
	for _, l := range rt.l {
		if l > 0 {
			count[l]++
		}
	}
	def, dc := int8(cands[len(cands)/2]), 0
	for l, c := range count {
		if c > dc || (c == dc && l < def) {
			def, dc = l, c
		}
	}
	for r := range rt.l {
		if rt.l[r] < 0 {
			rt.l[r] = def
		}
	}
}

func runRegion(t *trace, from, to, capacity, way int, rt *regionTable, name string) *result {
	nsets := capacity / way
	a := newSetArray(nsets, way)
	res := &result{Policy: "region-" + name, Params: fmt.Sprintf("g=%d", rt.g), Capacity: capacity, Way: way, LHist: map[int]uint64{}}
	res.TableBits = (1 << rt.g) * 4
	for i := from; i < to; i++ {
		l := rt.lookupL(t.dst[i])
		res.LHist[l]++
		if a.access(indexOf(t.dst[i], l, nsets), t.dst[i], t.clen[i]) {
			res.Hits++
		}
	}
	res.Packets = uint64(to - from)
	res.Probes = res.Packets
	return res
}

// runRegionOnline は decision table をデータプレーンでオンライン更新する（案2 の自動更新版）。
// リタイア段で確定した挿入長 clen を、その領域のエントリに反映する。
//   - last:     table[r] = clen（既存 last-inserted-prefix の領域版）
//   - majority: Boyer-Moore 多数決。entry = {cand 4bit, cnt CntBits}。cnt が 0 のときだけ cand を入れ替える
//
// update=miss なら挿入（miss）時だけ、all なら hit も含む全パケットで更新する。
// table 変更時に既存 entry は移動しない（full tag なので誤 hit はしない）。
//
// tableBits < g なら、上位 g bit を CRC32C で hash して 2^tableBits エントリの表を引く（領域が別名で共有する）。
func runRegionOnline(t *trace, capacity, way, g, tableBits int, cands []int, initial int, kind, update string, cntBits int) *result {
	nsets := capacity / way
	a := newSetArray(nsets, way)
	if tableBits <= 0 || tableBits > g {
		tableBits = g
	}
	nreg := 1 << tableBits
	regionOf := func(dst uint32) uint32 {
		if tableBits == g {
			return dst >> (32 - g)
		}
		return sampleHash(dst, g) & uint32(nreg-1)
	}
	cand := make([]int8, nreg)
	cnt := make([]uint8, nreg)
	for r := range cand {
		cand[r] = int8(initial)
	}
	cntMax := uint8(1<<cntBits - 1)
	lo, hi := cands[0], cands[len(cands)-1]
	res := &result{Policy: "region-online-" + kind, Params: fmt.Sprintf("g=%d;table=2^%d;update=%s;cnt=%d", g, tableBits, update, cntBits),
		Capacity: capacity, Way: way, LHist: map[int]uint64{}}
	res.TableBits = nreg * 4
	if kind == "majority" {
		res.TableBits = nreg * (4 + cntBits)
	}
	var changes int
	for i, dst := range t.dst {
		r := regionOf(dst)
		l := int(cand[r])
		res.LHist[l]++
		hit := a.access(indexOf(dst, l, nsets), dst, t.clen[i])
		if hit {
			res.Hits++
		}
		cl := int(t.clen[i])
		if cl <= 0 || (hit && update == "miss") {
			continue
		}
		obs := int8(clampInt(cl, lo, hi))
		switch kind {
		case "last":
			if cand[r] != obs {
				cand[r] = obs
				changes++
			}
		case "majority":
			switch {
			case cand[r] == obs:
				if cnt[r] < cntMax {
					cnt[r]++
				}
			case cnt[r] == 0:
				cand[r] = obs
				cnt[r] = 1
				changes++
			default:
				cnt[r]--
			}
		}
	}
	res.Switches = changes
	res.Packets = uint64(len(t.dst))
	res.Probes = res.Packets
	return res
}

// hotRegionTable は hot 領域だけ index 長を上書きする小さな連想テーブル（案2 の安価版）。
//
// エントリは {region tag (上位 g bit), cand 4bit, vote 3bit, cnt 16bit}。miss（挿入）時に:
//   - その領域が表にあれば cnt++ し、挿入長で多数決（Boyer-Moore）を更新する
//   - 無ければ cnt 最小のエントリを置き換える（Space-Saving: cnt = min+1, cand = 挿入長, vote = 0）
//
// lookup では表にあり vote>=1 の領域だけ cand を使う。fully associative（K 個の比較器）を想定。
type hotRegionTable struct {
	g      int
	lo, hi int
	tab    []hotRegionEntry
	writes int
}

type hotRegionEntry struct {
	tag   uint32
	valid bool
	cand  int8
	vote  uint8
	cnt   uint32
}

func newHotRegionTable(g, k int, cands []int) *hotRegionTable {
	return &hotRegionTable{g: g, lo: cands[0], hi: cands[len(cands)-1], tab: make([]hotRegionEntry, k)}
}

func (h *hotRegionTable) bits() int { return len(h.tab) * (h.g + 4 + 3 + 16 + 1) }

func (h *hotRegionTable) find(dst uint32) int {
	r := dst >> (32 - h.g)
	for i := range h.tab {
		if h.tab[i].valid && h.tab[i].tag == r {
			return i
		}
	}
	return -1
}

// override は dst の領域に上書き L があれば返す。
func (h *hotRegionTable) override(dst uint32) (int, bool) {
	if i := h.find(dst); i >= 0 && h.tab[i].vote > 0 {
		return int(h.tab[i].cand), true
	}
	return 0, false
}

// observeMiss は挿入長 clen の miss を記録する。
func (h *hotRegionTable) observeMiss(dst uint32, clen int) {
	obs := int8(clampInt(clen, h.lo, h.hi))
	i := h.find(dst)
	if i < 0 {
		victim := 0
		for j := range h.tab {
			if !h.tab[j].valid {
				victim = j
				break
			}
			if h.tab[j].cnt < h.tab[victim].cnt {
				victim = j
			}
		}
		h.tab[victim] = hotRegionEntry{tag: dst >> (32 - h.g), valid: true, cand: obs, cnt: h.tab[victim].cnt + 1}
		h.writes++
		return
	}
	e := &h.tab[i]
	e.cnt++
	switch {
	case e.cand == obs:
		if e.vote < 7 {
			e.vote++
		}
	case e.vote == 0:
		e.cand = obs
		e.vote = 1
	default:
		e.vote--
	}
}

func runHotRegion(t *trace, capacity, way, g, k, def int, cands []int) *result {
	nsets := capacity / way
	a := newSetArray(nsets, way)
	hot := newHotRegionTable(g, k, cands)
	res := &result{Policy: "hot-region", Params: fmt.Sprintf("g=%d;entries=%d;default=%d", g, k, def), Capacity: capacity, Way: way, LHist: map[int]uint64{}}
	res.TableBits = hot.bits()
	for i, dst := range t.dst {
		l := def
		if ol, ok := hot.override(dst); ok {
			l = ol
		}
		res.LHist[l]++
		if a.access(indexOf(dst, l, nsets), dst, t.clen[i]) {
			res.Hits++
		} else if t.clen[i] > 0 {
			hot.observeMiss(dst, int(t.clen[i]))
		}
	}
	res.Switches = hot.writes
	res.Packets = uint64(len(t.dst))
	res.Probes = res.Packets
	return res
}

// ---------------------------------------------------------------- 案4: way ごとの index 長

// runSplit は wayA 本の way を index 長 la、残りを lb で引く。prefix 長 <= la の entry は A 群、
// それ以外は B 群に入れる。lookup は 2 群を並列に引く（read は 2 回分）。
func runSplit(t *trace, capacity, way, wayA, la, lb int) *result {
	nsets := capacity / way
	a := newSetArray(nsets, wayA)
	b := newSetArray(nsets, way-wayA)
	res := &result{Policy: "split", Params: fmt.Sprintf("A=%dway@/%d;B=%dway@/%d", wayA, la, way-wayA, lb), Capacity: capacity, Way: way}
	for i, dst := range t.dst {
		sa, sb := indexOf(dst, la, nsets), indexOf(dst, lb, nsets)
		pa, pb := a.lookup(sa, dst), b.lookup(sb, dst)
		res.Probes += 2
		if pa >= 0 || pb >= 0 {
			res.Hits++
			if pa >= 0 {
				a.touch(sa, pa)
			}
			if pb >= 0 {
				b.touch(sb, pb)
			}
			continue
		}
		cl := int(t.clen[i])
		switch {
		case cl <= 0:
		case cl <= la:
			a.insert(sa, makeKey(dst, cl))
		default:
			b.insert(sb, makeKey(dst, cl))
		}
	}
	res.Packets = uint64(len(t.dst))
	return res
}

// ---------------------------------------------------------------- main

func parseInts(s string) []int {
	var out []int
	for _, f := range strings.Split(s, ",") {
		f = strings.TrimSpace(f)
		if f == "" {
			continue
		}
		if lo, hi, ok := strings.Cut(f, "-"); ok && lo != "" {
			a, _ := strconv.Atoi(lo)
			b, _ := strconv.Atoi(hi)
			for v := a; v <= b; v++ {
				out = append(out, v)
			}
			continue
		}
		v, err := strconv.Atoi(f)
		if err != nil {
			panic(err)
		}
		out = append(out, v)
	}
	return out
}

func main() {
	var (
		traceFiles = flag.String("trace", "", "comma separated .gob (gob-packet) or .dstleaf files (concatenated in order)")
		name       = flag.String("name", "", "trace label used in output")
		maxPer     = flag.Int("max", 10_000_000, "packets per file")
		mode       = flag.String("mode", "static", "static | shadow | region | split")
		indexKind  = flag.String("index", "direct", "set index function: direct (low bits of top L bits) | crc (DEPRECATED: CRC32 of top L bits)")
		caps       = flag.String("capacity", "1024,4096,16384", "capacities")
		way        = flag.Int("way", 8, "associativity")
		cands      = flag.String("cands", "16-24", "candidate index lengths")
		fixedIndex = flag.Int("fixed-index", 0, "fixed prefix length used for indexing (0 = normal /9..24 sweep; allows legacy type-5 comparison)")
		outDir     = flag.String("out", "scripts/reports/variable_index_hw", "output dir")
		tag        = flag.String("tag", "", "suffix for output file name")
		jobsN      = flag.Int("jobs", 20, "parallel jobs")

		sampleDivs = flag.String("sample-div", "32", "sampled set ratio 1/N (list)")
		sampleMode = flag.String("sample-mode", "set", "set | traffic (list)")
		sampleBits = flag.Int("sample-bits", 12, "prefix bits hashed for traffic sampling")
		epochs     = flag.String("epoch", "100000", "epoch lengths (list)")
		ths        = flag.String("threshold", "0.005", "switch thresholds (list)")
		switches   = flag.String("switch", "flush,keep,dual,rehash", "switch methods (list)")
		dualWin    = flag.Int("dual-window", 0, "dual probe window in packets (0 = 4*capacity)")
		initials   = flag.String("initial", "18", "initial index lengths (list)")
		neighbors  = flag.String("neighbor", "0", "neighbor windows (list, 0 = all candidates)")
		rovers     = flag.String("rover", "false", "add a roving shadow in neighbor mode (list of true/false)")
		tagBits    = flag.String("tag-bits", "0", "shadow partial tag bits (list, 0 = full)")
		decay      = flag.Bool("decay", false, "halve counters at epoch end instead of reset")
		dbgEpochs  = flag.Int("debug-epochs", 0, "print per-candidate shadow hit rates for the first N epochs")
		seriesWin  = flag.Int("series-window", 0, "write hit-rate time series with this window")

		regionG         = flag.String("region-g", "4,8,12,16", "region granularities")
		regionTableBits = flag.String("region-table-bits", "8,10,12,14,16", "hashed region table size bits (list)")
		hotEntries      = flag.String("hot-entries", "8,16,32,64,128", "hot-region table entries (list)")
		hotG            = flag.Int("hot-g", 18, "region bits of the hot-region table combined with shadow")
		shadowHot       = flag.String("shadow-hot", "0", "hot-region entries combined with shadow (list, 0 = off)")
		hotDefaults     = flag.String("hot-default", "14,16,18", "default index length outside hot regions (list)")
		regionInit      = flag.Int("region-initial", 18, "initial L of every region for region-online")
		trainPkts       = flag.String("train-packets", "10000,100000,1000000", "static-train: packets used to choose L (list)")
		evalStart       = flag.Int("eval-start", 1000000, "static-train: first packet of the evaluation range")
		trainFrac       = flag.Float64("train-frac", 0.5, "fraction of trace used for offline region training")

		splitSpec = flag.String("split", "4:16:20,4:16:24,4:18:22,4:18:24,4:20:24,2:16:20,6:16:20", "wayA:la:lb list")
	)
	flag.Parse()
	if *traceFiles == "" || *name == "" {
		fmt.Fprintln(os.Stderr, "-trace and -name are required")
		os.Exit(2)
	}
	debugEpochs = *dbgEpochs
	switch *indexKind {
	case "crc":
		// Deprecated: 旧結果の再現用
		fmt.Fprintln(os.Stderr, "warning: -index crc is deprecated; use -index direct")
	case "direct":
		directIndex = true
	default:
		fmt.Fprintf(os.Stderr, "unknown -index %s\n", *indexKind)
		os.Exit(2)
	}
	t := loadTraces(strings.Split(*traceFiles, ","), *maxPer)
	n := len(t.dst)
	fmt.Fprintf(os.Stderr, "%s: %d packets\n", *name, n)
	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		panic(err)
	}
	capList := parseInts(*caps)
	if *fixedIndex < 0 || *fixedIndex > 32 {
		fmt.Fprintf(os.Stderr, "invalid -fixed-index %d: expected 0..32\n", *fixedIndex)
		os.Exit(2)
	}
	candList := parseInts(*cands)

	var jobs []func() *result
	add := func(f func() *result) { jobs = append(jobs, f) }

	switch *mode {
	case "static":
		for _, c := range capList {
			if *fixedIndex > 0 {
				fixed := *fixedIndex
				add(func() *result { return runStatic(t, 0, n, c, *way, fixed) })
				continue
			}
			for l := 9; l <= 24; l++ {
				add(func() *result { return runStatic(t, 0, n, c, *way, l) })
			}
			add(func() *result { return runIdeal(t, c, *way) })
		}
	case "static-train":
		// 実際に作れる静的方式：先頭 train 個のパケットで固定 L を選び、残り [evalFrom, n) を固定 L で評価する。
		// 比較用に、評価区間での各固定 L も出す（評価区間でのオラクルと /18）。
		evalFrom := *evalStart
		for _, c := range capList {
			for _, tr := range parseInts(*trainPkts) {
				add(func() *result {
					best, bestHit := 0, uint64(0)
					for l := 9; l <= 24; l++ {
						if r := runStatic(t, 0, tr, c, *way, l); r.Hits > bestHit {
							best, bestHit = l, r.Hits
						}
					}
					r := runStatic(t, evalFrom, n, c, *way, best)
					r.Policy, r.Params = "static-train", fmt.Sprintf("train=%d;L=%d", tr, best)
					return r
				})
			}
			for l := 9; l <= 24; l++ {
				add(func() *result {
					r := runStatic(t, evalFrom, n, c, *way, l)
					r.Policy = "static-eval"
					return r
				})
			}
		}
	case "static-switch":
		// 実運用どおりの静的方式：[0, tr) は初期 L で転送しつつ、同じ [0, tr) で /9〜/24 を試して最良 L を選ぶ。
		// tr パケット目で L を書き換えて flush し、[tr, n) は選んだ L で転送する。全区間 [0, n) のヒット率を出す。
		for _, c := range capList {
			for _, tr := range parseInts(*trainPkts) {
				for _, ini := range parseInts(*initials) {
					add(func() *result { return runStaticSwitch(t, c, *way, ini, tr) })
				}
			}
		}
	case "shadow":
		for _, c := range capList {
			for _, div := range parseInts(*sampleDivs) {
				for _, ep := range parseInts(*epochs) {
					for _, thS := range strings.Split(*ths, ",") {
						th, _ := strconv.ParseFloat(thS, 64)
						for _, sw := range strings.Split(*switches, ",") {
							for _, nb := range parseInts(*neighbors) {
								for _, tb := range parseInts(*tagBits) {
									for _, ini := range parseInts(*initials) {
										for _, sm := range strings.Split(*sampleMode, ",") {
											for _, he := range parseInts(*shadowHot) {
												w := *dualWin
												if w == 0 {
													w = 4 * c
												}
												for _, rv := range strings.Split(*rovers, ",") {
													cfg := shadowConfig{Cands: candList, Neighbor: nb, Rover: rv == "true", SampleDiv: div, SampleMode: sm, SampleBits: *sampleBits,
														Epoch: ep, Threshold: th, Initial: ini, Switch: sw, DualWindow: w, TagBits: tb, Decay: *decay, SeriesWin: *seriesWin,
														HotEntries: he, HotG: *hotG}
													add(func() *result { return runShadow(t, c, *way, cfg) })
												}
											}
										}
									}
								}
							}
						}
					}
				}
			}
		}
	case "region":
		split := int(float64(n) * *trainFrac)
		for _, c := range capList {
			for _, g := range parseInts(*regionG) {
				add(func() *result {
					return runRegion(t, split, n, c, *way, trainRegionOracle(t, split, c, *way, g, candList), "oracle")
				})
				add(func() *result {
					return runRegion(t, split, n, c, *way, trainRegionMode(t, split, g, candList), "mode")
				})
			}
			// 同じテスト区間での静的 L（比較用）
			for _, l := range candList {
				add(func() *result {
					r := runRegion(t, split, n, c, *way, &regionTable{l: []int8{int8(l)}}, "baseline-static")
					r.Params, r.TableBits = fmt.Sprintf("L=%d", l), 0
					return r
				})
			}
		}
	case "region-online":
		for _, c := range capList {
			for _, g := range parseInts(*regionG) {
				for _, upd := range []string{"miss", "all"} {
					add(func() *result { return runRegionOnline(t, c, *way, g, g, candList, *regionInit, "last", upd, 0) })
					for _, cb := range []int{2, 3, 4} {
						add(func() *result { return runRegionOnline(t, c, *way, g, g, candList, *regionInit, "majority", upd, cb) })
					}
				}
			}
		}
	case "region-hashed":
		for _, c := range capList {
			for _, g := range parseInts(*regionG) {
				for _, tb := range parseInts(*regionTableBits) {
					if tb > g {
						continue
					}
					add(func() *result {
						return runRegionOnline(t, c, *way, g, tb, candList, *regionInit, "majority", "miss", 3)
					})
				}
			}
		}
	case "hot-region":
		for _, c := range capList {
			for _, k := range parseInts(*hotEntries) {
				for _, def := range parseInts(*hotDefaults) {
					for _, g := range parseInts(*regionG) {
						add(func() *result { return runHotRegion(t, c, *way, g, k, def, candList) })
					}
				}
			}
		}
	case "split":
		for _, c := range capList {
			for _, spec := range strings.Split(*splitSpec, ",") {
				p := parseInts(strings.ReplaceAll(spec, ":", ","))
				add(func() *result { return runSplit(t, c, *way, p[0], p[1], p[2]) })
			}
		}
	default:
		fmt.Fprintf(os.Stderr, "unknown mode %s\n", *mode)
		os.Exit(2)
	}

	results := make([]*result, len(jobs))
	sem := make(chan struct{}, *jobsN)
	var wg sync.WaitGroup
	for i, job := range jobs {
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			r := job()
			r.Trace = *name
			results[i] = r
		}()
	}
	wg.Wait()
	base := fmt.Sprintf("%s_%s%s", *name, *mode, *tag)
	writeResults(filepath.Join(*outDir, base+".csv"), results)
	if *seriesWin > 0 {
		writeSeries(filepath.Join(*outDir, base+"_series.csv"), results)
	}
}

func writeResults(path string, results []*result) {
	f, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	fmt.Fprintln(f, "trace,policy,params,capacity,way,packets,hits,hit_rate,probes_per_packet,switches,shadow_bits,table_bits,final_l,l_hist")
	for _, r := range results {
		keys := make([]int, 0, len(r.LHist))
		for l := range r.LHist {
			keys = append(keys, l)
		}
		sort.Ints(keys)
		hist := make([]string, 0, len(keys))
		for _, l := range keys {
			hist = append(hist, fmt.Sprintf("%d:%.3f", l, float64(r.LHist[l])/float64(r.Packets)))
		}
		fmt.Fprintf(f, "%s,%s,%s,%d,%d,%d,%d,%.6f,%.4f,%d,%d,%d,%s,%s\n",
			r.Trace, r.Policy, r.Params, r.Capacity, r.Way, r.Packets, r.Hits, r.hitRate(),
			float64(r.Probes)/float64(r.Packets), r.Switches, r.ShadowBits, r.TableBits, r.FinalL, strings.Join(hist, " "))
	}
	fmt.Fprintf(os.Stderr, "wrote %s\n", path)
}

func writeSeries(path string, results []*result) {
	f, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	fmt.Fprintln(f, "trace,policy,params,capacity,start,len,hits,active_l")
	for _, r := range results {
		for _, w := range r.Series {
			fmt.Fprintf(f, "%s,%s,%s,%d,%d,%d,%d,%d\n", r.Trace, r.Policy, r.Params, r.Capacity, w.Start, w.Len, w.Hits, w.Active)
		}
	}
	fmt.Fprintf(os.Stderr, "wrote %s\n", path)
}
