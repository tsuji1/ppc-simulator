package cache

import (
	"fmt"
	"hash/crc32"
	"math"
	"os"
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
	cacheTagLength  [][2]int
	directIndexSize uint
	minCacheIndex   uint8
	writeCount      uint64
	writeCountMax   uint64
}

func (c *UnifiedCache) StatString() string {
	str := "{}"
	return str
}

type UnifiedCacheStat struct {
	DepthSum                 uint64
	CachelineHitCount        [][32]uint32
	CachelineFirstMissCount  [][32]uint32
	CachelineSecondMissCount [][32]uint32
}

func (cache *UnifiedCache) Stat() interface{} {
	UnifiedCacheStat := UnifiedCacheStat{
		DepthSum: cache.DepthSum,
	}
	for i := 0; i < len(cache.Sets); i++ {
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

		if cache.Size > 4096 && max_secondMisscount < 200 && max_secondMisscount > 100 && cache.writeCount == 0 {
			uniqueDstIPHitCount := cacheLineStat.(UnifiedCacheLineStat).UniqueDstIPHitCount
			fmt.Printf("Max second miss count exceeded: %d (index: %d)\n", max_secondMisscount, max_index)

			cache.writeCount++
			save := uniqueDstIPHitCount[max_index]
			// fileに保存
			file, err := os.Create(fmt.Sprintf("cache_debug_size%d_%d_%d_100-200.txt", cache.Size, i, max_index))
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
		if cache.Size > 4096 && max_secondMisscount > 3000 {
			uniqueDstIPHitCount := cacheLineStat.(UnifiedCacheLineStat).UniqueDstIPHitCount
			fmt.Printf("Max second miss count exceeded: %d (index: %d)\n", max_secondMisscount, max_index)

			save := uniqueDstIPHitCount[max_index]
			// fileに保存
			file, err := os.Create(fmt.Sprintf("cache_debug_size%d_%d_%d_%d_3000.txt", cache.Size, i, max_index,cache.writeCountMax))
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

	maxSetIdx := cache.Size / cache.Way
	_ = maxSetIdx
	idxType := cache.CacheIndexType

	// PREFIX8 - PREFIX24 でindex化を行う
	// 9- 24
	if idxType > CACHE_INDEX_TYPE_PREFIX18 && idxType < 25 {
		dstIP := f.DstIP >> (32 - idxType)
		crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))
		return uint(crc) % maxSetIdx

	}

	switch cache.CacheIndexType {
	case CACHE_INDEX_TYPE_DIRECT:
		// 宛先ipの上位size を使う
		idx := f.DstIP >> (32 - cache.directIndexSize)
		return uint(idx)
	case CACHE_INDEX_TYPE_HASH:
		// ハッシュ値を使う
		dstIP := f.DstIP >> (16) //使う
		crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))
		return uint(crc) % maxSetIdx
	case CACHE_INDEX_TYPE_IDEAL:
		dstIP := f.DstIP >> (16) //使う

		if f.IsLeafIndex > 16 && f.IsLeafIndex < 25 {
			dstIP = f.DstIP >> (32 - f.IsLeafIndex)
		}
		if f.IsLeafIndex > 24 {
			dstIP = f.DstIP >> 8
		}

		crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))

		return uint(crc) % maxSetIdx
	case CACHE_INDEX_TYPE_PREFIX24:
		dstIP := f.DstIP >> (8) //使う
		crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))

		return uint(crc) % maxSetIdx
	case CACHE_INDEX_TYPE_PREFIX20:
		dstIP := f.DstIP >> (12) //使う
		crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))

		return uint(crc) % maxSetIdx
	case CACHE_INDEX_TYPE_PREFIX18:
		dstIP := f.DstIP >> (14) //使う
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
	return &UnifiedCacheParameter{
		Type:           cache.Description(),
		Way:            cache.Way,
		Size:           cache.Size,
		CacheIndexType: cache.CacheIndexType,
		CacheTagLength: cache.cacheTagLength,
	}
}

// cacheTagLengthは、wayごとにキャッシュタグの長さを指定するスライスです。[16,17]だと、16,17ビットを許容する。
func NewUnifiedCache(size uint, way uint, routingTable *routingtable.RoutingTablePatriciaTrie, cacheIndexType int, cacheTagLength [][2]int, debugMode bool) *UnifiedCache {
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
			i,
		)
	}
	minLength := 32
	for _, minmaxLength := range cacheTagLength {
		if minmaxLength[0] < minLength {
			minLength = minmaxLength[0]
		}
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
		minCacheIndex:   uint8(minLength),
	}

}
