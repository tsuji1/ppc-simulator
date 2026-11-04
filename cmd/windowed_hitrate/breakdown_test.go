package main

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"test-module/cache"
)

var tagLengthWay8 = [][2]int{{9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}}

func TestFALRU(t *testing.T) {
	c := newFALRU(2)
	steps := []struct {
		key uint64
		hit bool
	}{{1, false}, {2, false}, {1, true}, {3, false}, {2, false}, {1, false}, {3, false}}
	for i, s := range steps {
		if got := c.access(s.key); got != s.hit {
			t.Fatalf("step %d key %d: hit=%v、期待 %v", i, s.key, got, s.hit)
		}
	}
}

// writeBreakdownFixture は乱数の宛先の text trace と、長さの違うプレフィクスを持つ rule を書く。
func writeBreakdownFixture(t *testing.T, packets int) (rule, trace string) {
	t.Helper()
	dir := t.TempDir()
	rule = filepath.Join(dir, "rule.txt")
	trace = filepath.Join(dir, "trace.txt")
	rules := []string{"0.0.0.0 0 0", "10.0.0.0 8 1", "10.1.0.0 16 2", "172.16.0.0 12 3"}
	for i := 0; i < 40; i++ {
		rules = append(rules, fmt.Sprintf("192.168.%d.0 24 %d", i, 10+i), fmt.Sprintf("20.%d.0.0 18 %d", i*4, 60+i))
	}
	if err := os.WriteFile(rule, []byte(strings.Join(rules, "\n")+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	r := rand.New(rand.NewSource(1))
	var lines []string
	for i := 0; i < packets; i++ {
		var dst string
		switch r.Intn(5) {
		case 0:
			dst = fmt.Sprintf("10.%d.%d.1", r.Intn(4), r.Intn(256))
		case 1:
			dst = fmt.Sprintf("172.%d.%d.1", 16+r.Intn(16), r.Intn(256))
		case 2, 3:
			dst = fmt.Sprintf("192.168.%d.%d", r.Intn(40), r.Intn(256))
		default:
			dst = fmt.Sprintf("20.%d.%d.1", r.Intn(160), r.Intn(256))
		}
		lines = append(lines, "0 0 1.1.1.1 "+dst+" tcp 1 2")
	}
	if err := os.WriteFile(trace, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return rule, trace
}

func runBreakdown(t *testing.T, opts options) ([]runState, breakdownJSON) {
	t.Helper()
	table, err := loadRoutingTable(opts.ruleFile)
	if err != nil {
		t.Fatal(err)
	}
	configs, err := buildConfigSpecs(opts)
	if err != nil {
		t.Fatal(err)
	}
	runs, err := buildWarmRuns(configs, opts, table)
	if err != nil {
		t.Fatal(err)
	}
	b, err := newBreakdown(opts, runs)
	if err != nil {
		t.Fatal(err)
	}
	writer := csv.NewWriter(io.Discard)
	if _, err := processTrace(opts, table, func(p *cache.MinPacket) error {
		b.observe(p)
		return processMinPacket(writer, opts, time.Now(), runs, p)
	}); err != nil {
		t.Fatal(err)
	}
	if err := b.write(opts); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(opts.breakdownJSON)
	if err != nil {
		t.Fatal(err)
	}
	var got breakdownJSON
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatal(err)
	}
	return runs, got
}

// set が 1 つ（8 entry・8-way、direct L=0）の VPLC は fully associative LRU なので、ミス数が FA LRU と一致する。
func TestBreakdownFAMatchesSingleSetCache(t *testing.T) {
	rule, trace := writeBreakdownFixture(t, 3000)
	opts := options{
		ruleFile: rule, trace: trace, way: 8, windows: []uint64{1000}, insertionPolicy: "exclusive",
		mpConfigs: []mpConfigSpec{{refbits: []int{24, 18}, capacities: []int{8, 8}}}, mpIndexes: []string{"direct"},
		psCapacity: 8, psIndexTypes: []int{cache.CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE}, cacheTagLength: tagLengthWay8,
		breakdownJSON: filepath.Join(t.TempDir(), "b.json"), breakdownWindow: 500,
	}
	runs, got := runBreakdown(t, opts)
	var cacheMisses uint64
	for _, r := range runs {
		if r.config.family == "Prefix-Shared-Cache" {
			cacheMisses = r.cumulativePackets - r.cumulativeHits
		}
	}
	if got.Packets != 3000 || got.FAMisses != cacheMisses {
		t.Fatalf("packets=%d FA ミス=%d、cache のミス=%d", got.Packets, got.FAMisses, cacheMisses)
	}
	if got.FirstReferences == 0 || got.FirstReferences+got.Rejected > got.FAMisses {
		t.Fatalf("初回参照 %d + 挿入しない %d が FA ミス %d を超える", got.FirstReferences, got.Rejected, got.FAMisses)
	}
	if got.Observers[0].Windows != 6 || got.Observers[0].Sets != 1 {
		t.Fatalf("observer: %+v", got.Observers[0])
	}
}

// ideal は /16 以下の entry を宛先の上位 16 bit で複数の set に入れ、direct L=9 は 1 つの set にまとめる。
func TestBreakdownSetLoad(t *testing.T) {
	rule, trace := writeBreakdownFixture(t, 4000)
	opts := options{
		ruleFile: rule, trace: trace, way: 8, windows: []uint64{1000}, insertionPolicy: "exclusive",
		mpConfigs: []mpConfigSpec{{refbits: []int{24, 18}, capacities: []int{64, 64}}}, mpIndexes: []string{"direct"},
		psCapacity: 128, psIndexTypes: []int{cache.CACHE_INDEX_TYPE_IDEAL, cache.CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE + 9},
		cacheTagLength: tagLengthWay8, breakdownJSON: filepath.Join(t.TempDir(), "b.json"), breakdownWindow: 1000,
	}
	_, got := runBreakdown(t, opts)
	byType := map[int]breakdownObserverJSON{}
	for _, o := range got.Observers {
		byType[o.CacheIndexType] = o
	}
	ideal := byType[cache.CACHE_INDEX_TYPE_IDEAL]
	direct9 := byType[cache.CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE+9]
	// 10.0.0.0/8 と 172.16.0.0/12 の packet は /9 の entry になる。ideal は上位 16 bit で set を選ぶので同じ entry が複数の set に入る。
	if ideal.Dup <= 1.0 {
		t.Fatalf("ideal の dup = %v、1 を超えるはず", ideal.Dup)
	}
	// direct L=9 は上位 9 bit で set を選ぶので、/9 以上の entry は 1 つの set にしか入らない。
	if math.Abs(direct9.Dup-1.0) > 1e-12 {
		t.Fatalf("direct L=9 の dup = %v、1 のはず", direct9.Dup)
	}
}

func TestSetLoadObserverClose(t *testing.T) {
	o := &setLoadObserver{sets: 4, way: 2, pairs: map[uint64]struct{}{}}
	// set 0 に 4 entry、set 1 に 2 entry、set 2・3 は空。key は 6 個
	for i, set := range []uint64{0, 0, 0, 0, 1, 1} {
		o.pairs[set<<37|uint64(i)] = struct{}{}
	}
	o.close(6)
	// 平均 1.5、分散 ((2.5)^2 + 0.5^2 + 1.5^2 + 1.5^2) / 4 = 2.75
	want := map[string][2]float64{
		"dup": {o.sumDup, 1}, "dispersion": {o.sumDispersion, 2.75 / 1.5},
		"overflow": {o.sumOverflow, 2.0 / 6}, "max_over_mean": {o.sumMaxOverMean, 4 / 1.5},
	}
	for name, v := range want {
		if math.Abs(v[0]-v[1]) > 1e-12 {
			t.Fatalf("%s = %v、期待 %v", name, v[0], v[1])
		}
	}
	if len(o.pairs) != 0 || o.windows != 1 {
		t.Fatalf("window を閉じた後: pairs=%d windows=%d", len(o.pairs), o.windows)
	}
}
