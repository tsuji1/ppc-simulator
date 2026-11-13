package main

import (
	"math/rand"
	"os"
	"path/filepath"
	"test-module/cache"
	"test-module/routingtable"
	"testing"
)

func TestBaselineMatchesProductionPerPacket(t *testing.T) {
	table := routingtable.NewRoutingTablePatriciaTrie()
	path := filepath.Join(t.TempDir(), "default.rule")
	if err := os.WriteFile(path, []byte("0.0.0.0 0 1\n"), 0600); err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	table.ReadRule(f)
	tagLengths := make([][2]int, 8)
	for i := range tagLengths {
		tagLengths[i] = [2]int{9, 24}
	}
	for _, capacity := range []int{32, 256, 1024} {
		for _, indexType := range []int{108, 114, 118, 124, 2} {
			cfg := config{"baseline", "direct", []int{indexType - 100}}
			if indexType == 2 {
				cfg = config{"ideal", "ideal", nil}
			}
			got := newReplay(cfg, capacity, 8)
			want := cache.NewUnifiedCache(uint(capacity), 8, table, indexType, tagLengths, "exclusive", false)
			rng := rand.New(rand.NewSource(124))
			for i := 0; i < 30000; i++ {
				// Nonoverlapping leaf regions with host variation, bursts, /0 clamp,
				// and noninsertable /25 leaves. LRU replacement is exercised heavily.
				region := rng.Intn(24)
				leaf := int8(9 + region%17)
				if region == 0 {
					leaf = 0
				}
				dst := uint32(region)<<(32-9) | uint32(rng.Intn(64))<<8 | uint32(rng.Intn(256))
				p := packet{dst, leaf}
				f := &cache.FiveTuple{DstIP: dst, IsLeafIndex: leaf}
				wh, _ := want.IsCachedWithFiveTuple(f, true)
				if !wh {
					want.CacheFiveTuple(f)
				}
				if gh := got.access(p); gh != wh {
					t.Fatalf("capacity=%d index=%d packet=%d got=%v want=%v", capacity, indexType, i, gh, wh)
				}
			}
		}
	}
}

func TestFloorPlacementNeverUsesHostBits(t *testing.T) {
	for _, cfg := range configurations() {
		if cfg.kind != "floor" {
			continue
		}
		for length := 9; length <= 24; length++ {
			floor := floorLength(length, cfg.lengths)
			if floor > length {
				t.Fatal("host bits used")
			}
		}
	}
	r := newReplay(config{"three", "floor", []int{9, 16, 24}}, 1024, 8)
	if r.access(packet{0x0a010001, 16}) {
		t.Fatal("cold hit")
	}
	// Host bits and even the input leaf annotation cannot change lookup.
	if !r.access(packet{0x0a01ffff, -1}) {
		t.Fatal("short prefix must be shared")
	}
	count := 0
	for _, k := range r.tags {
		if k != 0 {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("short prefix duplicated: %d", count)
	}
}

func TestDense24sEscapeSinglePrefixSet(t *testing.T) {
	baseline := newReplay(config{"direct", "direct", []int{16}}, 1024, 8)
	probe := newReplay(config{"probe", "floor", []int{9, 16, 24}}, 1024, 8)
	bh, ph := 0, 0
	for i := 0; i < 640; i++ {
		p := packet{0x0a010001 | uint32(i%64)<<8, 24}
		if baseline.access(p) {
			bh++
		}
		if probe.access(p) {
			ph++
		}
	}
	if bh != 0 || ph != 576 {
		t.Fatalf("dense /24 baseline=%d probe=%d", bh, ph)
	}
}

func TestProbeLookupIndependentOfLeafAnnotation(t *testing.T) {
	a := newReplay(config{"probe", "floor", []int{9, 16, 20, 24}}, 256, 8)
	a.access(packet{0x0a010001, 16})
	for _, leaf := range []int8{-1, 0, 9, 16, 24, 32} {
		if !a.access(packet{0x0a01ff02, leaf}) {
			t.Fatalf("lookup used annotation %d", leaf)
		}
	}
}

func TestStagedEqualsParallelOnDisjointLeafRegions(t *testing.T) {
	for _, bits := range []int{0, 4, 10} {
		for _, cfg := range configurations() {
			if cfg.kind != "floor" {
				continue
			}
			a, b := newReplay(cfg, 256, 8), newReplay(cfg, 256, 8)
			b.staged = true
			if bits > 0 {
				b.predictor = make([]uint8, 1<<bits)
			}
			rng := rand.New(rand.NewSource(88))
			for i := 0; i < 50000; i++ {
				if i == 1000 {
					b.freezeOrder()
				}
				region := rng.Intn(24)
				leaf := int8(9 + region%17)
				dst := uint32(region)<<(32-9) | uint32(rng.Intn(64))<<8 | uint32(rng.Intn(256))
				p := packet{dst, leaf}
				ah, bh := a.access(p), b.access(p)
				if ah != bh {
					t.Fatalf("%s packet %d staged=%v parallel=%v", cfg.name, i, bh, ah)
				}
				if bh && i < 1000 {
					b.trainBucketHits[b.lastBucket]++
				}
			}
			for i := range a.tags {
				if a.tags[i] != b.tags[i] {
					t.Fatalf("%s cache state differs", cfg.name)
				}
			}
			if b.reads > a.reads {
				t.Fatal("staged used more reads")
			}
		}
	}
}
