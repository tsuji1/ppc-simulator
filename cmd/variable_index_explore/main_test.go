package main

import (
	"encoding/binary"
	"encoding/gob"
	"math/rand"
	"os"
	"path/filepath"
	"testing"

	"test-module/cache"
)

// ip は a.b.c.d を uint32 にする。
func ip(a, b, c, d byte) uint32 { return binary.BigEndian.Uint32([]byte{a, b, c, d}) }

func withDirectIndex(t *testing.T, v bool) {
	t.Helper()
	prev := directIndex
	directIndex = v
	t.Cleanup(func() { directIndex = prev })
}

// ---------------------------------------------------------------- setArray

func TestSetArrayLRUEviction(t *testing.T) {
	// 1 set / 2 way。A B A C B の順で A=miss B=miss A=hit C=miss(B を追い出す) B=miss
	a := newSetArray(1, 2)
	A, B, C := ip(10, 0, 0, 1), ip(10, 0, 1, 1), ip(10, 0, 2, 1)
	want := []bool{false, false, true, false, false}
	for i, dst := range []uint32{A, B, A, C, B} {
		if got := a.access(0, dst, 24); got != want[i] {
			t.Fatalf("access %d: hit=%v, want %v", i, got, want[i])
		}
	}
	// 最後に B が MRU、C が LRU（A は C の挿入で、B は再挿入で押し出された）
	if a.tags[0] != makeKey(B, 24) || a.tags[1] != makeKey(C, 24) {
		t.Fatalf("LRU order = %x, want [B C]", a.tags)
	}
}

func TestSetArrayLongestMatchInSet(t *testing.T) {
	a := newSetArray(1, 4)
	dst := ip(10, 1, 2, 3)
	a.insert(0, makeKey(dst, 16))
	a.insert(0, makeKey(dst, 24))
	a.insert(0, makeKey(ip(10, 9, 9, 9), 24)) // 別の prefix
	pos := a.lookup(0, dst)
	if pos < 0 || a.tags[pos] != makeKey(dst, 24) {
		t.Fatalf("lookup picked %x, want the /24", a.tags[pos])
	}
	// /24 の外側（10.1.3.0）は /16 にだけ一致する
	pos = a.lookup(0, ip(10, 1, 3, 0))
	if pos < 0 || a.tags[pos] != makeKey(dst, 16) {
		t.Fatalf("lookup for 10.1.3.0 picked %v, want the /16", pos)
	}
	if a.lookup(0, ip(11, 0, 0, 0)) != -1 {
		t.Fatal("unrelated address should miss")
	}
}

func TestNonInsertablePacketIsNeverCached(t *testing.T) {
	a := newSetArray(1, 2)
	dst := ip(192, 0, 2, 1)
	for i := 0; i < 3; i++ {
		if a.access(0, dst, -1) {
			t.Fatal("clen=-1 packet must not hit")
		}
	}
	if a.tags[0] != 0 || a.tags[1] != 0 {
		t.Fatal("clen=-1 packet must not be inserted")
	}
}

func TestTraceAppendClampsInsertLength(t *testing.T) {
	tr := &trace{}
	for _, leaf := range []int{-1, 0, 1, 8, 9, 24, 25, 32} {
		tr.append(0, leaf)
	}
	want := []int8{-1, 9, 9, 9, 9, 24, -1, -1}
	for i := range want {
		if tr.clen[i] != want[i] {
			t.Fatalf("leaf idx %d: clen=%d, want %d", i, tr.clen[i], want[i])
		}
	}
}

func TestIndexOfDirect(t *testing.T) {
	withDirectIndex(t, true)
	// L=24 の下位 3 bit = 第 3 octet の下位 3 bit
	if got := indexOf(ip(10, 0, 5, 0), 24, 8); got != 5 {
		t.Fatalf("direct L=24 index = %d, want 5", got)
	}
	// L=16 の下位 3 bit = 第 2 octet の下位 3 bit
	if got := indexOf(ip(10, 6, 5, 0), 16, 8); got != 6 {
		t.Fatalf("direct L=16 index = %d, want 6", got)
	}
}

// ---------------------------------------------------------------- static vs. independent reference

// refLRU は setArray と独立に書いた参照実装（set ごとに MRU 先頭の slice）。
type refLRU struct {
	way  int
	sets map[int][]struct {
		net uint32
		l   int
	}
}

func (r *refLRU) access(set int, dst uint32, clen int8) bool {
	entries := r.sets[set]
	best := -1
	for i, e := range entries {
		if dst>>(32-e.l) == e.net && (best < 0 || e.l > entries[best].l) {
			best = i
		}
	}
	if best >= 0 {
		e := entries[best]
		entries = append(entries[:best], entries[best+1:]...)
		r.sets[set] = append([]struct {
			net uint32
			l   int
		}{e}, entries...)
		return true
	}
	if clen > 0 {
		e := struct {
			net uint32
			l   int
		}{dst >> (32 - int(clen)), int(clen)}
		entries = append([]struct {
			net uint32
			l   int
		}{e}, entries...)
		if len(entries) > r.way {
			entries = entries[:r.way]
		}
		r.sets[set] = entries
	}
	return false
}

func randomTrace(seed int64, n int) *trace {
	rng := rand.New(rand.NewSource(seed))
	tr := &trace{}
	// 少数の /16 に集中させて hit と衝突の両方を起こす
	for i := 0; i < n; i++ {
		dst := uint32(rng.Intn(4))<<24 | uint32(rng.Intn(8))<<16 | uint32(rng.Intn(64))<<8 | uint32(rng.Intn(256))
		leaf := []int{-1, 12, 16, 20, 24, 24}[rng.Intn(6)]
		tr.append(dst, leaf)
	}
	return tr
}

func TestRunStaticMatchesReference(t *testing.T) {
	for _, direct := range []bool{false, true} {
		withDirectIndex(t, direct)
		tr := randomTrace(1, 20000)
		for _, l := range []int{12, 16, 18, 24} {
			const capacity, way = 64, 4
			nsets := capacity / way
			ref := &refLRU{way: way, sets: map[int][]struct {
				net uint32
				l   int
			}{}}
			var refHits uint64
			for i, dst := range tr.dst {
				if ref.access(indexOf(dst, l, nsets), dst, tr.clen[i]) {
					refHits++
				}
			}
			got := runStatic(tr, 0, len(tr.dst), capacity, way, l)
			if got.Hits != refHits {
				t.Fatalf("direct=%v L=%d: runStatic hits=%d, reference=%d", direct, l, got.Hits, refHits)
			}
			if refHits == 0 || refHits == uint64(len(tr.dst)) {
				t.Fatalf("direct=%v L=%d: degenerate trace (hits=%d)", direct, l, refHits)
			}
		}
	}
}

// ---------------------------------------------------------------- partial tag (shadow)

func TestShadowPartialTagFalseHit(t *testing.T) {
	// 部分 tag が衝突する 2 つの /24 を探す
	const bits = 4
	base := ip(10, 0, 0, 0)
	var other uint32
	k0 := shadowKey(base>>8, 24, bits)
	for c := uint32(1); c < 1<<16; c++ {
		cand := base + c<<8
		if shadowKey(cand>>8, 24, bits) == k0 {
			other = cand
			break
		}
	}
	if other == 0 {
		t.Fatal("no aliasing prefix found")
	}

	partial := &shadowArray{setArray: newSetArray(1, 2), tagBits: bits}
	partial.access(0, base, 24)
	if !partial.access(0, other, 24) {
		t.Fatal("partial tag: aliasing prefix should (falsely) hit")
	}

	full := &shadowArray{setArray: newSetArray(1, 2), tagBits: 0}
	full.access(0, base, 24)
	if full.access(0, other, 24) {
		t.Fatal("full tag: different prefix must not hit")
	}
	if !full.access(0, base+1, 24) {
		t.Fatal("full tag: same /24 must hit")
	}
}

// ---------------------------------------------------------------- switchIndex

func TestSwitchIndexFlushAndKeep(t *testing.T) {
	a := newSetArray(4, 2)
	a.insert(1, makeKey(ip(10, 0, 0, 0), 24))
	before := append([]uint64(nil), a.tags...)

	switchIndex(a, "keep", 16, 4)
	for i := range before {
		if a.tags[i] != before[i] {
			t.Fatal("keep must not touch the array")
		}
	}
	switchIndex(a, "dual", 16, 4)
	for i := range before {
		if a.tags[i] != before[i] {
			t.Fatal("dual must not touch the array at switch time")
		}
	}
	switchIndex(a, "flush", 16, 4)
	for _, k := range a.tags {
		if k != 0 {
			t.Fatal("flush must clear every entry")
		}
	}
}

func TestSwitchIndexRehash(t *testing.T) {
	withDirectIndex(t, true)
	const nsets, way = 8, 2
	a := newSetArray(nsets, way)
	long := ip(10, 3, 5, 0)  // /24
	short := ip(10, 3, 0, 0) // /16
	// L=16 で index した状態（どちらも set 3）
	a.insert(indexOf(long, 16, nsets), makeKey(long, 24))
	a.insert(indexOf(short, 16, nsets), makeKey(short, 16))

	switchIndex(a, "rehash", 24, nsets)

	// /24 は L=24 の set（第 3 octet=5）に移り、新 index で引ける
	if pos := a.lookup(indexOf(long, 24, nsets), long); pos < 0 || a.tags[indexOf(long, 24, nsets)*way+pos] != makeKey(long, 24) {
		t.Fatal("rehash: /24 entry should be reachable at its L=24 set")
	}
	// /16 は L=24 の index に必要な bit が無いので捨てる
	for _, k := range a.tags {
		if k == makeKey(short, 16) {
			t.Fatal("rehash: entry shorter than the new L must be dropped")
		}
	}
}

func TestSwitchIndexRehashKeepsMRUOrder(t *testing.T) {
	withDirectIndex(t, true)
	const nsets, way = 8, 2
	a := newSetArray(nsets, way)
	// 同じ L=24 set（第 3 octet=1）に落ちる 3 entry を、旧 index (L=16) の別々の set に置く
	x, y, z := ip(10, 0, 1, 0), ip(10, 1, 1, 0), ip(10, 2, 1, 0)
	a.insert(0, makeKey(z, 24)) // set 0: z
	a.insert(1, makeKey(y, 24)) // set 1: y
	a.insert(2, makeKey(x, 24)) // set 2: x
	switchIndex(a, "rehash", 24, nsets)
	// 3 個のうち 2 個しか入らない。全部 MRU 位置なので、set 番号の大きい（後から入れた）方が残る
	set := indexOf(x, 24, nsets)
	got := a.tags[set*way : set*way+way]
	if got[0] != makeKey(x, 24) || got[1] != makeKey(y, 24) {
		t.Fatalf("rehash result %x, want [x y]", got)
	}
}

func TestDualProbeMovesEntry(t *testing.T) {
	a := newSetArray(4, 2)
	dst := ip(10, 0, 3, 1)
	k := makeKey(dst, 24)
	a.insert(0, makeKey(ip(10, 9, 0, 0), 24))
	a.insert(0, k) // 旧 set 0 に [k, other]
	if !dualProbe(a, 3, 0, dst) {
		t.Fatal("dual probe should find the entry in the old set")
	}
	if a.tags[3*2] != k {
		t.Fatal("found entry must move to the MRU of the new set")
	}
	if a.lookup(0, dst) >= 0 {
		t.Fatal("found entry must be removed from the old set (no duplicate)")
	}
	if a.tags[0] != makeKey(ip(10, 9, 0, 0), 24) || a.tags[1] != 0 {
		t.Fatalf("old set after move = %x, want [other, empty]", a.tags[0:2])
	}
	if dualProbe(a, 3, 0, ip(11, 0, 0, 0)) {
		t.Fatal("absent address must not hit")
	}
}

// ---------------------------------------------------------------- runShadow

// switchTrace は L=24 なら全 entry が収まり、L=16 なら 1 set に集中して thrash する trace。
// direct index・8 set・2 way（容量 16）で、10.0.c.0/24（c=1..7）を順に繰り返す。
// L=16 の index は第 2 octet=0 なので全部 set 0、L=24 の index は c（1..7）なので set 0 を使わない。
const switchEntries = 7

func switchTrace(rounds int) *trace {
	tr := &trace{}
	for r := 0; r < rounds; r++ {
		for c := 1; c <= switchEntries; c++ {
			tr.append(ip(10, 0, byte(c), 1), 24)
		}
	}
	return tr
}

func baseShadowConfig() shadowConfig {
	return shadowConfig{
		Cands:      []int{16, 24},
		SampleDiv:  1, // 全 set を sampled（shadow = 本体と同じ大きさ）
		SampleMode: "set",
		Epoch:      8 * switchEntries, // 8 周で 1 epoch（epoch 末は周の切れ目）
		Threshold:  0.01,
		Initial:    16,
		Switch:     "keep",
	}
}

func TestRunShadowSwitchesToBetterL(t *testing.T) {
	withDirectIndex(t, true)
	tr := switchTrace(40)
	cfg := baseShadowConfig()
	res := runShadow(tr, 16, 2, cfg)
	if res.Switches != 1 || res.FinalL != "24" {
		t.Fatalf("switches=%d final=%s, want 1 switch to 24", res.Switches, res.FinalL)
	}
	// 最初の epoch は L=16、残りは L=24
	if res.LHist[16] != uint64(cfg.Epoch) || res.LHist[24] != uint64(len(tr.dst)-cfg.Epoch) {
		t.Fatalf("LHist=%v", res.LHist)
	}
	static16 := runStatic(tr, 0, len(tr.dst), 16, 2, 16)
	if static16.Hits != 0 {
		t.Fatalf("static L=16 should thrash, got %d hits", static16.Hits)
	}
	// keep では切替後 1 周で温まり、その後は全部 hit
	if want := uint64(len(tr.dst) - cfg.Epoch - switchEntries); res.Hits != want {
		t.Fatalf("hits=%d, want %d", res.Hits, want)
	}
}

func TestRunShadowThresholdPreventsSwitch(t *testing.T) {
	withDirectIndex(t, true)
	cfg := baseShadowConfig()
	cfg.Threshold = 1.0 // hit rate 差は 1 を超えないので切り替わらない
	res := runShadow(switchTrace(40), 16, 2, cfg)
	if res.Switches != 0 || res.FinalL != "16" {
		t.Fatalf("switches=%d final=%s, want no switch", res.Switches, res.FinalL)
	}
}

func runSwitchMethods(t *testing.T, tr *trace, cfg shadowConfig) (map[string]uint64, map[string]uint64) {
	t.Helper()
	hits, probes := map[string]uint64{}, map[string]uint64{}
	for _, m := range []string{"flush", "keep", "dual", "rehash"} {
		c := cfg
		c.Switch = m
		c.DualWindow = cfg.Epoch
		res := runShadow(tr, 16, 2, c)
		if res.Switches != 1 {
			t.Fatalf("%s: switches=%d", m, res.Switches)
		}
		hits[m], probes[m] = res.Hits, res.Probes
	}
	return hits, probes
}

func TestRunShadowSwitchMethods(t *testing.T) {
	withDirectIndex(t, true)
	tr := switchTrace(40)
	hits, probes := runSwitchMethods(t, tr, baseShadowConfig())
	// 切替時点で本体に残っているのは L=16 の set 0 にある 2 entry（10.0.6.0/24 と 10.0.7.0/24）。
	//   flush : 消す → 1 周分の再ウォームアップ
	//   keep  : 残るが、L=24 では set 6, 7 を引くので set 0 の entry に到達できない → flush と同じ
	//   dual  : 新 set で miss したとき旧 set 0 も引いて見つけ、新 set へ移す → 2 pkt 多く hit
	//   rehash: 切替時に 2 entry を新 set へ移す → 2 pkt 多く hit
	if hits["keep"] != hits["flush"] {
		t.Fatalf("keep=%d flush=%d, want equal", hits["keep"], hits["flush"])
	}
	if hits["dual"] != hits["flush"]+2 || hits["rehash"] != hits["flush"]+2 {
		t.Fatalf("hits=%v, want dual = rehash = flush+2", hits)
	}
	// dual は dual window の間、新 set で miss するたびに旧 set を追加 probe する
	if probes["dual"] <= probes["keep"] {
		t.Fatalf("dual probes=%d should exceed keep probes=%d", probes["dual"], probes["keep"])
	}
	for _, m := range []string{"flush", "keep", "rehash"} {
		if probes[m] != uint64(len(tr.dst)) {
			t.Fatalf("%s should probe once per packet: %v", m, probes)
		}
	}
}

func TestDualLosesEntriesWhenOldSetIsReused(t *testing.T) {
	// 10.0.c.0/24（c=0..15）を回す trace では、L=24 の新 set に c=0, 8 が set 0（＝旧 set）を使う。
	// 切替直後の c=0 と c=8 の挿入で旧 set 0 の生き残り（c=14, 15）が追い出されるので、
	// dual は c=14, 15 に来たときに何も見つけられない。rehash は切替時に移しているので +2。
	withDirectIndex(t, true)
	tr := &trace{}
	for r := 0; r < 40; r++ {
		for c := 0; c < 16; c++ {
			tr.append(ip(10, 0, byte(c), 1), 24)
		}
	}
	cfg := baseShadowConfig()
	cfg.Epoch = 64
	hits, _ := runSwitchMethods(t, tr, cfg)
	if hits["dual"] != hits["flush"] || hits["keep"] != hits["flush"] || hits["rehash"] != hits["flush"]+2 {
		t.Fatalf("hits=%v, want dual = keep = flush, rehash = flush+2", hits)
	}
}

func TestRunShadowTrafficSamplingSeesSamePackets(t *testing.T) {
	// traffic サンプリング（SampleDiv=1）でも同じ切替が起きる
	withDirectIndex(t, true)
	cfg := baseShadowConfig()
	cfg.SampleMode = "traffic"
	cfg.SampleBits = 24
	res := runShadow(switchTrace(40), 16, 2, cfg)
	if res.Switches != 1 || res.FinalL != "24" {
		t.Fatalf("traffic sampling: switches=%d final=%s", res.Switches, res.FinalL)
	}
}

// ---------------------------------------------------------------- input formats

func TestLoadGobMatchesDstLeaf(t *testing.T) {
	dir := t.TempDir()
	packets := []cache.MinPacket{
		{Proto: "tcp", DstIP: ip(1, 2, 3, 4), IsLeafIndex: 24},
		{Proto: "icmp", DstIP: ip(5, 6, 7, 8), IsLeafIndex: 16}, // TCP/UDP 以外は捨てる
		{Proto: "udp", DstIP: ip(9, 9, 9, 9), IsLeafIndex: 8},   // 9 に切り上げ
		{Proto: "tcp", DstIP: ip(8, 8, 8, 8), IsLeafIndex: -1},  // 挿入不可
		{Proto: "udp", DstIP: ip(7, 7, 7, 7), IsLeafIndex: 28},  // 24 超は挿入不可
	}
	gobPath := filepath.Join(dir, "x.gob")
	f, err := os.Create(gobPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := gob.NewEncoder(f).Encode(packets); err != nil {
		t.Fatal(err)
	}
	f.Close()

	// export_dst_leaf と同じ 5 byte 形式も作る
	leafPath := filepath.Join(dir, "x.dstleaf")
	var raw []byte
	for _, p := range packets {
		if p.FiveTuple() == nil {
			continue
		}
		var b [5]byte
		binary.LittleEndian.PutUint32(b[:4], p.DstIP)
		b[4] = byte(p.IsLeafIndex)
		raw = append(raw, b[:]...)
	}
	if err := os.WriteFile(leafPath, raw, 0o644); err != nil {
		t.Fatal(err)
	}

	g := loadTraces([]string{gobPath}, 0)
	d := loadTraces([]string{leafPath}, 0)
	wantDst := []uint32{ip(1, 2, 3, 4), ip(9, 9, 9, 9), ip(8, 8, 8, 8), ip(7, 7, 7, 7)}
	wantLen := []int8{24, 9, -1, -1}
	for name, tr := range map[string]*trace{"gob": g, "dstleaf": d} {
		if len(tr.dst) != len(wantDst) {
			t.Fatalf("%s: %d packets, want %d", name, len(tr.dst), len(wantDst))
		}
		for i := range wantDst {
			if tr.dst[i] != wantDst[i] || tr.clen[i] != wantLen[i] {
				t.Fatalf("%s[%d] = (%x,%d), want (%x,%d)", name, i, tr.dst[i], tr.clen[i], wantDst[i], wantLen[i])
			}
		}
	}
	// max は TCP/UDP パケット数で数える
	if got := loadTraces([]string{gobPath}, 2); len(got.dst) != 2 || got.dst[1] != ip(9, 9, 9, 9) {
		t.Fatalf("gob max=2: %v", got.dst)
	}
}
