package cache

import (
	"container/list"
	"fmt"
	"test-module/ipaddress"
	"test-module/routingtable"
)

type UnifiedCacheLine struct {
	Entries         map[uint32]*list.Element // キャッシュされたエントリのマップ。キーはMasked IP、値はリストの要素へのポインタ。
	Size            uint                     // キャッシュの最大サイズ。
	cacheTagLength  [][2]int
	cacheIndexType  int
	routingTable    *routingtable.RoutingTablePatriciaTrie
	debugMode       bool
	evictList       *list.List // 最も古いエントリを追跡するための双方向リスト。
	directIndexSize uint
	HitCount        [32]uint32
	EvictedCache    map[uint32]uint32
	// 初期参照性ミス数
	FirstMissCount      [32]uint32
	UniqueDstIP         [32][]uint32
	UniqueDstIPHitCount [32]map[uint32]uint32
	// 2回目以降の参照性ミス数
	SecondMissCount [32]uint32
	parentIndex     uint
}

type UnifiedCacheLineEntry struct {
	Refered   int
	Prefix    uint32
	FiveTuple FiveTuple // キャッシュされたFiveTuple。
	Length    uint8
	NextHop   string // 次のホップのアドレス。
}

type UnifiedCacheLineStat struct {
	HitCount            [32]uint32
	FirstMissCount      [32]uint32
	SecondMissCount     [32]uint32
	UniqueDstIPHitCount [32]map[uint32]uint32
}

func (cache *UnifiedCacheLine) ReturnMaskedIP(IP uint32, prefix uint8) uint32 {
	var temp uint32

	temp = IP
	temp = temp >> (32 - prefix)
	temp = temp << (32 - prefix)
	return temp
}

func (cache *UnifiedCacheLine) StatString() string {
	return ""
}

func (cache *UnifiedCacheLine) Stat() interface{} {
	return UnifiedCacheLineStat{
		HitCount:            cache.HitCount,
		FirstMissCount:      cache.FirstMissCount,
		SecondMissCount:     cache.SecondMissCount,
		UniqueDstIPHitCount: cache.UniqueDstIPHitCount,
	}

}

// AssertImmutableCondition は、キャッシュの状態が期待通りであることを確認します。
func (cache *UnifiedCacheLine) AssertImmutableCondition() {
	if int(cache.Size) < len(cache.Entries) {
		panic(fmt.Sprintln("len(cache.Entries):", len(cache.Entries), ", expected: less than or equal to", cache.Size))
	}

	if cache.evictList.Len() != int(cache.Size) {
		panic(fmt.Sprintln("cache.evictList.Len():", cache.evictList.Len(), ", expected: ", cache.Size))
	}
}

func (cache *UnifiedCacheLine) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *UnifiedCacheLine) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hit := false
	var hitElem *list.Element
	var dstIp uint32

	for dstIP, elem := range cache.Entries {
		unifiedEntry := elem.Value.(UnifiedCacheLineEntry)
		dstIp = f.DstIP
		if cache.ReturnMaskedIP(dstIp, unifiedEntry.Length) == dstIP {
			hit = true
			hitElem = elem
			break
		}
	}
	// if cache.parentIndex == 58 {
	// 	file, err := os.OpenFile("output.txt",
	// 		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	// 	if err != nil {
	// 		log.Fatal(err)
	// 	}
	// 	defer file.Close()

	// 	if _, err := file.WriteString(ipaddress.NewIPaddress(f.DstIP).String() + "\n"); err != nil {
	// 		log.Fatal(err)
	// 	}
	// }

	cache.AssertImmutableCondition()
	if hit {
		if update {
			cache.evictList.MoveToFront(hitElem)
			cache.HitCount[hitElem.Value.(UnifiedCacheLineEntry).Length]++

			// 参照カウントを更新
			hitEntry := hitElem.Value.(UnifiedCacheLineEntry)
			hitElem.Value = UnifiedCacheLineEntry{
				Refered:   hitEntry.Refered + 1,
				FiveTuple: hitEntry.FiveTuple,
				NextHop:   hitEntry.NextHop,
				Length:    hitEntry.Length,
				Prefix:    hitEntry.Prefix,
			}
		}
		if cache.debugMode && update {
			dstIpAddress := ipaddress.NewIPaddress(f.DstIP)
			hitIP, item := cache.routingTable.SearchLongestIP(dstIpAddress, 32)

			if item.(routingtable.Data).NextHop != hitElem.Value.(UnifiedCacheLineEntry).NextHop {
				println("hitIP: ", ipaddress.BitStringToIP(hitIP), "dstIP: ", dstIpAddress.String())

				println("hitElem.Value.(UnifiedCacheLineEntry).FiveTuple.DstIP: ", ipaddress.NewIPaddress(hitElem.Value.(UnifiedCacheLineEntry).FiveTuple.DstIP).String())
				println("(UnifiedCacheLineEntry).NextHop: ", hitElem.Value.(UnifiedCacheLineEntry).NextHop)
				println("(routingtable.Data).NextHop: ", item.(routingtable.Data).NextHop)
				dstIpAddressString := dstIpAddress.String()
				_ = dstIpAddressString
				panic("NextHop is different")
			}
		}
	} else {
		if update {
			cacheLength := f.IsLeafIndex
			// cacheTagLength = [[8, 24], [16, 32], [24, 32]] みたいな感じで8を出力する、min(8,16,24)

			cachetagmin := 32
			cacheTagMax := 0
			for i := 0; i < len(cache.cacheTagLength); i++ {
				if cache.cacheTagLength[i][0] < cachetagmin {
					cachetagmin = cache.cacheTagLength[i][0]
				}
				if cache.cacheTagLength[i][1] > cacheTagMax {
					cacheTagMax = cache.cacheTagLength[i][1]
				}
			}
			if cacheLength < int8(cachetagmin) {
				cacheLength = int8(cachetagmin)
			}
			// Maxの場合はキャッシュできない

			dstNetwork := f.DstIP >> (32 - uint8(cacheLength))
			// uniqueCache[cacheLength]にdstNetworkが存在するか確認
			found := false
			for _, ip := range cache.UniqueDstIP[cacheLength] {
				if ip == dstNetwork {
					found = true  // dstNetworkで判断
					break
				}
			}
			if cache.UniqueDstIPHitCount[cacheLength] == nil {
				cache.UniqueDstIPHitCount[cacheLength] = make(map[uint32]uint32)
			}
			cache.UniqueDstIPHitCount[cacheLength][dstNetwork]++

			if !found {
				cache.FirstMissCount[f.IsLeafIndex]++
			} else {
				cache.SecondMissCount[f.IsLeafIndex]++
			}
		if cache.debugMode && update {
			dstIpAddress := ipaddress.NewIPaddress(f.DstIP)
			hitIP, item := cache.routingTable.SearchLongestIP(dstIpAddress, 32)

			// ヒットしていないのにNextHopが同じなことはありえない,逆の部分も見る
			if item.(routingtable.Data).NextHop == hitElem.Value.(UnifiedCacheLineEntry).NextHop {
				println("hitIP: ", ipaddress.BitStringToIP(hitIP), "dstIP: ", dstIpAddress.String())

				println("hitElem.Value.(UnifiedCacheLineEntry).FiveTuple.DstIP: ", ipaddress.NewIPaddress(hitElem.Value.(UnifiedCacheLineEntry).FiveTuple.DstIP).String())
				println("(UnifiedCacheLineEntry).NextHop: ", hitElem.Value.(UnifiedCacheLineEntry).NextHop)
				println("(routingtable.Data).NextHop: ", item.(routingtable.Data).NextHop)
				dstIpAddressString := dstIpAddress.String()
				_ = dstIpAddressString
				panic("NextHop is different")
			}
		}

			// if _, exists := cache.EvictedCache[dstNetwork]; !exists {
			// 	cache.SecondMissCount[f.IsLeafIndex]++
			// } else {
			// 	cache.FirstMissCount[f.IsLeafIndex]++
			// }
		}
	}

	var entryIndexPtr *int
	if !hit {
		entryIndexPtr = nil
	} else {
		entryIndex := int(f.DstIP)
		entryIndexPtr = &entryIndex
	}
	cache.AssertImmutableCondition()

	return hit, entryIndexPtr
}

// CacheFiveTuple は、新しい FiveTuple をキャッシュします。
// キャッシュが満杯の場合、最も古いエントリを削除して新しいエントリを追加します。
// 置き換えられたエントリの FiveTuple を返します。
func (cache *UnifiedCacheLine) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	cache.AssertImmutableCondition()

	evictedFiveTuples := []*FiveTuple{}

	if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
		return evictedFiveTuples
	}

	// 各wayのcacheTagLengthをチェックして、キャッシュ可能かどうか判断
	canCache := false
	var cacheLength int8
	for wayIdx := 0; wayIdx < int(cache.Size); wayIdx++ {
		cacheTagLength := cache.cacheTagLength[wayIdx]
		cacheTagLengthStart := cacheTagLength[0]
		cacheTagLengthEnd := cacheTagLength[1]
		if int(f.IsLeafIndex) <= cacheTagLengthEnd {
			canCache = true
			if int(f.IsLeafIndex) > cacheTagLengthStart {
				cacheLength = f.IsLeafIndex
			} else {
				cacheLength = int8(cacheTagLengthStart)
			}
		}
	}

	if !canCache {
		return evictedFiveTuples
	}

	oldestElem := cache.evictList.Back()

	replacedEntry := cache.evictList.Remove(oldestElem).(UnifiedCacheLineEntry)

	delete(cache.Entries, cache.ReturnMaskedIP(replacedEntry.FiveTuple.DstIP, replacedEntry.Length))

	var newEntry UnifiedCacheLineEntry
	if cache.debugMode {

		// デバッグモードの場合、ルーティングテーブルを参照してエントリを作成する
		maskDstIP := cache.ReturnMaskedIP(f.DstIP, uint8(cacheLength))

		hit, item := cache.routingTable.SearchLongestIP(ipaddress.NewIPaddress(maskDstIP), int(cacheLength))

		_ = hit

		// fmt.Println("caching hitIP: ", ipaddress.BitStringToIP(hit), "dstIP: ", ipaddress.NewIPaddress(maskDstIP).String())
		newEntry = UnifiedCacheLineEntry{
			FiveTuple: *f,
			NextHop:   item.(routingtable.Data).NextHop,
			Length:    uint8(cacheLength),
			Prefix:    maskDstIP,
			Refered:   1, // 新しいエントリは参照されているとみなす
		}
	} else {
		newEntry = UnifiedCacheLineEntry{
			FiveTuple: *f,
			Length:    uint8(cacheLength),
		}
	}

	newElem := cache.evictList.PushFront(newEntry)
	cache.Entries[cache.ReturnMaskedIP(f.DstIP, uint8(cacheLength))] = newElem

	cache.AssertImmutableCondition()
	dstNetwork := f.DstIP >> (32 - cacheLength)

	found := false
	for _, ip := range cache.UniqueDstIP[cacheLength] {
		if ip == dstNetwork {
			found = true
			break
		}
	}
	if !found {
		cache.UniqueDstIP[cacheLength] = append(cache.UniqueDstIP[cacheLength], dstNetwork)
	}
	if replacedEntry.FiveTuple == (FiveTuple{}) {
		return evictedFiveTuples
	}

	evictedFiveTuples = append(evictedFiveTuples, &replacedEntry.FiveTuple)

	return evictedFiveTuples
}

// InvalidateFiveTuple は、指定された FiveTuple をキャッシュから削除します。
// 削除が成功すると、キャッシュの整合性が再確認されます。
func (cache *UnifiedCacheLine) InvalidateFiveTuple(f *FiveTuple) {
	panic("Not implemented")
	// hitElem, hit := cache.Entries[cache.ReturnMaskedIP(f.DstIP,)]

	// if !hit {
	// 	panic("entry not cached")
	// }

	// cache.evictList.Remove(hitElem)
	// delete(cache.Entries, cache.ReturnMaskedIP((f.DstIP)))

	// cache.evictList.PushBack(UnifiedCacheLineEntry{})

	// cache.AssertImmutableCondition()
}

// Clear は、キャッシュをクリアします。
// 現在は未実装で、呼び出されるとパニックを発生させます。
func (cache *UnifiedCacheLine) Clear() {
	panic("Not implemented")
}

// Description は、キャッシュの説明文字列を返します。
func (cache *UnifiedCacheLine) Description() string {
	return "NbitFullAssociativeDstipLRUCache"
}

// ParameterString は、キャッシュのパラメータをJSON形式の文字列として返します。
func (cache *UnifiedCacheLine) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Size\": %d}", cache.Description(), cache.Size)
}

// NewFullAssociativeDstipNbitLRUCacheParameter は、新しい FullAssociativeDstipNbitLRUCacheParameter を作成します。
func (cache *UnifiedCacheLine) Parameter() Parameter {
	return &UnifiedCacheLineParameter{
		Type:           cache.Description(),
		Size:           int(cache.Size),
		CacheTagLength: cache.cacheTagLength,
	}
}

// NewFullAssociativeDstipNbitLRUCache は、新しい UnifiedCacheLine を作成します。
// refbits は参照ビットの数、size はキャッシュのサイズを指定します。
func NewUnifiedCacheLine(
	size uint,
	routingTable *routingtable.RoutingTablePatriciaTrie,
	cacheIndexType int,
	cacheTagLength [][2]int,
	debugMode bool,
	parentIndex uint,
) *UnifiedCacheLine {
	evictList := list.New()

	for i := 0; i < int(size); i++ {
		evictList.PushBack(UnifiedCacheLineEntry{})
	}

	return &UnifiedCacheLine{
		Entries:        map[uint32]*list.Element{},
		Size:           size,
		evictList:      evictList,
		routingTable:   routingTable,
		cacheIndexType: cacheIndexType,
		cacheTagLength: cacheTagLength,
		debugMode:      debugMode,
		EvictedCache:   make(map[uint32]uint32),
		parentIndex:    parentIndex,
	}
}
