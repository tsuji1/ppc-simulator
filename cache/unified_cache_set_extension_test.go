package cache

import (
	"reflect"
	"test-module/routingtable"
	"testing"
)

func extensionTestConfig() UnifiedCacheIndexConfig {
	config := DefaultUnifiedCacheIndexConfig()
	config.SetExtensionPolicy = UnifiedCacheSetExtensionEpochRepeat
	config.SetExtensionCapacityMode = UnifiedCacheSetExtensionAdditive
	config.SetExtensionPoolRatio = 0.25
	config.SetExtensionEpochLength = 4
	config.SetExtensionPressureThreshold = 2
	config.SetExtensionMaxPerSet = 2
	return config
}

func newExtensionTestCache(t *testing.T, size uint, config UnifiedCacheIndexConfig) *UnifiedCache {
	t.Helper()
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	return NewUnifiedCacheWithIndexConfig(
		size,
		8,
		&routingTable,
		CACHE_INDEX_TYPE_PREFIX18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		config,
		false,
	)
}

func TestUnifiedCacheLineGrowPreservesBankSlotsAndGlobalLRU(t *testing.T) {
	line := NewUnifiedCacheLine(8, nil, CACHE_INDEX_TYPE_PREFIX18, [][2]int{{24, 24}}, UnifiedCacheInsertionPolicyExclusive, false, 0)
	for i := uint32(1); i <= 8; i++ {
		_, bank := line.CacheFiveTupleWithLengthAndBank(&FiveTuple{DstIP: i << 8, IsLeafIndex: 24}, 24)
		if bank != 0 {
			t.Fatalf("initial write bank = %d, want main", bank)
		}
	}
	line.GrowExtensionSet(1)
	if line.Size != 16 || line.ExtensionSetCount() != 1 {
		t.Fatalf("grown line size/extensions = %d/%d, want 16/1", line.Size, line.ExtensionSetCount())
	}
	for i := uint32(9); i <= 16; i++ {
		_, bank := line.CacheFiveTupleWithLengthAndBank(&FiveTuple{DstIP: i << 8, IsLeafIndex: 24}, 24)
		if bank != 1 {
			t.Fatalf("extension fill bank = %d, want 1", bank)
		}
	}
	_, bank := line.CacheFiveTupleWithLengthAndBank(&FiveTuple{DstIP: 17 << 8, IsLeafIndex: 24}, 24)
	if bank != 0 {
		t.Fatalf("global LRU replacement bank = %d, want oldest main slot", bank)
	}
}

func TestUnifiedCacheExtensionEpochRanksPressureAndBreaksTiesBySet(t *testing.T) {
	cache := newExtensionTestCache(t, 64, extensionTestConfig())
	cache.extensionPressure[1] = 10
	cache.extensionPressure[0] = 5
	cache.extensionPressure[2] = 5
	cache.finishSetExtensionEpoch()

	if len(cache.extensionBanksBySet[1]) != 1 || len(cache.extensionBanksBySet[0]) != 1 {
		t.Fatalf("allocated sets = set1:%v set0:%v, want one each", cache.extensionBanksBySet[1], cache.extensionBanksBySet[0])
	}
	if len(cache.extensionBanksBySet[2]) != 0 {
		t.Fatalf("tie loser set2 received extension: %v", cache.extensionBanksBySet[2])
	}
	if cache.ExtensionAllocationCount != 2 || cache.extensionPoolRemainingSets() != 0 {
		t.Fatalf("allocations/remaining = %d/%d, want 2/0", cache.ExtensionAllocationCount, cache.extensionPoolRemainingSets())
	}
	if cache.ExtensionPoolExhaustedEpochs != 1 {
		t.Fatalf("pool exhausted epochs = %d, want 1", cache.ExtensionPoolExhaustedEpochs)
	}
}

func TestUnifiedCacheExtensionThresholdAndOneAllocationPerEpoch(t *testing.T) {
	config := extensionTestConfig()
	config.SetExtensionPoolRatio = 0.5
	cache := newExtensionTestCache(t, 64, config)
	cache.extensionPressure[0] = 1
	cache.finishSetExtensionEpoch()
	if len(cache.extensionBanksBySet[0]) != 0 {
		t.Fatal("allocated below pressure threshold")
	}
	cache.extensionPressure[0] = 100
	cache.finishSetExtensionEpoch()
	if len(cache.extensionBanksBySet[0]) != 1 {
		t.Fatalf("first epoch extensions = %d, want 1", len(cache.extensionBanksBySet[0]))
	}
	cache.extensionPressure[0] = 100
	cache.finishSetExtensionEpoch()
	if len(cache.extensionBanksBySet[0]) != 2 {
		t.Fatalf("second epoch extensions = %d, want 2", len(cache.extensionBanksBySet[0]))
	}
	if got := cache.ExtensionAllocationByEpoch; !reflect.DeepEqual(got, []uint32{0, 1, 1}) {
		t.Fatalf("allocation timeline = %v, want [0 1 1]", got)
	}
}

func TestUnifiedCacheRecordsOnlyFullRepeatMissPressureAndExtensionProbe(t *testing.T) {
	config := extensionTestConfig()
	config.SetExtensionPressureThreshold = 1
	cache := newExtensionTestCache(t, 64, config)
	target := &FiveTuple{DstIP: 0x0a000001, IsLeafIndex: 24}
	setIdx := cache.setIdx(target)
	cache.Sets[setIdx].CacheFiveTupleWithLength(target, 24)
	inserted := 0
	for value := uint32(1); inserted < 8; value++ {
		candidate := &FiveTuple{DstIP: 0x80000000 | value<<8, IsLeafIndex: 24}
		if cache.setIdx(candidate) != setIdx {
			continue
		}
		cache.Sets[setIdx].CacheFiveTupleWithLength(candidate, 24)
		inserted++
	}
	if hit, _ := cache.IsCachedWithFiveTuple(target, true); hit {
		t.Fatal("target unexpectedly remained resident")
	}
	if cache.extensionPressure[setIdx] != 1 {
		t.Fatalf("repeat-miss pressure = %d, want 1", cache.extensionPressure[setIdx])
	}
	cache.finishSetExtensionEpoch()
	cache.Sets[setIdx].CacheFiveTupleWithLength(target, 24)
	before := cache.SetProbeCount
	if hit, _ := cache.IsCachedWithFiveTuple(target, true); !hit {
		t.Fatal("target missed after extension insertion")
	}
	if cache.SetProbeCount-before != 2 {
		t.Fatalf("physical probes = %d, want main+extension=2", cache.SetProbeCount-before)
	}
	if cache.MaxSetProbeCount != 2 {
		t.Fatalf("maximum physical probes = %d, want 2", cache.MaxSetProbeCount)
	}
}

func TestResolveUnifiedCacheSetExtensionSizes(t *testing.T) {
	main, extension, total, err := ResolveUnifiedCacheSetExtensionSizes(1024, 8, UnifiedCacheSetExtensionEpochRepeat, UnifiedCacheSetExtensionFixedTotal, 0.125)
	if err != nil || main != 896 || extension != 128 || total != 1024 {
		t.Fatalf("fixed-total sizes = %d/%d/%d err=%v", main, extension, total, err)
	}
	main, extension, total, err = ResolveUnifiedCacheSetExtensionSizes(1024, 8, UnifiedCacheSetExtensionEpochRepeat, UnifiedCacheSetExtensionAdditive, 0.125)
	if err != nil || main != 1024 || extension != 128 || total != 1152 {
		t.Fatalf("additive sizes = %d/%d/%d err=%v", main, extension, total, err)
	}
}

func TestUnifiedCacheFixedTotalAllowsNonPowerOfTwoHashSets(t *testing.T) {
	config := extensionTestConfig()
	config.SetExtensionCapacityMode = UnifiedCacheSetExtensionFixedTotal
	config.SetExtensionPoolRatio = 0.125
	cache := newExtensionTestCache(t, 64, config)
	if len(cache.Sets) != 7 || cache.MainSize != 56 {
		t.Fatalf("main sets/size = %d/%d, want 7/56", len(cache.Sets), cache.MainSize)
	}
}

func TestUnifiedCacheExtensionParameterBSONIdentifiesConfiguration(t *testing.T) {
	cache := newExtensionTestCache(t, 64, extensionTestConfig())
	bson := cache.Parameter().GetBson()
	if bson["setextensionpolicy"] != UnifiedCacheSetExtensionEpochRepeat || bson["mainsize"] != uint(64) || bson["extensionsize"] != uint(16) {
		t.Fatalf("unexpected extension BSON: %#v", bson)
	}
}
