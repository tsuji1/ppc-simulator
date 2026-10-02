package cache

import (
	"fmt"
	"hash/crc32"
	"math"
	"os"
	"path/filepath"
	"sort"
	"test-module/ipaddress"
	"test-module/routingtable"
)

const (
	CACHE_INDEX_TYPE_DIRECT   = iota // 0
	CACHE_INDEX_TYPE_HASH            // 1
	CACHE_INDEX_TYPE_IDEAL           // 2
	CACHE_INDEX_TYPE_PREFIX24        // 3
	CACHE_INDEX_TYPE_PREFIX20        // 4
	CACHE_INDEX_TYPE_PREFIX18        // 5
)

const CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE = 100

const (
	CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE = 20000
	CACHE_INDEX_TYPE_WINDOW_XOR_BASE    = 30000
	CACHE_INDEX_TYPE_WINDOW_CRC_BASE    = 40000
	cacheIndexTypeWindowStride          = 100
)

var skewCRC32Table = crc32.MakeTable(crc32.Castagnoli)

const cacheDebugFileOutputEnabled = false

const (
	UnifiedCacheInsertionPolicyExclusive = "exclusive"
	UnifiedCacheInsertionPolicyInclusive = "inclusive"
	UnifiedCacheIndexPolicyFixed         = "fixed"
	UnifiedCacheIndexPolicyLastInserted  = "last-inserted-prefix"
	UnifiedCacheIndexPolicyEpochFrequent = "epoch-most-frequent-prefix"
	UnifiedCacheSetExtensionOff          = "off"
	UnifiedCacheSetExtensionEpochRepeat  = "epoch-full-repeat-miss"
	UnifiedCacheSetExtensionFixedTotal   = "fixed-total"
	UnifiedCacheSetExtensionAdditive     = "additive"
)

type UnifiedCacheIndexConfig struct {
	Policy                        string
	Initial                       int
	Min                           int
	Max                           int
	EpochLength                   int
	LengthAwareMultiProbe         bool
	MultiProbeLengths             []int
	WayQuotaWideMax               int
	WayQuotaWideWays              int
	SkewedAssociative             bool
	SetExtensionPolicy            string
	SetExtensionCapacityMode      string
	SetExtensionPoolRatio         float64
	SetExtensionEpochLength       int
	SetExtensionPressureThreshold uint64
	SetExtensionMaxPerSet         int
}

func DefaultUnifiedCacheIndexConfig() UnifiedCacheIndexConfig {
	return UnifiedCacheIndexConfig{
		Policy:                        UnifiedCacheIndexPolicyFixed,
		Initial:                       18,
		Min:                           6,
		Max:                           24,
		EpochLength:                   1024,
		SetExtensionPolicy:            UnifiedCacheSetExtensionOff,
		SetExtensionCapacityMode:      UnifiedCacheSetExtensionAdditive,
		SetExtensionPoolRatio:         0.125,
		SetExtensionEpochLength:       4096,
		SetExtensionPressureThreshold: 8,
		SetExtensionMaxPerSet:         2,
	}
}

type UnifiedCache struct {
	Sets                          []UnifiedCacheLine // len(Sets) = Size / Way, each size == Way
	Way                           uint
	Size                          uint
	MainSize                      uint
	ExtensionSize                 uint
	TotalPhysicalSize             uint
	CacheIndexType                int
	IndexPolicy                   string
	AdaptiveInitial               int
	AdaptiveMin                   int
	AdaptiveMax                   int
	AdaptiveEpochLength           int
	ActiveIndexLen                int
	InsertionPolicy               string
	LengthAwareMultiProbe         bool
	MultiProbeLengths             []int
	WayQuotaWideMax               int
	WayQuotaWideWays              int
	SkewedAssociative             bool
	SetProbeCount                 uint64
	MaxSetProbeCount              uint64
	SetExtensionPolicy            string
	SetExtensionCapacityMode      string
	SetExtensionPoolRatio         float64
	SetExtensionEpochLength       int
	SetExtensionPressureThreshold uint64
	SetExtensionMaxPerSet         int
	ExtensionEpochAccessCount     uint64
	ExtensionCompletedEpochs      uint64
	ExtensionAllocationCount      uint64
	ExtensionAllocationByEpoch    []uint32
	ExtensionPoolExhaustedEpochs  uint64
	ExtensionSetProbeCount        uint64
	MainHitCount                  uint64
	ExtensionHitCount             uint64
	MainWriteCount                uint64
	ExtensionWriteCount           uint64
	extensionPressure             []uint64
	extensionBanksBySet           [][]int
	extensionBankCapacity         []int
	extensionBankAllocated        []int
	RoutingTable                  routingtable.RoutingTablePatriciaTrie
	DepthSum                      uint64
	LongestMatchMap               [33]int
	MatchMap                      [33]int
	DebugMode                     bool
	cacheTagLength                [][2]int
	directIndexSize               uint
	minCacheIndex                 uint8
	writeCount                    uint64
	writeCountMax                 uint64
	// Whole-cache first/second miss tracking is separate from per-set counters.
	WholeCacheFirstMissCount   [32]uint32
	WholeCacheSecondMissCount  [32]uint32
	wholeCacheSeenMissNetworks [32]map[uint32]struct{}
	// These counters estimate misses caused by the exclusive leaf-only insert gate.
	ExclusiveRejectedFirstMissCount   [32]uint32
	ExclusiveRejectedSecondMissCount  [32]uint32
	InclusiveNonLeafInsertedCount     [32]uint32
	exclusiveRejectedSeenMissNetworks [32]map[uint32]struct{}
	AdaptiveLookupCount               [32]uint64
	AdaptiveSelectionCount            [32]uint64
	AdaptiveSwitchCount               uint64
	AdaptiveEpochAccessCount          uint64
	AdaptiveEpochObservationCount     [32]uint64
	AdaptiveEpochDecisionCount        [32]uint64
	AdaptiveCompletedEpochs           uint64
}

func (c *UnifiedCache) StatString() string {
	str := "{}"
	return str
}

type UnifiedCacheStat struct {
	DepthSum                         uint64
	CachelineHitCount                [][32]uint32
	CachelineFirstMissCount          [][32]uint32
	CachelineSecondMissCount         [][32]uint32
	WholeCacheFirstMissCount         [32]uint32
	WholeCacheSecondMissCount        [32]uint32
	ExclusiveRejectedFirstMissCount  [32]uint32
	ExclusiveRejectedSecondMissCount [32]uint32
	InclusiveNonLeafInsertedCount    [32]uint32
	AdaptiveLookupCount              [32]uint64
	AdaptiveSelectionCount           [32]uint64
	AdaptiveSwitchCount              uint64
	AdaptiveFinalIndexLength         int
	AdaptiveEpochAccessCount         uint64
	AdaptiveEpochDecisionCount       [32]uint64
	AdaptiveCompletedEpochs          uint64
	SetProbeCount                    uint64
	MaxSetProbeCount                 uint64
	ExtensionEpochAccessCount        uint64
	ExtensionCompletedEpochs         uint64
	ExtensionAllocationCount         uint64
	ExtensionAllocationByEpoch       []uint32
	ExtensionPoolRemainingSets       uint64
	ExtensionPoolExhaustedEpochs     uint64
	ExtensionSetProbeCount           uint64
	MainHitCount                     uint64
	ExtensionHitCount                uint64
	MainWriteCount                   uint64
	ExtensionWriteCount              uint64
	ExtensionSetCountBySet           []uint32
}

func NormalizeUnifiedCacheInsertionPolicy(policy string) (string, error) {
	switch policy {
	case "", UnifiedCacheInsertionPolicyExclusive:
		return UnifiedCacheInsertionPolicyExclusive, nil
	case UnifiedCacheInsertionPolicyInclusive:
		return UnifiedCacheInsertionPolicyInclusive, nil
	default:
		return "", fmt.Errorf("unknown UnifiedCache insertion policy: %s", policy)
	}
}

func NormalizeUnifiedCacheIndexPolicy(policy string) (string, error) {
	switch policy {
	case "", UnifiedCacheIndexPolicyFixed:
		return UnifiedCacheIndexPolicyFixed, nil
	case UnifiedCacheIndexPolicyLastInserted, UnifiedCacheIndexPolicyEpochFrequent:
		return policy, nil
	default:
		return "", fmt.Errorf("unknown UnifiedCache index policy: %s", policy)
	}
}

func NormalizeUnifiedCacheSetExtensionPolicy(policy string) (string, error) {
	switch policy {
	case "", UnifiedCacheSetExtensionOff:
		return UnifiedCacheSetExtensionOff, nil
	case UnifiedCacheSetExtensionEpochRepeat:
		return policy, nil
	default:
		return "", fmt.Errorf("unknown UnifiedCache set extension policy: %s", policy)
	}
}

func NormalizeUnifiedCacheSetExtensionCapacityMode(mode string) (string, error) {
	switch mode {
	case "", UnifiedCacheSetExtensionAdditive:
		return UnifiedCacheSetExtensionAdditive, nil
	case UnifiedCacheSetExtensionFixedTotal:
		return mode, nil
	default:
		return "", fmt.Errorf("unknown UnifiedCache set extension capacity mode: %s", mode)
	}
}

func IsAdaptiveUnifiedCacheIndexPolicy(policy string) bool {
	return policy == UnifiedCacheIndexPolicyLastInserted || policy == UnifiedCacheIndexPolicyEpochFrequent
}

func unifiedPrefixIndex(prefixLen int8) (int, bool) {
	if prefixLen < 0 || prefixLen >= 32 {
		return 0, false
	}
	return int(prefixLen), true
}

func directPrefixIndexLength(cacheIndexType int) (int, bool) {
	prefixLen := cacheIndexType - CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE
	if prefixLen < 0 || prefixLen > 32 {
		return 0, false
	}
	return prefixLen, true
}

func decodeWindowCacheIndexType(cacheIndexType int) (base int, start int, width int, ok bool) {
	switch {
	case cacheIndexType >= CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE && cacheIndexType < CACHE_INDEX_TYPE_WINDOW_XOR_BASE:
		base = CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE
	case cacheIndexType >= CACHE_INDEX_TYPE_WINDOW_XOR_BASE && cacheIndexType < CACHE_INDEX_TYPE_WINDOW_CRC_BASE:
		base = CACHE_INDEX_TYPE_WINDOW_XOR_BASE
	case cacheIndexType >= CACHE_INDEX_TYPE_WINDOW_CRC_BASE && cacheIndexType < CACHE_INDEX_TYPE_WINDOW_CRC_BASE+32*cacheIndexTypeWindowStride:
		base = CACHE_INDEX_TYPE_WINDOW_CRC_BASE
	default:
		return 0, 0, 0, false
	}

	encoded := cacheIndexType - base
	start = encoded / cacheIndexTypeWindowStride
	width = encoded % cacheIndexTypeWindowStride
	if start < 0 || start > 31 || width < 1 || width > 32 || start+width > 32 {
		panic(fmt.Sprintf("invalid window CacheIndexType %d: start=%d width=%d", cacheIndexType, start, width))
	}
	return base, start, width, true
}

func dstIPWindow(dstIP uint32, start int, width int) uint32 {
	if width == 32 {
		return dstIP
	}
	shift := 32 - start - width
	mask := uint32((uint64(1) << width) - 1)
	return (dstIP >> shift) & mask
}

func xorFoldIndex(value uint32, valueBits int, indexBits uint) uint {
	if indexBits == 0 {
		return 0
	}

	chunkMask := uint32((uint64(1) << indexBits) - 1)
	var folded uint32
	for remaining := valueBits; remaining > 0; remaining -= int(indexBits) {
		chunkBits := int(indexBits)
		if remaining < chunkBits {
			chunkBits = remaining
		}
		shift := remaining - chunkBits
		chunk := (value >> shift) & uint32((uint64(1)<<chunkBits)-1)
		folded ^= chunk
	}
	return uint(folded & chunkMask)
}

func selectUnifiedCacheLength(f *FiveTuple, cacheTagLength [][2]int, allowNonLeaf bool) (int8, bool) {
	leafLen := int(f.IsLeafIndex)
	if leafLen < 0 || leafLen >= 32 {
		return 0, false
	}

	var selected int8
	found := false
	for _, tagLength := range cacheTagLength {
		start := tagLength[0]
		end := tagLength[1]
		switch {
		case leafLen < start:
			selected = int8(start)
			found = true
		case leafLen <= end:
			selected = int8(leafLen)
			found = true
		case allowNonLeaf:
			selected = int8(end)
			found = true
		}
	}
	if !found || selected < 0 || selected >= 32 {
		return 0, false
	}
	return selected, true
}

type UnifiedSecondMissIPRecord struct {
	SetIndex    int
	PrefixLen   int
	Network     uint32
	NetworkCIDR string
	Count       uint32
}

type UnifiedCacheLengthRecord struct {
	SetIndex   int
	Length     int
	EntryCount int
	ReferedSum int
}

func (cache *UnifiedCache) LengthSummaryRecords() []UnifiedCacheLengthRecord {
	byLength := make(map[int]UnifiedCacheLengthRecord)
	for setIdx := range cache.Sets {
		cacheLine := &cache.Sets[setIdx]
		for _, elem := range cacheLine.Entries {
			entry := elem.Value.(UnifiedCacheLineEntry)
			length := int(entry.Length)
			record := byLength[length]
			record.SetIndex = -1
			record.Length = length
			record.EntryCount++
			record.ReferedSum += entry.Refered
			byLength[length] = record
		}
	}

	records := make([]UnifiedCacheLengthRecord, 0, len(byLength))
	for _, record := range byLength {
		records = append(records, record)
	}
	sort.Slice(records, func(i, j int) bool {
		return records[i].Length < records[j].Length
	})
	return records
}

func (cache *UnifiedCache) LengthBySetRecords() []UnifiedCacheLengthRecord {
	records := make([]UnifiedCacheLengthRecord, 0)
	for setIdx := range cache.Sets {
		cacheLine := &cache.Sets[setIdx]
		byLength := make(map[int]UnifiedCacheLengthRecord)
		for _, elem := range cacheLine.Entries {
			entry := elem.Value.(UnifiedCacheLineEntry)
			length := int(entry.Length)
			record := byLength[length]
			record.SetIndex = setIdx
			record.Length = length
			record.EntryCount++
			record.ReferedSum += entry.Refered
			byLength[length] = record
		}
		for _, record := range byLength {
			records = append(records, record)
		}
	}
	sort.Slice(records, func(i, j int) bool {
		if records[i].SetIndex != records[j].SetIndex {
			return records[i].SetIndex < records[j].SetIndex
		}
		return records[i].Length < records[j].Length
	})
	return records
}

func (cache *UnifiedCache) TopSecondMissIPRecords(limit int) []UnifiedSecondMissIPRecord {
	records := make([]UnifiedSecondMissIPRecord, 0)
	for setIdx := range cache.Sets {
		cacheLine := &cache.Sets[setIdx]
		for prefixLen, countsByNetwork := range cacheLine.SecondMissIPCount {
			for network, count := range countsByNetwork {
				if count == 0 {
					continue
				}
				records = append(records, UnifiedSecondMissIPRecord{
					SetIndex:    setIdx,
					PrefixLen:   prefixLen,
					Network:     network,
					NetworkCIDR: ipaddress.NewIPaddress(network).DstNetworkString(prefixLen),
					Count:       count,
				})
			}
		}
	}

	sort.Slice(records, func(i, j int) bool {
		if records[i].Count != records[j].Count {
			return records[i].Count > records[j].Count
		}
		if records[i].PrefixLen != records[j].PrefixLen {
			return records[i].PrefixLen < records[j].PrefixLen
		}
		if records[i].Network != records[j].Network {
			return records[i].Network < records[j].Network
		}
		return records[i].SetIndex < records[j].SetIndex
	})

	if limit > 0 && len(records) > limit {
		return records[:limit]
	}
	return records
}

func (cache *UnifiedCache) Stat() interface{} {
	UnifiedCacheStat := UnifiedCacheStat{
		DepthSum:                         cache.DepthSum,
		WholeCacheFirstMissCount:         cache.WholeCacheFirstMissCount,
		WholeCacheSecondMissCount:        cache.WholeCacheSecondMissCount,
		ExclusiveRejectedFirstMissCount:  cache.ExclusiveRejectedFirstMissCount,
		ExclusiveRejectedSecondMissCount: cache.ExclusiveRejectedSecondMissCount,
		InclusiveNonLeafInsertedCount:    cache.InclusiveNonLeafInsertedCount,
		AdaptiveLookupCount:              cache.AdaptiveLookupCount,
		AdaptiveSelectionCount:           cache.AdaptiveSelectionCount,
		AdaptiveSwitchCount:              cache.AdaptiveSwitchCount,
		AdaptiveFinalIndexLength:         cache.ActiveIndexLen,
		AdaptiveEpochAccessCount:         cache.AdaptiveEpochAccessCount,
		AdaptiveEpochDecisionCount:       cache.AdaptiveEpochDecisionCount,
		AdaptiveCompletedEpochs:          cache.AdaptiveCompletedEpochs,
		SetProbeCount:                    cache.SetProbeCount,
		MaxSetProbeCount:                 cache.MaxSetProbeCount,
		ExtensionEpochAccessCount:        cache.ExtensionEpochAccessCount,
		ExtensionCompletedEpochs:         cache.ExtensionCompletedEpochs,
		ExtensionAllocationCount:         cache.ExtensionAllocationCount,
		ExtensionAllocationByEpoch:       append([]uint32(nil), cache.ExtensionAllocationByEpoch...),
		ExtensionPoolRemainingSets:       uint64(cache.extensionPoolRemainingSets()),
		ExtensionPoolExhaustedEpochs:     cache.ExtensionPoolExhaustedEpochs,
		ExtensionSetProbeCount:           cache.ExtensionSetProbeCount,
		MainHitCount:                     cache.MainHitCount,
		ExtensionHitCount:                cache.ExtensionHitCount,
		MainWriteCount:                   cache.MainWriteCount,
		ExtensionWriteCount:              cache.ExtensionWriteCount,
	}
	debugDirPath := "debug"
	for i := 0; i < len(cache.Sets); i++ {
		UnifiedCacheStat.ExtensionSetCountBySet = append(UnifiedCacheStat.ExtensionSetCountBySet, uint32(len(cache.extensionBanksBySet[i])))
		cacheLineStat := cache.Sets[i].Stat()
		UnifiedCacheStat.CachelineHitCount = append(UnifiedCacheStat.CachelineHitCount, cacheLineStat.(UnifiedCacheLineStat).HitCount)

		UnifiedCacheStat.CachelineFirstMissCount = append(UnifiedCacheStat.CachelineFirstMissCount, cacheLineStat.(UnifiedCacheLineStat).FirstMissCount)
		UnifiedCacheStat.CachelineSecondMissCount = append(UnifiedCacheStat.CachelineSecondMissCount, cacheLineStat.(UnifiedCacheLineStat).SecondMissCount)
		secondMisscount := cacheLineStat.(UnifiedCacheLineStat).SecondMissCount

		max_secondMisscount := uint32(0)
		max_index := 0
		for i, v := range secondMisscount {
			if v > max_secondMisscount {
				max_secondMisscount = v
				max_index = i
			}
		}

		if cacheDebugFileOutputEnabled && cache.Size > 4096 && max_secondMisscount < 200 && max_secondMisscount > 100 && cache.writeCount == 0 {
			uniqueDstIPHitCount := cacheLineStat.(UnifiedCacheLineStat).UniqueDstIPHitCount
			fmt.Printf("Max second miss count exceeded: %d (index: %d)\n", max_secondMisscount, max_index)

			cache.writeCount++
			save := uniqueDstIPHitCount[max_index]
			if err := os.MkdirAll(debugDirPath, 0o755); err != nil {
				fmt.Printf("Error creating debug directory: %v\n", err)
				continue
			}
			// fileに保存
			filePath := filepath.Join(debugDirPath, fmt.Sprintf("cache_debug_size%d_%d_%d_100-200.txt", cache.Size, i, max_index))
			file, err := os.Create(filePath)
			if err != nil {
				fmt.Printf("Error creating file: %v\n", err)
			} else {
				defer file.Close()
				// IPアドレスでソートするためにキーをスライスに変換
				ips := make([]uint32, 0, len(save))
				for ip := range save {
					ips = append(ips, ip)
				}

				// IPアドレスでソート
				sort.Slice(ips, func(i, j int) bool {
					return ips[i] < ips[j]
				})

				// ソートされた順序で書き込み
				for _, ip := range ips {
					fmt.Fprintf(file, "IP: %s, Count: %d\n", ipaddress.NewIPaddress(ip).DstNetworkString(max_index), save[ip])
				}
			}

		}
		if cacheDebugFileOutputEnabled && cache.Size > 4096 && max_secondMisscount > 3000 {
			uniqueDstIPHitCount := cacheLineStat.(UnifiedCacheLineStat).UniqueDstIPHitCount
			fmt.Printf("Max second miss count exceeded: %d (index: %d)\n", max_secondMisscount, max_index)

			save := uniqueDstIPHitCount[max_index]
			if err := os.MkdirAll(debugDirPath, 0o755); err != nil {
				fmt.Printf("Error creating debug directory: %v\n", err)
				continue
			}
			// fileに保存
			filePath := filepath.Join(debugDirPath, fmt.Sprintf("cache_debug_size%d_%d_%d_%d_3000.txt", cache.Size, i, max_index, cache.writeCountMax))
			file, err := os.Create(filePath)
			cache.writeCountMax++
			if err != nil {
				fmt.Printf("Error creating file: %v\n", err)
			} else {
				defer file.Close()
				// IPアドレスでソートするためにキーをスライスに変換
				ips := make([]uint32, 0, len(save))
				for ip := range save {
					ips = append(ips, ip)
				}

				// IPアドレスでソート
				sort.Slice(ips, func(i, j int) bool {
					return ips[i] < ips[j]
				})

				// ソートされた順序で書き込み
				for _, ip := range ips {
					fmt.Fprintf(file, "IP: %s, Count: %d\n", ipaddress.NewIPaddress(ip).DstNetworkString(max_index), save[ip])
				}
			}

		}
	}
	return UnifiedCacheStat
}

func (cache *UnifiedCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *UnifiedCache) setIdx(f *FiveTuple) uint {
	idxType := cache.CacheIndexType
	if IsAdaptiveUnifiedCacheIndexPolicy(cache.IndexPolicy) {
		idxType = cache.ActiveIndexLen
	}
	return cache.setIdxForType(f, idxType, false)
}

func (cache *UnifiedCache) hashSetIdx(value uint32, skew bool) uint {
	maxSetIdx := cache.MainSize / cache.Way
	if skew {
		return uint(crc32.Checksum(uint32ToBytes(value), skewCRC32Table)) % maxSetIdx
	}
	return uint(crc32.ChecksumIEEE(uint32ToBytes(value))) % maxSetIdx
}

func (cache *UnifiedCache) setIdxForType(f *FiveTuple, idxType int, skew bool) uint {
	maxSetIdx := cache.MainSize / cache.Way
	if base, start, width, ok := decodeWindowCacheIndexType(idxType); ok {
		window := dstIPWindow(f.DstIP, start, width)
		if skew {
			return cache.hashSetIdx(window, true)
		}
		switch base {
		case CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE:
			return uint(window) & (maxSetIdx - 1)
		case CACHE_INDEX_TYPE_WINDOW_XOR_BASE:
			return xorFoldIndex(window, width, cache.directIndexSize)
		case CACHE_INDEX_TYPE_WINDOW_CRC_BASE:
			crc := crc32.ChecksumIEEE(uint32ToBytes(window))
			return uint(crc) % maxSetIdx
		}
	}

	if directPrefixLen, ok := directPrefixIndexLength(idxType); ok {
		if directPrefixLen == 0 {
			return 0
		}
		dstPrefix := f.DstIP >> (32 - directPrefixLen)
		if skew {
			return cache.hashSetIdx(dstPrefix, true)
		}
		return uint(dstPrefix) & (maxSetIdx - 1)
	}

	// PREFIX8 - PREFIX24 でindex化を行う
	// 9- 24
	if idxType > CACHE_INDEX_TYPE_PREFIX18 && idxType < 25 {
		dstIP := f.DstIP >> (32 - idxType)
		return cache.hashSetIdx(dstIP, skew)
	}

	switch idxType {
	case CACHE_INDEX_TYPE_DIRECT:
		// 宛先ipの上位size を使う
		idx := f.DstIP >> (32 - cache.directIndexSize)
		if skew {
			return cache.hashSetIdx(idx, true)
		}
		return uint(idx)
	case CACHE_INDEX_TYPE_HASH:
		// ハッシュ値を使う
		dstIP := f.DstIP >> (16) //使う
		return cache.hashSetIdx(dstIP, skew)
	case CACHE_INDEX_TYPE_IDEAL:
		dstIP := f.DstIP >> (16) //使う

		if f.IsLeafIndex > 16 && f.IsLeafIndex < 25 {
			dstIP = f.DstIP >> (32 - f.IsLeafIndex)
		}
		if f.IsLeafIndex > 24 {
			dstIP = f.DstIP >> 8
		}

		return cache.hashSetIdx(dstIP, skew)
	case CACHE_INDEX_TYPE_PREFIX24:
		dstIP := f.DstIP >> (8) //使う
		return cache.hashSetIdx(dstIP, skew)
	case CACHE_INDEX_TYPE_PREFIX20:
		dstIP := f.DstIP >> (12) //使う
		return cache.hashSetIdx(dstIP, skew)
	case CACHE_INDEX_TYPE_PREFIX18:
		dstIP := f.DstIP >> (14) //使う
		return cache.hashSetIdx(dstIP, skew)
	default:
		panic(fmt.Sprintf("Unknown CacheIndexType: %d", idxType))
	}
}

func appendUniqueSet(indices []uint, index uint) []uint {
	for _, existing := range indices {
		if existing == index {
			return indices
		}
	}
	return append(indices, index)
}

func (cache *UnifiedCache) lookupSetIndices(f *FiveTuple) []uint {
	indexTypes := []int{cache.CacheIndexType}
	if IsAdaptiveUnifiedCacheIndexPolicy(cache.IndexPolicy) {
		indexTypes[0] = cache.ActiveIndexLen
	}
	if cache.LengthAwareMultiProbe {
		indexTypes = cache.MultiProbeLengths
	}

	indices := make([]uint, 0, len(indexTypes)*2)
	for _, idxType := range indexTypes {
		indices = appendUniqueSet(indices, cache.setIdxForType(f, idxType, false))
		if cache.SkewedAssociative {
			indices = appendUniqueSet(indices, cache.setIdxForType(f, idxType, true))
		}
	}
	return indices
}

func (cache *UnifiedCache) setExtensionEnabled() bool {
	return cache.SetExtensionPolicy == UnifiedCacheSetExtensionEpochRepeat
}

func (cache *UnifiedCache) extensionPoolRemainingSets() int {
	remaining := 0
	for i := range cache.extensionBankCapacity {
		remaining += cache.extensionBankCapacity[i] - cache.extensionBankAllocated[i]
	}
	return remaining
}

func (cache *UnifiedCache) allocateExtensionSet(setIdx int) bool {
	if setIdx < 0 || setIdx >= len(cache.Sets) || len(cache.extensionBanksBySet[setIdx]) >= cache.SetExtensionMaxPerSet {
		return false
	}
	used := make(map[int]struct{}, len(cache.extensionBanksBySet[setIdx]))
	for _, bank := range cache.extensionBanksBySet[setIdx] {
		used[bank] = struct{}{}
	}
	for bankIndex := range cache.extensionBankCapacity {
		bank := bankIndex + 1
		if _, exists := used[bank]; exists || cache.extensionBankAllocated[bankIndex] >= cache.extensionBankCapacity[bankIndex] {
			continue
		}
		cache.Sets[setIdx].GrowExtensionSet(bank)
		cache.extensionBanksBySet[setIdx] = append(cache.extensionBanksBySet[setIdx], bank)
		cache.extensionBankAllocated[bankIndex]++
		cache.ExtensionAllocationCount++
		return true
	}
	return false
}

func (cache *UnifiedCache) finishSetExtensionEpoch() {
	type candidate struct {
		set      int
		pressure uint64
	}
	candidates := make([]candidate, 0)
	for setIdx, pressure := range cache.extensionPressure {
		if pressure >= cache.SetExtensionPressureThreshold && len(cache.extensionBanksBySet[setIdx]) < cache.SetExtensionMaxPerSet {
			candidates = append(candidates, candidate{set: setIdx, pressure: pressure})
		}
	}
	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].pressure != candidates[j].pressure {
			return candidates[i].pressure > candidates[j].pressure
		}
		return candidates[i].set < candidates[j].set
	})
	exhausted := false
	allocationsBefore := cache.ExtensionAllocationCount
	for _, candidate := range candidates {
		if !cache.allocateExtensionSet(candidate.set) && cache.extensionPoolRemainingSets() == 0 {
			exhausted = true
			break
		}
	}
	if exhausted {
		cache.ExtensionPoolExhaustedEpochs++
	}
	cache.ExtensionAllocationByEpoch = append(cache.ExtensionAllocationByEpoch, uint32(cache.ExtensionAllocationCount-allocationsBefore))
	for i := range cache.extensionPressure {
		cache.extensionPressure[i] = 0
	}
	cache.ExtensionEpochAccessCount = 0
	cache.ExtensionCompletedEpochs++
}

func (cache *UnifiedCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	if update && cache.setExtensionEnabled() {
		if cache.ExtensionEpochAccessCount >= uint64(cache.SetExtensionEpochLength) {
			cache.finishSetExtensionEpoch()
		}
		cache.ExtensionEpochAccessCount++
	}
	if update && cache.IndexPolicy == UnifiedCacheIndexPolicyEpochFrequent {
		if cache.AdaptiveEpochAccessCount >= uint64(cache.AdaptiveEpochLength) {
			cache.finishAdaptiveEpoch()
		}
		cache.AdaptiveEpochAccessCount++
	}
	if update && IsAdaptiveUnifiedCacheIndexPolicy(cache.IndexPolicy) {
		cache.AdaptiveLookupCount[cache.ActiveIndexLen]++
	}
	setIndices := cache.lookupSetIndices(f)
	if update {
		var lookupProbes uint64
		for _, setIdx := range setIndices {
			extensionProbes := uint64(len(cache.extensionBanksBySet[setIdx]))
			cache.SetProbeCount += 1 + extensionProbes
			cache.ExtensionSetProbeCount += extensionProbes
			lookupProbes += 1 + extensionProbes
		}
		if lookupProbes > cache.MaxSetProbeCount {
			cache.MaxSetProbeCount = lookupProbes
		}
	}
	hitSet := -1
	var hitLength uint8
	hitBank := 0
	for _, setIdx := range setIndices {
		length, bank, hit := cache.Sets[setIdx].LongestMatchLocation(f)
		if hit && (hitSet < 0 || length > hitLength) {
			hitSet = int(setIdx)
			hitLength = length
			hitBank = bank
		}
	}
	if hitSet >= 0 {
		if update {
			if hitBank == 0 {
				cache.MainHitCount++
			} else {
				cache.ExtensionHitCount++
			}
		}
		return cache.Sets[hitSet].IsCachedWithFiveTuple(f, update)
	}
	if !update {
		return false, nil
	}

	// Per-set miss accounting remains attached to the primary candidate only.
	primarySet := setIndices[0]
	if cache.setExtensionEnabled() && cache.Sets[primarySet].IsFull() && cache.Sets[primarySet].HasSeenMissNetwork(f) {
		cache.extensionPressure[primarySet]++
	}
	cache.Sets[primarySet].IsCachedWithFiveTuple(f, true)
	if update {
		cache.recordWholeCacheMiss(f)
	}
	return false, nil
}

func (cache *UnifiedCache) clampAdaptiveIndex(prefixLen int) int {
	if prefixLen < cache.AdaptiveMin {
		return cache.AdaptiveMin
	}
	if prefixLen > cache.AdaptiveMax {
		return cache.AdaptiveMax
	}
	return prefixLen
}

func (cache *UnifiedCache) updateAdaptiveIndex(prefixLen int) int {
	prefixLen = cache.clampAdaptiveIndex(prefixLen)
	cache.AdaptiveSelectionCount[prefixLen]++
	if cache.ActiveIndexLen != prefixLen {
		cache.AdaptiveSwitchCount++
		cache.ActiveIndexLen = prefixLen
	}
	return prefixLen
}

func (cache *UnifiedCache) recordAdaptiveEpochObservation(prefixLen int) {
	prefixLen = cache.clampAdaptiveIndex(prefixLen)
	cache.AdaptiveSelectionCount[prefixLen]++
	cache.AdaptiveEpochObservationCount[prefixLen]++
}

func (cache *UnifiedCache) selectAdaptiveEpochIndex() (int, bool) {
	var maxCount uint64
	for length := cache.AdaptiveMin; length <= cache.AdaptiveMax; length++ {
		if cache.AdaptiveEpochObservationCount[length] > maxCount {
			maxCount = cache.AdaptiveEpochObservationCount[length]
		}
	}
	if maxCount == 0 {
		return cache.ActiveIndexLen, false
	}
	if cache.AdaptiveEpochObservationCount[cache.ActiveIndexLen] == maxCount {
		return cache.ActiveIndexLen, true
	}
	best := -1
	bestDistance := 33
	for length := cache.AdaptiveMin; length <= cache.AdaptiveMax; length++ {
		if cache.AdaptiveEpochObservationCount[length] != maxCount {
			continue
		}
		distance := length - cache.ActiveIndexLen
		if distance < 0 {
			distance = -distance
		}
		if distance < bestDistance || (distance == bestDistance && (best < 0 || length < best)) {
			best = length
			bestDistance = distance
		}
	}
	return best, true
}

func (cache *UnifiedCache) finishAdaptiveEpoch() {
	selected, observed := cache.selectAdaptiveEpochIndex()
	if observed {
		cache.AdaptiveEpochDecisionCount[selected]++
		if cache.ActiveIndexLen != selected {
			cache.AdaptiveSwitchCount++
			cache.ActiveIndexLen = selected
		}
	}
	cache.AdaptiveCompletedEpochs++
	cache.AdaptiveEpochAccessCount = 0
	cache.AdaptiveEpochObservationCount = [32]uint64{}
}

func (cache *UnifiedCache) wholeCacheMissNetwork(f *FiveTuple) (int8, uint32, bool) {
	cacheLength := f.IsLeafIndex
	if cacheLength < int8(cache.minCacheIndex) {
		cacheLength = int8(cache.minCacheIndex)
	}
	if f.IsLeafIndex < 0 || f.IsLeafIndex >= 32 || cacheLength < 0 || cacheLength >= 32 {
		return 0, 0, false
	}
	dstNetwork := f.DstIP >> (32 - uint8(cacheLength))
	return cacheLength, dstNetwork, true
}

func (cache *UnifiedCache) recordWholeCacheMiss(f *FiveTuple) {
	cacheLength, dstNetwork, ok := cache.wholeCacheMissNetwork(f)
	if !ok {
		return
	}
	if cache.wholeCacheSeenMissNetworks[cacheLength] == nil {
		cache.wholeCacheSeenMissNetworks[cacheLength] = make(map[uint32]struct{})
	}
	if _, found := cache.wholeCacheSeenMissNetworks[cacheLength][dstNetwork]; found {
		cache.WholeCacheSecondMissCount[f.IsLeafIndex]++
		return
	}
	cache.wholeCacheSeenMissNetworks[cacheLength][dstNetwork] = struct{}{}
	cache.WholeCacheFirstMissCount[f.IsLeafIndex]++
}

func (cache *UnifiedCache) canInsertExclusive(f *FiveTuple) bool {
	for _, tagLength := range cache.cacheTagLength {
		if isLeaf(f, &cache.RoutingTable, tagLength[0]) || isLeaf(f, &cache.RoutingTable, tagLength[1]) {
			return true
		}
	}
	return false
}

func (cache *UnifiedCache) recordExclusiveRejectedMiss(f *FiveTuple) {
	prefixIdx, ok := unifiedPrefixIndex(f.IsLeafIndex)
	if !ok {
		return
	}
	cacheLength, ok := selectUnifiedCacheLength(f, cache.cacheTagLength, true)
	if !ok {
		return
	}
	dstNetwork := f.DstIP >> (32 - uint8(cacheLength))
	if cache.exclusiveRejectedSeenMissNetworks[cacheLength] == nil {
		cache.exclusiveRejectedSeenMissNetworks[cacheLength] = make(map[uint32]struct{})
	}
	if _, found := cache.exclusiveRejectedSeenMissNetworks[cacheLength][dstNetwork]; found {
		cache.ExclusiveRejectedSecondMissCount[prefixIdx]++
		return
	}
	cache.exclusiveRejectedSeenMissNetworks[cacheLength][dstNetwork] = struct{}{}
	cache.ExclusiveRejectedFirstMissCount[prefixIdx]++
}

func (cache *UnifiedCache) recordInclusiveNonLeafInsert(f *FiveTuple) {
	prefixIdx, ok := unifiedPrefixIndex(f.IsLeafIndex)
	if !ok {
		return
	}
	cache.InclusiveNonLeafInsertedCount[prefixIdx]++
}

func (cache *UnifiedCache) canCacheExactLength(prefixLen int) bool {
	if prefixLen < 0 || prefixLen >= 32 {
		return false
	}
	for _, tagLength := range cache.cacheTagLength {
		if tagLength[0] <= prefixLen && prefixLen <= tagLength[1] {
			return true
		}
	}
	return false
}

func (cache *UnifiedCache) placementIndexType(cacheLength int) int {
	if cache.LengthAwareMultiProbe {
		for _, probeLength := range cache.MultiProbeLengths {
			if cacheLength <= probeLength {
				return probeLength
			}
		}
		return cache.MultiProbeLengths[len(cache.MultiProbeLengths)-1]
	}
	if IsAdaptiveUnifiedCacheIndexPolicy(cache.IndexPolicy) {
		return cache.ActiveIndexLen
	}
	return cache.CacheIndexType
}

func (cache *UnifiedCache) placementSetIndex(f *FiveTuple, cacheLength int) uint {
	idxType := cache.placementIndexType(cacheLength)
	primary := cache.setIdxForType(f, idxType, false)
	if !cache.SkewedAssociative {
		return primary
	}
	secondary := cache.setIdxForType(f, idxType, true)
	if cache.Sets[secondary].ResidentCount() < cache.Sets[primary].ResidentCount() {
		return secondary
	}
	return primary
}

func (cache *UnifiedCache) cacheAtSetWithLength(setIdx uint, f *FiveTuple, cacheLength uint8) []*FiveTuple {
	evicted, bank := cache.Sets[setIdx].CacheFiveTupleWithLengthAndBank(f, cacheLength)
	if bank == 0 {
		cache.MainWriteCount++
	} else {
		cache.ExtensionWriteCount++
	}
	return evicted
}

func (cache *UnifiedCache) cacheInclusiveFiveTuple(f *FiveTuple) []*FiveTuple {
	prefixes, _ := cache.RoutingTable.SearchIP(ipaddress.NewIPaddress(f.DstIP), 32)
	evictedFiveTuples := []*FiveTuple{}
	for _, prefix := range prefixes {
		prefixLen := len(prefix)
		if !cache.canCacheExactLength(prefixLen) {
			continue
		}
		setIdx := cache.placementSetIndex(f, prefixLen)
		evictedFiveTuples = append(evictedFiveTuples, cache.cacheAtSetWithLength(setIdx, f, uint8(prefixLen))...)
	}
	return evictedFiveTuples
}

func (cache *UnifiedCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	// 統計情報を更新
	cache.DepthSum += uint64(cache.RoutingTable.GetDepth(f.DstIP))

	canInsertExclusive := cache.canInsertExclusive(f)
	if !canInsertExclusive {
		cache.recordExclusiveRejectedMiss(f)
		if cache.InsertionPolicy == UnifiedCacheInsertionPolicyExclusive {
			return []*FiveTuple{}
		}
		cache.recordInclusiveNonLeafInsert(f)
	}

	if cache.InsertionPolicy == UnifiedCacheInsertionPolicyInclusive {
		return cache.cacheInclusiveFiveTuple(f)
	}

	if cache.IndexPolicy == UnifiedCacheIndexPolicyLastInserted {
		cacheLength, canCache := selectUnifiedCacheLength(f, cache.cacheTagLength, false)
		if !canCache {
			return []*FiveTuple{}
		}
		cache.updateAdaptiveIndex(int(cacheLength))
		setIdx := cache.placementSetIndex(f, int(cacheLength))
		return cache.cacheAtSetWithLength(setIdx, f, uint8(cacheLength))
	}
	if cache.IndexPolicy == UnifiedCacheIndexPolicyEpochFrequent {
		cacheLength, canCache := selectUnifiedCacheLength(f, cache.cacheTagLength, false)
		if !canCache {
			return []*FiveTuple{}
		}
		cache.recordAdaptiveEpochObservation(int(cacheLength))
		setIdx := cache.placementSetIndex(f, int(cacheLength))
		return cache.cacheAtSetWithLength(setIdx, f, uint8(cacheLength))
	}

	cacheLength, canCache := selectUnifiedCacheLength(f, cache.cacheTagLength, false)
	if !canCache {
		return []*FiveTuple{}
	}
	setIdx := cache.placementSetIndex(f, int(cacheLength))
	return cache.cacheAtSetWithLength(setIdx, f, uint8(cacheLength))
}

func (cache *UnifiedCache) InvalidateFiveTuple(f *FiveTuple) {
	for _, setIdx := range cache.lookupSetIndices(f) {
		cache.Sets[setIdx].InvalidateFiveTuple(f)
	}
}

func (cache *UnifiedCache) Clear() {
	panic("Not implemented")
}

func (cache *UnifiedCache) Description() string {
	return "UnifiedCache"
}

func (cache *UnifiedCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Way\": %d, \"Size\": %d, \"DepthSum\": %d}", cache.Description(), cache.Way, cache.Size, cache.DepthSum)
}

func (cache *UnifiedCache) Parameter() Parameter {
	return &UnifiedCacheParameter{
		Type:                          cache.Description(),
		Way:                           cache.Way,
		Size:                          cache.Size,
		CacheIndexType:                cache.CacheIndexType,
		IndexPolicy:                   cache.IndexPolicy,
		AdaptiveInitial:               cache.AdaptiveInitial,
		AdaptiveMin:                   cache.AdaptiveMin,
		AdaptiveMax:                   cache.AdaptiveMax,
		AdaptiveEpochLength:           cache.AdaptiveEpochLength,
		CacheTagLength:                cache.cacheTagLength,
		InsertionPolicy:               cache.InsertionPolicy,
		LengthAwareMultiProbe:         cache.LengthAwareMultiProbe,
		MultiProbeLengths:             cache.MultiProbeLengths,
		WayQuotaWideMax:               cache.WayQuotaWideMax,
		WayQuotaWideWays:              cache.WayQuotaWideWays,
		SkewedAssociative:             cache.SkewedAssociative,
		SetExtensionPolicy:            cache.SetExtensionPolicy,
		SetExtensionCapacityMode:      cache.SetExtensionCapacityMode,
		SetExtensionPoolRatio:         cache.SetExtensionPoolRatio,
		SetExtensionEpochLength:       cache.SetExtensionEpochLength,
		SetExtensionPressureThreshold: cache.SetExtensionPressureThreshold,
		SetExtensionMaxPerSet:         cache.SetExtensionMaxPerSet,
		MainSize:                      cache.MainSize,
		ExtensionSize:                 cache.ExtensionSize,
		TotalPhysicalSize:             cache.TotalPhysicalSize,
	}
}

// cacheTagLengthは、wayごとにキャッシュタグの長さを指定するスライスです。[16,17]だと、16,17ビットを許容する。
func NewUnifiedCache(size uint, way uint, routingTable *routingtable.RoutingTablePatriciaTrie, cacheIndexType int, cacheTagLength [][2]int, insertionPolicy string, debugMode bool) *UnifiedCache {
	return NewUnifiedCacheWithIndexConfig(size, way, routingTable, cacheIndexType, cacheTagLength, insertionPolicy, DefaultUnifiedCacheIndexConfig(), debugMode)
}

func ResolveUnifiedCacheSetExtensionSizes(size, way uint, policy, capacityMode string, poolRatio float64) (mainSize, extensionSize, totalPhysicalSize uint, err error) {
	if way == 0 || size == 0 || size%way != 0 {
		return 0, 0, 0, fmt.Errorf("size must be positive and divisible by way")
	}
	if policy == "" || policy == UnifiedCacheSetExtensionOff {
		return size, 0, size, nil
	}
	if poolRatio <= 0 || poolRatio >= 1 {
		return 0, 0, 0, fmt.Errorf("set extension pool ratio must satisfy 0 < ratio < 1, got %g", poolRatio)
	}
	poolSets := uint(float64(size/way) * poolRatio)
	if poolSets == 0 {
		return 0, 0, 0, fmt.Errorf("set extension pool ratio %g yields zero extension sets", poolRatio)
	}
	extensionSize = poolSets * way
	switch capacityMode {
	case UnifiedCacheSetExtensionFixedTotal:
		if extensionSize >= size {
			return 0, 0, 0, fmt.Errorf("extension size must be smaller than total size")
		}
		mainSize = size - extensionSize
		totalPhysicalSize = size
	case UnifiedCacheSetExtensionAdditive:
		mainSize = size
		totalPhysicalSize = size + extensionSize
	default:
		return 0, 0, 0, fmt.Errorf("unknown set extension capacity mode: %s", capacityMode)
	}
	return mainSize, extensionSize, totalPhysicalSize, nil
}

func unifiedIndexRequiresPowerOfTwoSets(cacheIndexType int) bool {
	if cacheIndexType == CACHE_INDEX_TYPE_DIRECT {
		return true
	}
	if _, ok := directPrefixIndexLength(cacheIndexType); ok {
		return true
	}
	if base, _, _, ok := decodeWindowCacheIndexType(cacheIndexType); ok {
		return base == CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE || base == CACHE_INDEX_TYPE_WINDOW_XOR_BASE
	}
	return false
}

func NewUnifiedCacheWithIndexConfig(size uint, way uint, routingTable *routingtable.RoutingTablePatriciaTrie, cacheIndexType int, cacheTagLength [][2]int, insertionPolicy string, indexConfig UnifiedCacheIndexConfig, debugMode bool) *UnifiedCache {
	if way == 0 {
		panic("way must be greater than 0")
	}
	if size%way != 0 {
		panic("Size must be multiplier of way")
	}
	if len(cacheTagLength) != 1 && len(cacheTagLength) != int(way) {
		panic(fmt.Sprintf("cacheTagLength must have 1 or %d items, but got %d", way, len(cacheTagLength)))
	}
	normalizedInsertionPolicy, err := NormalizeUnifiedCacheInsertionPolicy(insertionPolicy)
	if err != nil {
		panic(err)
	}
	normalizedIndexPolicy, err := NormalizeUnifiedCacheIndexPolicy(indexConfig.Policy)
	if err != nil {
		panic(err)
	}
	normalizedExtensionPolicy, err := NormalizeUnifiedCacheSetExtensionPolicy(indexConfig.SetExtensionPolicy)
	if err != nil {
		panic(err)
	}
	normalizedExtensionCapacityMode, err := NormalizeUnifiedCacheSetExtensionCapacityMode(indexConfig.SetExtensionCapacityMode)
	if err != nil {
		panic(err)
	}
	mainSize, extensionSize, totalPhysicalSize, err := ResolveUnifiedCacheSetExtensionSizes(
		size, way, normalizedExtensionPolicy, normalizedExtensionCapacityMode, indexConfig.SetExtensionPoolRatio,
	)
	if err != nil {
		panic(err)
	}
	if indexConfig.Min < 0 || indexConfig.Max >= 32 || indexConfig.Min > indexConfig.Max {
		panic(fmt.Sprintf("adaptive index range must satisfy 0 <= min <= max < 32, got %d..%d", indexConfig.Min, indexConfig.Max))
	}
	if indexConfig.Initial < indexConfig.Min || indexConfig.Initial > indexConfig.Max {
		panic(fmt.Sprintf("adaptive initial index must be within %d..%d, got %d", indexConfig.Min, indexConfig.Max, indexConfig.Initial))
	}
	if IsAdaptiveUnifiedCacheIndexPolicy(normalizedIndexPolicy) && normalizedInsertionPolicy != UnifiedCacheInsertionPolicyExclusive {
		panic(fmt.Sprintf("%s index policy requires exclusive insertion policy", normalizedIndexPolicy))
	}
	if normalizedIndexPolicy == UnifiedCacheIndexPolicyEpochFrequent && indexConfig.EpochLength <= 0 {
		panic(fmt.Sprintf("adaptive epoch length must be greater than 0, got %d", indexConfig.EpochLength))
	}
	if indexConfig.LengthAwareMultiProbe && IsAdaptiveUnifiedCacheIndexPolicy(normalizedIndexPolicy) {
		panic("length-aware multi-probe cannot be combined with an adaptive index policy")
	}
	probeLengths := append([]int(nil), indexConfig.MultiProbeLengths...)
	sort.Ints(probeLengths)
	if indexConfig.LengthAwareMultiProbe {
		if len(probeLengths) == 0 {
			panic("length-aware multi-probe requires at least one probe length")
		}
		for i, length := range probeLengths {
			if length <= 0 || length >= 32 {
				panic(fmt.Sprintf("multi-probe length must satisfy 0 < length < 32, got %d", length))
			}
			if i > 0 && probeLengths[i-1] == length {
				panic(fmt.Sprintf("duplicate multi-probe length: %d", length))
			}
		}
	}
	if indexConfig.WayQuotaWideWays < 0 || indexConfig.WayQuotaWideWays >= int(way) {
		panic(fmt.Sprintf("way quota wide ways must satisfy 0 <= wide ways < way, got %d of %d", indexConfig.WayQuotaWideWays, way))
	}
	if indexConfig.WayQuotaWideWays > 0 && (indexConfig.WayQuotaWideMax < 0 || indexConfig.WayQuotaWideMax >= 32) {
		panic(fmt.Sprintf("way quota wide max must satisfy 0 <= max < 32, got %d", indexConfig.WayQuotaWideMax))
	}
	if normalizedExtensionPolicy != UnifiedCacheSetExtensionOff {
		if way != 8 {
			panic(fmt.Sprintf("set extension v1 requires way=8, got %d", way))
		}
		if normalizedInsertionPolicy != UnifiedCacheInsertionPolicyExclusive {
			panic("set extension v1 requires exclusive insertion policy")
		}
		if normalizedIndexPolicy != UnifiedCacheIndexPolicyFixed || indexConfig.LengthAwareMultiProbe || indexConfig.SkewedAssociative || indexConfig.WayQuotaWideWays > 0 {
			panic("set extension v1 cannot be combined with adaptive index, multi-probe, skewed associative, or way quota")
		}
		if indexConfig.SetExtensionEpochLength <= 0 || indexConfig.SetExtensionPressureThreshold == 0 || indexConfig.SetExtensionMaxPerSet <= 0 {
			panic("set extension epoch length, pressure threshold, and max per set must be greater than zero")
		}
	}

	sets_size := mainSize / way
	sets := make([]UnifiedCacheLine, sets_size)

	for i := uint(0); i < sets_size; i++ {
		sets[i] = *NewUnifiedCacheLine(
			way,
			routingTable,
			cacheIndexType,
			cacheTagLength,
			normalizedInsertionPolicy,
			debugMode,
			i,
		)
		if indexConfig.WayQuotaWideWays > 0 {
			sets[i].ConfigureWayQuota(indexConfig.WayQuotaWideMax, indexConfig.WayQuotaWideWays)
		}
	}
	minLength := 32
	for _, minmaxLength := range cacheTagLength {
		if minmaxLength[0] < minLength {
			minLength = minmaxLength[0]
		}
	}

	directIndexSize := sets_size
	// sets_sizeが2の何乗かを調べる
	if sets_size&(sets_size-1) != 0 && unifiedIndexRequiresPowerOfTwoSets(cacheIndexType) {
		panic(fmt.Sprintf("CacheIndexType %d requires a power-of-two main set count, got %d", cacheIndexType, sets_size))
	}
	directIndexSize = uint(math.Floor(math.Log2(float64(sets_size))))
	extensionBanksBySet := make([][]int, sets_size)
	extensionPressure := make([]uint64, sets_size)
	extensionBankCapacity := make([]int, indexConfig.SetExtensionMaxPerSet)
	extensionBankAllocated := make([]int, indexConfig.SetExtensionMaxPerSet)
	if normalizedExtensionPolicy != UnifiedCacheSetExtensionOff {
		poolSets := int(extensionSize / way)
		for bank := 0; bank < indexConfig.SetExtensionMaxPerSet; bank++ {
			extensionBankCapacity[bank] = poolSets / indexConfig.SetExtensionMaxPerSet
			if bank < poolSets%indexConfig.SetExtensionMaxPerSet {
				extensionBankCapacity[bank]++
			}
		}
	}

	return &UnifiedCache{
		Sets:                              sets,
		Way:                               way,
		Size:                              size,
		MainSize:                          mainSize,
		ExtensionSize:                     extensionSize,
		TotalPhysicalSize:                 totalPhysicalSize,
		CacheIndexType:                    cacheIndexType,
		IndexPolicy:                       normalizedIndexPolicy,
		AdaptiveInitial:                   indexConfig.Initial,
		AdaptiveMin:                       indexConfig.Min,
		AdaptiveMax:                       indexConfig.Max,
		AdaptiveEpochLength:               indexConfig.EpochLength,
		ActiveIndexLen:                    indexConfig.Initial,
		InsertionPolicy:                   normalizedInsertionPolicy,
		LengthAwareMultiProbe:             indexConfig.LengthAwareMultiProbe,
		MultiProbeLengths:                 probeLengths,
		WayQuotaWideMax:                   indexConfig.WayQuotaWideMax,
		WayQuotaWideWays:                  indexConfig.WayQuotaWideWays,
		SkewedAssociative:                 indexConfig.SkewedAssociative,
		SetExtensionPolicy:                normalizedExtensionPolicy,
		SetExtensionCapacityMode:          normalizedExtensionCapacityMode,
		SetExtensionPoolRatio:             indexConfig.SetExtensionPoolRatio,
		SetExtensionEpochLength:           indexConfig.SetExtensionEpochLength,
		SetExtensionPressureThreshold:     indexConfig.SetExtensionPressureThreshold,
		SetExtensionMaxPerSet:             indexConfig.SetExtensionMaxPerSet,
		extensionPressure:                 extensionPressure,
		extensionBanksBySet:               extensionBanksBySet,
		extensionBankCapacity:             extensionBankCapacity,
		extensionBankAllocated:            extensionBankAllocated,
		cacheTagLength:                    cacheTagLength,
		RoutingTable:                      *routingTable,
		DebugMode:                         debugMode,
		directIndexSize:                   directIndexSize,
		minCacheIndex:                     uint8(minLength),
		exclusiveRejectedSeenMissNetworks: [32]map[uint32]struct{}{},
	}

}
