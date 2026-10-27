package main

import (
	"os"
	"path/filepath"
	"testing"

	"test-module/ipaddress"
)

func TestStreamReuseDistance(t *testing.T) {
	// a b a c b a: 2 回目の a の間には b だけ、2 回目の b の間には a・c、3 回目の a の間には c・b
	s := newStream("x", 2, 6)
	for _, k := range []uint64{1, 2, 1, 3, 2, 1} {
		s.add(k)
	}
	want := []int32{-1, -1, 1, -1, 2, 2}
	for i, d := range s.distances {
		if d != want[i] {
			t.Fatalf("distances = %v, want %v", s.distances, want)
		}
	}
	if s.hits() != 1 {
		t.Fatalf("hits = %d, want 1（容量 2 で距離 1 の 1 回だけ）", s.hits())
	}
	if s.runs != 6 || s.maxRun != 1 {
		t.Fatalf("runs = %d maxRun = %d", s.runs, s.maxRun)
	}
}

func TestStreamRun(t *testing.T) {
	s := newStream("x", 1, 5)
	for _, k := range []uint64{7, 7, 7, 8, 8} {
		s.add(k)
	}
	if s.runs != 2 || s.maxRun != 3 {
		t.Fatalf("runs = %d maxRun = %d, want 2 3", s.runs, s.maxRun)
	}
	if s.hits() != 3 {
		t.Fatalf("hits = %d, want 3（連続の参照は距離 0）", s.hits())
	}
}

func TestMaskTop(t *testing.T) {
	d := uint32(0x0a050001) // 10.5.0.1
	cases := map[int]uint32{0: 0, 8: 0x0a000000, 14: 0x0a040000, 24: 0x0a050000, 32: d}
	for length, want := range cases {
		if got := maskTop(d, length); got != want {
			t.Errorf("maskTop(/%d) = %08x, want %08x", length, got, want)
		}
	}
}

func TestLeafIndex(t *testing.T) {
	// 10.0.0.0/8 の中に 10.1.2.0/24 がある
	rule := filepath.Join(t.TempDir(), "rule")
	if err := os.WriteFile(rule, []byte("10.0.0.0 8 a\n10.1.2.0 24 b\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	rt, err := loadRoutingTable(rule)
	if err != nil {
		t.Fatal(err)
	}
	cases := map[string]int{
		"10.5.0.1": 14, // 10.4.0.0/14 には /24 がない、10.0.0.0/13 にはある
		"10.1.2.3": 24, // /24 そのもの
		"10.1.3.1": 24, // 10.1.3.0/24 は /24 の隣で、10.1.2.0/23 には /24 がある
		"11.0.0.1": 8,  // どの prefix にも当たらない（default route なし）。11.0.0.0/8 に長い prefix はない
	}
	for ip, want := range cases {
		if got := leafIndex(ipaddress.NewIPaddress(ip), rt); got != want {
			t.Errorf("leafIndex(%s) = %d, want %d", ip, got, want)
		}
	}
}
