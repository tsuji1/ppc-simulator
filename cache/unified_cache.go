package cache

import (
	"fmt"
	"hash/crc32"
	"math"
	"test-module/ipaddress"
	"test-module/routingtable"
)

const (
	CACHE_INDEX_TYPE_DIRECT = iota
	CACHE_INDEX_TYPE_HASH
)

type UnifiedCache struct {
	Sets            []UnifiedCacheLine // len(Sets) = Size / Way, each size == Way
	Way             uint
	Size            uint
	CacheIndexType  int
	RoutingTable    routingtable.RoutingTablePatriciaTrie
	DepthSum        uint64
	LongestMatchMap [33]int
	MatchMap        [33]int
	DebugMode       bool
	cacheTagLength  [][]int
	directIndexSize uint
}

func (c *UnifiedCache) StatString() string {
	str := "{}"
	return str
}

type UnifiedCacheStat struct {
	Refered         []uint
	Replaced        []uint
	Hit             []uint
	MatchMap        []uint
	LongestMatchMap []uint
	DepthSum        uint
	Inserted        []uint
	directIndexSize uint
}

func (cache *UnifiedCache) Stat() interface{} {
	return NWaySetAssociativeLRUCacheStat{
		DepthSum: cache.DepthSum,
	}
}

func (cache *UnifiedCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *UnifiedCache) setIdx(f *FiveTuple) uint {

	maxSetIdx := cache.Size / cache.Way
	_ = maxSetIdx

	switch cache.CacheIndexType {
	case CACHE_INDEX_TYPE_DIRECT:
		// 宛先ipの上位size を使う
		idx := f.DstIP >> (32 - cache.directIndexSize)
		return uint(idx)
	case CACHE_INDEX_TYPE_HASH:
		// ハッシュ値を使う
		dstIP := f.DstIP >> (16)
		crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))
		return uint(crc) % maxSetIdx
	default:
		panic(fmt.Sprintf("Unknown CacheIndexType: %d", cache.CacheIndexType))
	}
}

func (cache *UnifiedCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	setIdx := cache.setIdx(f)
	return cache.Sets[setIdx].IsCachedWithFiveTuple(f, update)
}

func (cache *UnifiedCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	setIdx := cache.setIdx(f)

	// プレフィックス情報を取得
	_, prefix_item := cache.RoutingTable.SearchLongestIP(ipaddress.NewIPaddress(f.DstIP), 32)

	// 統計情報を更新
	cache.DepthSum += prefix_item.(routingtable.Data).Depth

	// 各wayのcacheTagLengthをチェックして、キャッシュ可能かどうか判断
	canCache := false
	for wayIdx := 0; wayIdx < int(cache.Way); wayIdx++ {
		for _, tagLength := range cache.cacheTagLength[wayIdx] {
			if isLeaf(f, &cache.RoutingTable, tagLength) {
				canCache = true
			}
		}
		if canCache {
			break
		}
	}

	// キャッシュ可能な場合のみ実際にキャッシュする
	if canCache {
		return cache.Sets[setIdx].CacheFiveTuple(f)
	}

	// キャッシュできない場合は空のスライスを返す
	return []*FiveTuple{}
}

func (cache *UnifiedCache) InvalidateFiveTuple(f *FiveTuple) {
	setIdx := cache.setIdx(f)
	cache.Sets[setIdx].InvalidateFiveTuple(f)
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
	return &SetAssociativeParameter{
		Type: cache.Description(),
		Way:  cache.Way,
		Size: cache.Size,
	}
}

// cacheTagLengthは、wayごとにキャッシュタグの長さを指定するスライスです。[16,17]だと、16,17ビットを許容する。
func NewUnifiedCache(size uint, way uint, routingTable *routingtable.RoutingTablePatriciaTrie, cacheIndexType int, cacheTagLength [][]int, debugMode bool) *UnifiedCache {
	if size%way != 0 {
		panic("Size must be multiplier of way")
	}
	if len(cacheTagLength) != int(way) {
		panic(fmt.Sprintf("cacheTagLength must have %d items, but got %d", way, len(cacheTagLength)))
	}

	sets_size := size / way
	sets := make([]UnifiedCacheLine, sets_size)

	for i := uint(0); i < sets_size; i++ {
		sets[i] = *NewUnifiedCacheLine(
			way,
			routingTable,
			cacheIndexType,
			cacheTagLength,
			debugMode,
		)
	}

	directIndexSize := sets_size
	// sets_sizeが2の何乗かを調べる
	if sets_size&(sets_size-1) != 0 {
		panic("sets_size must be power of 2")
	}
	directIndexSize = uint(math.Log2(float64(sets_size)))

	return &UnifiedCache{
		Sets:            sets,
		Way:             way,
		Size:            size,
		CacheIndexType:  cacheIndexType,
		cacheTagLength:  cacheTagLength,
		RoutingTable:    *routingTable,
		DebugMode:       debugMode,
		directIndexSize: directIndexSize,
	}

}
