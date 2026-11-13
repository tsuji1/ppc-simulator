package main

import (
	"math/rand"
	"os"
	"path/filepath"
	"reflect"
	"test-module/ipaddress"
	"testing"
)

func TestFIBShapeMatchesProductionSafeLeaf(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.rule")
	data := "0.0.0.0 0 1\n10.0.0.0 8 2\n10.1.0.0 16 2\n10.1.2.0 24 3\n10.1.2.128 25 4\n20.0.0.0 12 5\n"
	if err := os.WriteFile(path, []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	f, err := readFIBShape(path)
	if err != nil {
		t.Fatal(err)
	}
	production, err := loadRoutingTable(path)
	if err != nil {
		t.Fatal(err)
	}
	rng := rand.New(rand.NewSource(124))
	for i := 0; i < 2048; i++ {
		dst := rng.Uint32()
		if i%3 == 0 {
			dst = 0x0a010000 | (dst & 65535)
		}
		if i%5 == 0 {
			dst = 0x0a010200 | (dst & 255)
		}
		want := 32
		ip := ipaddress.NewIPaddress(dst)
		for n := 0; n <= 32; n++ {
			if production.IsLeaf(ip, n) {
				want = n
				break
			}
		}
		if got := f.safeLength(dst); got != want {
			t.Fatalf("sample %d: leaf %d != %d", i, got, want)
		}
	}
}

func TestFIBHistogramCoversExactlyCacheableSpace(t *testing.T) {
	f := newFIBShape()
	f.insert(0, 0)
	f.insert(0x0a010200, 25)
	// All of 2^32 IPv4 addresses is cacheable except this /24: its /25
	// route and implicit sibling both require an uncacheable length /25.
	for _, g := range []int{4, 8, 12, 16} {
		h := f.regionHist(g)
		var covered uint64
		for _, row := range h {
			for n := 9; n <= 24; n++ {
				covered += row[n] << (32 - max(n, g))
			}
		}
		if covered != (uint64(1)<<32)-256 {
			t.Fatalf("g%d covers %d", g, covered)
		}
	}
}

func TestFIBLengthRulesAndPackedTable(t *testing.T) {
	h := make([][25]uint64, 256)
	h[10][12], h[10][24] = 1, 16
	// Region 10: count/mode prefer numerous /24s; address/sqrt prefer
	// the broad /12. These are explicit fixed rules, not traffic fitting.
	for method, want := range map[string]int{"mode": 24, "count": 24, "sqrt": 12, "address": 12} {
		rt := buildFIBRegionTable(h, 8, method)
		if rt.lookup(0x0a010203) != want || rt.lookup(0x14000000) != 18 {
			t.Fatal(method, rt.histString())
		}
		if err := rt.writePacked(t.TempDir()); err != nil {
			t.Fatal(err)
		}
		dir := t.TempDir()
		if err := rt.writePacked(dir); err != nil {
			t.Fatal(err)
		}
		packed, err := os.ReadFile(filepath.Join(dir, rt.name()+".packed"))
		if err != nil {
			t.Fatal(err)
		}
		if len(packed) != 128 {
			t.Fatal(len(packed))
		}
		for i, n := range rt.lengths {
			if got := (packed[i/2] >> (4 * (i % 2))) & 15; got+9 != n {
				t.Fatal("packing mismatch")
			}
		}
	}
}

func TestRegionalSingleReadUsesDestinationOnlyAndFullTags(t *testing.T) {
	rt := &fibRegionTable{g: 8, method: "test", lengths: make([]uint8, 256)}
	for i := range rt.lengths {
		rt.lengths[i] = 24
	}
	rt.lengths[10] = 12
	before := append([]uint8(nil), rt.lengths...)
	r := newReplay(config{"regional", "direct", nil}, 1024, 8)
	r.region = rt
	if r.access(packet{0x0a000001, 12}) {
		t.Fatal("cold hit")
	}
	// Changing host bits and passing no leaf oracle still finds the entry.
	if !r.access(packet{0x0a0fffff, -1}) {
		t.Fatal("lookup used leaf annotation or insertion index differed")
	}
	if r.access(packet{0x14000001, 24}) {
		t.Fatal("cross-region false match")
	}
	if !r.access(packet{0x140000fe, -1}) {
		t.Fatal("/24 lost")
	}
	if r.reads != 4 || !reflect.DeepEqual(before, rt.lengths) {
		t.Fatal("extra read or mutable selector")
	}
}

func TestRegionSelectorCanResolveMixedGranularity(t *testing.T) {
	rt := &fibRegionTable{g: 8, method: "test", lengths: make([]uint8, 256)}
	for i := range rt.lengths {
		rt.lengths[i] = 24
	}
	rt.lengths[10] = 12
	r := newReplay(config{"regional", "direct", nil}, 1024, 8)
	r.region = rt
	fixed := newReplay(config{"fixed", "direct", []int{18}}, 1024, 8)
	var rh, fh int
	for i := 0; i < 4096; i++ {
		p := packet{0x0a000001 | uint32(i%1024)<<8, 12}
		if i%2 != 0 {
			p = packet{0x14000001 | uint32((i/2)%64)<<8, 24}
		}
		if r.access(p) {
			rh++
		}
		if fixed.access(p) {
			fh++
		}
	}
	if rh <= fh || r.reads != 4096 {
		t.Fatalf("regional=%d fixed=%d reads=%d", rh, fh, r.reads)
	}
}
