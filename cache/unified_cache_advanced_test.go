package cache

import (
	"test-module/routingtable"
	"testing"
)

func newAdvancedPolicyTestCache(config UnifiedCacheIndexConfig) *UnifiedCache {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	return NewUnifiedCacheWithIndexConfig(
		8192,
		8,
		&routingTable,
		24,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		config,
		false,
	)
}

func TestUnifiedCacheLineWayQuotaProtectsWidePrefixWays(t *testing.T) {
	line := NewUnifiedCacheLine(
		8,
		nil,
		CACHE_INDEX_TYPE_PREFIX18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
		0,
	)
	line.ConfigureWayQuota(18, 2)

	for i := uint32(1); i <= 2; i++ {
		f := &FiveTuple{Proto: IP_TCP, DstIP: i << 14, IsLeafIndex: 18}
		line.CacheFiveTupleWithLength(f, 18)
	}
	for i := uint32(1); i <= 12; i++ {
		f := &FiveTuple{Proto: IP_TCP, DstIP: (0x800000 + i) << 8, IsLeafIndex: 24}
		line.CacheFiveTupleWithLength(f, 24)
	}

	wide := 0
	narrow := 0
	for _, elem := range line.Entries {
		entry := elem.Value.(UnifiedCacheLineEntry)
		if entry.Length <= 18 {
			wide++
		} else {
			narrow++
		}
	}
	if wide != 2 || narrow != 6 {
		t.Fatalf("resident quota groups = wide:%d narrow:%d, want wide:2 narrow:6", wide, narrow)
	}
}

func TestUnifiedCacheLengthAwareMultiProbeSelectsGlobalLPM(t *testing.T) {
	config := DefaultUnifiedCacheIndexConfig()
	config.LengthAwareMultiProbe = true
	config.MultiProbeLengths = []int{18, 20, 22, 24}
	cache := newAdvancedPolicyTestCache(config)
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a123456, IsLeafIndex: 24}

	set18 := cache.setIdxForType(f, 18, false)
	set24 := cache.setIdxForType(f, 24, false)
	cache.Sets[set18].CacheFiveTupleWithLength(f, 18)
	cache.Sets[set24].CacheFiveTupleWithLength(f, 24)

	candidates := cache.lookupSetIndices(f)
	hit, _ := cache.IsCachedWithFiveTuple(f, true)
	if !hit {
		t.Fatal("length-aware multi-probe missed a resident prefix")
	}
	if cache.SetProbeCount != uint64(len(candidates)) {
		t.Fatalf("SetProbeCount = %d, want %d", cache.SetProbeCount, len(candidates))
	}

	var hit18 uint32
	var hit24 uint32
	for i := range cache.Sets {
		hit18 += cache.Sets[i].HitCount[18]
		hit24 += cache.Sets[i].HitCount[24]
	}
	if hit18 != 0 || hit24 != 1 {
		t.Fatalf("LPM hit counts = /18:%d /24:%d, want /18:0 /24:1", hit18, hit24)
	}
}

func TestUnifiedCacheSkewedAssociativeChoosesEmptierSet(t *testing.T) {
	config := DefaultUnifiedCacheIndexConfig()
	config.SkewedAssociative = true
	cache := newAdvancedPolicyTestCache(config)

	var target *FiveTuple
	var primary uint
	var secondary uint
	for i := uint32(1); i < 1<<20; i++ {
		f := &FiveTuple{Proto: IP_TCP, DstIP: i << 8, IsLeafIndex: 24}
		p := cache.setIdxForType(f, 24, false)
		s := cache.setIdxForType(f, 24, true)
		if p != s {
			target = f
			primary = p
			secondary = s
			break
		}
	}
	if target == nil {
		t.Fatal("could not find a destination with distinct skew candidates")
	}

	for i := uint32(1); i <= 8; i++ {
		f := &FiveTuple{Proto: IP_TCP, DstIP: (0xf00000 + i) << 8, IsLeafIndex: 24}
		cache.Sets[primary].CacheFiveTupleWithLength(f, 24)
	}
	if got := cache.placementSetIndex(target, 24); got != secondary {
		t.Fatalf("placementSetIndex = %d, want emptier secondary set %d", got, secondary)
	}
	cache.Sets[cache.placementSetIndex(target, 24)].CacheFiveTupleWithLength(target, 24)
	if cache.Sets[primary].ResidentCount() != 8 || cache.Sets[secondary].ResidentCount() != 1 {
		t.Fatalf(
			"resident counts = primary:%d secondary:%d, want primary:8 secondary:1",
			cache.Sets[primary].ResidentCount(),
			cache.Sets[secondary].ResidentCount(),
		)
	}
}

func TestUnifiedCacheCombinedPolicyCountsUniqueParallelProbes(t *testing.T) {
	config := DefaultUnifiedCacheIndexConfig()
	config.LengthAwareMultiProbe = true
	config.MultiProbeLengths = []int{18, 20, 22, 24}
	config.SkewedAssociative = true
	cache := newAdvancedPolicyTestCache(config)
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0xc0a80101, IsLeafIndex: 24}

	candidates := cache.lookupSetIndices(f)
	cache.IsCachedWithFiveTuple(f, true)
	if len(candidates) < 2 || len(candidates) > 8 {
		t.Fatalf("unique candidate count = %d, want 2..8", len(candidates))
	}
	if cache.SetProbeCount != uint64(len(candidates)) {
		t.Fatalf("SetProbeCount = %d, want %d", cache.SetProbeCount, len(candidates))
	}
}
