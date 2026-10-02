package cache

import (
	"container/list"
	"fmt"
	"test-module/ipaddress"
	"test-module/routingtable"
)

type UnifiedCacheLine struct {
	Entries          map[unifiedCacheLineEntryKey]*list.Element // キャッシュされたエントリのマップ。キーはMasked IPとprefix長、値はリストの要素へのポインタ。
	Size             uint                                       // キャッシュの最大サイズ。
	cacheTagLength   [][2]int
	cacheIndexType   int
	insertionPolicy  string
	routingTable     *routingtable.RoutingTablePatriciaTrie
	debugMode        bool
	evictList        *list.List // 最も古いエントリを追跡するための双方向リスト。
	directIndexSize  uint
	wayQuotaWideMax  int
	wayQuotaWideWays int
	HitCount         [32]uint32
	EvictedCache     map[uint32]uint32
	// 初期参照性ミス数
	FirstMissCount      [32]uint32
	UniqueDstIP         [32][]uint32
	UniqueDstIPHitCount [32]map[uint32]uint32
	// 2回目以降の参照性ミス数
	SecondMissCount   [32]uint32
	SecondMissIPCount [32]map[uint32]uint32
	parentIndex       uint
	BaseSize          uint
}

type UnifiedCacheLineEntry struct {
	Refered     int
	Prefix      uint32
	FiveTuple   FiveTuple // キャッシュされたFiveTuple。
	Length      uint8
	NextHop     string // 次のホップのアドレス。
	StorageBank int    // 0=Main, 1..N=Extension bank
}

type unifiedCacheLineEntryKey struct {
	Network uint32
	Length  uint8
}

type UnifiedCacheLineStat struct {
	HitCount            [32]uint32
	FirstMissCount      [32]uint32
	SecondMissCount     [32]uint32
	UniqueDstIPHitCount [32]map[uint32]uint32
	SecondMissIPCount   [32]map[uint32]uint32
}

func (cache *UnifiedCacheLine) ReturnMaskedIP(IP uint32, prefix uint8) uint32 {
	var temp uint32

	temp = IP
	temp = temp >> (32 - prefix)
	temp = temp << (32 - prefix)
	return temp
}

func (cache *UnifiedCacheLine) entryKey(dstIP uint32, prefix uint8) unifiedCacheLineEntryKey {
	return unifiedCacheLineEntryKey{
		Network: cache.ReturnMaskedIP(dstIP, prefix),
		Length:  prefix,
	}
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
		SecondMissIPCount:   cache.SecondMissIPCount,
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

func (cache *UnifiedCacheLine) LongestMatchLength(f *FiveTuple) (uint8, bool) {
	length, _, found := cache.LongestMatchLocation(f)
	return length, found
}

func (cache *UnifiedCacheLine) LongestMatchLocation(f *FiveTuple) (uint8, int, bool) {
	var longest uint8
	bank := 0
	found := false
	for key, elem := range cache.Entries {
		entry := elem.Value.(UnifiedCacheLineEntry)
		if cache.ReturnMaskedIP(f.DstIP, entry.Length) == key.Network &&
			(!found || entry.Length > longest) {
			longest = entry.Length
			bank = entry.StorageBank
			found = true
		}
	}
	return longest, bank, found
}

func (cache *UnifiedCacheLine) ResidentCount() int {
	return len(cache.Entries)
}

func (cache *UnifiedCacheLine) IsFull() bool {
	return cache.ResidentCount() >= int(cache.Size)
}

func (cache *UnifiedCacheLine) ExtensionSetCount() int {
	if cache.Size <= cache.BaseSize || cache.BaseSize == 0 {
		return 0
	}
	return int((cache.Size - cache.BaseSize) / cache.BaseSize)
}

// GrowExtensionSet adds one physical extension set while preserving a single
// logical LRU order across Main and all extension banks.
func (cache *UnifiedCacheLine) GrowExtensionSet(bank int) {
	if bank <= 0 {
		panic("extension bank must be greater than zero")
	}
	for i := uint(0); i < cache.BaseSize; i++ {
		cache.evictList.PushBack(UnifiedCacheLineEntry{StorageBank: bank})
	}
	cache.Size += cache.BaseSize
	cache.AssertImmutableCondition()
}

func (cache *UnifiedCacheLine) HasSeenMissNetwork(f *FiveTuple) bool {
	cacheLength, ok := selectUnifiedCacheLength(
		f,
		cache.cacheTagLength,
		cache.insertionPolicy == UnifiedCacheInsertionPolicyInclusive,
	)
	if !ok {
		return false
	}
	dstNetwork := f.DstIP >> (32 - uint8(cacheLength))
	for _, network := range cache.UniqueDstIP[int(cacheLength)] {
		if network == dstNetwork {
			return true
		}
	}
	return false
}

func (cache *UnifiedCacheLine) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hit := false
	var hitElem *list.Element

	for key, elem := range cache.Entries {
		unifiedEntry := elem.Value.(UnifiedCacheLineEntry)
		if cache.ReturnMaskedIP(f.DstIP, unifiedEntry.Length) == key.Network &&
			(!hit || unifiedEntry.Length > hitElem.Value.(UnifiedCacheLineEntry).Length) {
			hit = true
			hitElem = elem
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
				Refered:     hitEntry.Refered + 1,
				FiveTuple:   hitEntry.FiveTuple,
				NextHop:     hitEntry.NextHop,
				Length:      hitEntry.Length,
				Prefix:      hitEntry.Prefix,
				StorageBank: hitEntry.StorageBank,
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
			cacheLength, canRecordMiss := selectUnifiedCacheLength(
				f,
				cache.cacheTagLength,
				cache.insertionPolicy == UnifiedCacheInsertionPolicyInclusive,
			)
			if canRecordMiss {
				lengthIndex := int(cacheLength)
				dstNetwork := f.DstIP >> (32 - uint8(cacheLength))
				// uniqueCache[cacheLength]にdstNetworkが存在するか確認
				found := false
				for _, ip := range cache.UniqueDstIP[lengthIndex] {
					if ip == dstNetwork {
						found = true // dstNetworkで判断
						break
					}
				}
				if cache.UniqueDstIPHitCount[lengthIndex] == nil {
					cache.UniqueDstIPHitCount[lengthIndex] = make(map[uint32]uint32)
				}
				cache.UniqueDstIPHitCount[lengthIndex][dstNetwork]++

				if !found {
					cache.FirstMissCount[lengthIndex]++
				} else {
					cache.SecondMissCount[lengthIndex]++
					if cache.SecondMissIPCount[lengthIndex] == nil {
						cache.SecondMissIPCount[lengthIndex] = make(map[uint32]uint32)
					}
					cache.SecondMissIPCount[lengthIndex][dstNetwork]++
				}
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

	cacheLength, canCache := selectUnifiedCacheLength(
		f,
		cache.cacheTagLength,
		cache.insertionPolicy == UnifiedCacheInsertionPolicyInclusive,
	)
	if !canCache {
		return evictedFiveTuples
	}

	evicted, _ := cache.cacheFiveTupleWithLength(f, uint8(cacheLength))
	return evicted
}

func (cache *UnifiedCacheLine) CacheFiveTupleWithLength(f *FiveTuple, cacheLength uint8) []*FiveTuple {
	evicted, _ := cache.CacheFiveTupleWithLengthAndBank(f, cacheLength)
	return evicted
}

func (cache *UnifiedCacheLine) CacheFiveTupleWithLengthAndBank(f *FiveTuple, cacheLength uint8) ([]*FiveTuple, int) {
	cache.AssertImmutableCondition()
	if elem, ok := cache.Entries[cache.entryKey(f.DstIP, cacheLength)]; ok {
		return []*FiveTuple{}, elem.Value.(UnifiedCacheLineEntry).StorageBank
	}
	return cache.cacheFiveTupleWithLength(f, cacheLength)
}

func (cache *UnifiedCacheLine) cacheFiveTupleWithLength(f *FiveTuple, cacheLength uint8) ([]*FiveTuple, int) {
	evictedFiveTuples := []*FiveTuple{}

	oldestElem := cache.victimForLength(cacheLength)
	replacedEntry := cache.removeElement(oldestElem)
	evictedFiveTuples = append(evictedFiveTuples, cache.cascadeEvictAncestors(replacedEntry)...)

	newEntry := cache.newEntry(f, cacheLength)
	newEntry.StorageBank = replacedEntry.StorageBank
	newElem := cache.evictList.PushFront(newEntry)
	cache.Entries[cache.entryKey(f.DstIP, cacheLength)] = newElem

	cache.recordInsertedNetwork(f.DstIP, cacheLength)
	cache.AssertImmutableCondition()
	if replacedEntry.FiveTuple != (FiveTuple{}) {
		evictedFiveTuples = append(evictedFiveTuples, &replacedEntry.FiveTuple)
	}

	return evictedFiveTuples, newEntry.StorageBank
}

func (cache *UnifiedCacheLine) victimForLength(cacheLength uint8) *list.Element {
	if cache.wayQuotaWideWays <= 0 {
		return cache.evictList.Back()
	}

	requestWide := int(cacheLength) <= cache.wayQuotaWideMax
	quota := cache.wayQuotaWideWays
	if !requestWide {
		quota = int(cache.Size) - cache.wayQuotaWideWays
	}

	residentInGroup := 0
	var empty *list.Element
	var oldestInGroup *list.Element
	for elem := cache.evictList.Back(); elem != nil; elem = elem.Prev() {
		entry := elem.Value.(UnifiedCacheLineEntry)
		if entry.FiveTuple == (FiveTuple{}) {
			if empty == nil {
				empty = elem
			}
			continue
		}
		if (int(entry.Length) <= cache.wayQuotaWideMax) == requestWide {
			residentInGroup++
			if oldestInGroup == nil {
				oldestInGroup = elem
			}
		}
	}
	if residentInGroup >= quota && oldestInGroup != nil {
		return oldestInGroup
	}
	if residentInGroup < quota && empty != nil {
		return empty
	}
	panic(fmt.Sprintf("way quota invariant violated: length=%d wide_max=%d wide_ways=%d", cacheLength, cache.wayQuotaWideMax, cache.wayQuotaWideWays))
}

func (cache *UnifiedCacheLine) ConfigureWayQuota(wideMax, wideWays int) {
	cache.wayQuotaWideMax = wideMax
	cache.wayQuotaWideWays = wideWays
}

func (cache *UnifiedCacheLine) removeElement(elem *list.Element) UnifiedCacheLineEntry {
	replacedEntry := cache.evictList.Remove(elem).(UnifiedCacheLineEntry)
	if replacedEntry.FiveTuple != (FiveTuple{}) {
		delete(cache.Entries, cache.entryKey(replacedEntry.FiveTuple.DstIP, replacedEntry.Length))
	}
	return replacedEntry
}

func (cache *UnifiedCacheLine) cascadeEvictAncestors(replacedEntry UnifiedCacheLineEntry) []*FiveTuple {
	if cache.insertionPolicy != UnifiedCacheInsertionPolicyInclusive || replacedEntry.FiveTuple == (FiveTuple{}) {
		return nil
	}

	evictedFiveTuples := []*FiveTuple{}
	for key, elem := range cache.Entries {
		if key.Length >= replacedEntry.Length {
			continue
		}
		if cache.ReturnMaskedIP(replacedEntry.FiveTuple.DstIP, key.Length) != key.Network {
			continue
		}
		entry := cache.removeElement(elem)
		cache.evictList.PushBack(UnifiedCacheLineEntry{StorageBank: entry.StorageBank})
		if entry.FiveTuple != (FiveTuple{}) {
			evictedFiveTuples = append(evictedFiveTuples, &entry.FiveTuple)
		}
	}
	return evictedFiveTuples
}

func (cache *UnifiedCacheLine) newEntry(f *FiveTuple, cacheLength uint8) UnifiedCacheLineEntry {
	maskDstIP := cache.ReturnMaskedIP(f.DstIP, cacheLength)
	if cache.debugMode {
		// デバッグモードの場合、ルーティングテーブルを参照してエントリを作成する
		hit, item := cache.routingTable.SearchLongestIP(ipaddress.NewIPaddress(maskDstIP), int(cacheLength))
		_ = hit
		return UnifiedCacheLineEntry{
			FiveTuple: *f,
			NextHop:   item.(routingtable.Data).NextHop,
			Length:    cacheLength,
			Prefix:    maskDstIP,
			Refered:   1, // 新しいエントリは参照されているとみなす
		}
	}

	return UnifiedCacheLineEntry{
		FiveTuple: *f,
		Length:    cacheLength,
		Prefix:    maskDstIP,
		Refered:   1,
	}
}

func (cache *UnifiedCacheLine) recordInsertedNetwork(dstIP uint32, cacheLength uint8) {
	dstNetwork := dstIP >> (32 - cacheLength)

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
	insertionPolicy string,
	debugMode bool,
	parentIndex uint,
) *UnifiedCacheLine {
	evictList := list.New()

	for i := 0; i < int(size); i++ {
		evictList.PushBack(UnifiedCacheLineEntry{StorageBank: 0})
	}

	return &UnifiedCacheLine{
		Entries:         map[unifiedCacheLineEntryKey]*list.Element{},
		Size:            size,
		evictList:       evictList,
		routingTable:    routingTable,
		cacheIndexType:  cacheIndexType,
		cacheTagLength:  cacheTagLength,
		insertionPolicy: insertionPolicy,
		debugMode:       debugMode,
		EvictedCache:    make(map[uint32]uint32),
		parentIndex:     parentIndex,
		BaseSize:        size,
	}
}
