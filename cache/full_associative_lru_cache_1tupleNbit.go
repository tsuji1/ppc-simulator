package cache

import (
	"container/list"
	"fmt"
	"test-module/ipaddress"
	"test-module/routingtable"
	
)

// FullAssociativeDstipNbitLRUCache は、Nビットの参照ビットを使用してフルアソシエイティブLRUキャッシュを管理する構造体です。
// キャッシュはエントリのマップと、最も古いエントリを追跡するための双方向リストを使用して実装されています。
type FullAssociativeDstipNbitLRUCache struct {
	Entries      map[uint32]*list.Element // キャッシュされたエントリのマップ。キーはMasked IP、値はリストの要素へのポインタ。
	Size         uint                     // キャッシュの最大サイズ。
	routingTable *routingtable.RoutingTablePatriciaTrie
	debugMode    bool
	Refbits      uint       // 参照ビットの数。
	evictList    *list.List // 最も古いエントリを追跡するための双方向リスト。
}

// ReturnMaskedIP は、与えられたIPアドレスの最上位Nビットを取得し、残りのビットを0に設定して返します。
// このNビットは、キャッシュで使用される参照ビットの数に基づいて決定されます。
func (cache *FullAssociativeDstipNbitLRUCache) ReturnMaskedIP(IP uint32) uint32 {
	var temp uint32

	temp = IP
	temp = temp >> (32 - cache.Refbits)
	temp = temp << (32 - cache.Refbits)
	return temp
}

// StatString は、キャッシュの統計情報を文字列として返します。
// 現在は未実装です。
func (cache *FullAssociativeDstipNbitLRUCache) StatString() string {
	return ""
}

// AssertImmutableCondition は、キャッシュの状態が期待通りであることを確認します。
// サイズやエントリ数が不整合であればパニックを発生させます。
func (cache *FullAssociativeDstipNbitLRUCache) AssertImmutableCondition() {
	if int(cache.Size) < len(cache.Entries) {
		panic(fmt.Sprintln("len(cache.Entries):", len(cache.Entries), ", expected: less than or equal to", cache.Size))
	}

	if cache.evictList.Len() != int(cache.Size) {
		panic(fmt.Sprintln("cache.evictList.Len():", cache.evictList.Len(), ", expected: ", cache.Size))
	}
}

// IsCached は、パケットがキャッシュに存在するかをチェックします。
// update が true の場合、キャッシュのエントリを更新します。
func (cache *FullAssociativeDstipNbitLRUCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

// IsCachedWithFiveTuple は、指定された FiveTuple がキャッシュに存在するかをチェックします。
// update が true の場合、キャッシュのエントリを更新します。
func (cache *FullAssociativeDstipNbitLRUCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	dstIP := cache.ReturnMaskedIP(f.DstIP)
	hitElem, hit := cache.Entries[dstIP]

	cache.AssertImmutableCondition()
	if hit {
		if update {
			cache.evictList.MoveToFront(hitElem)

			// 参照カウントを更新
			hitEntry := hitElem.Value.(fullAssociativeLRUCacheEntry)
			hitElem.Value = fullAssociativeLRUCacheEntry{
				Refered:   hitEntry.Refered + 1,
				FiveTuple: hitEntry.FiveTuple,
				NextHop:   hitEntry.NextHop,
			}
		}
		if cache.debugMode {
			dstIpAddress := ipaddress.NewIPaddress(dstIP)
			hitIP, item := cache.routingTable.SearchLongestIP(dstIpAddress, 32)

			if item.(routingtable.Data).NextHop != hitElem.Value.(fullAssociativeLRUCacheEntry).NextHop {
				println("hitIP: ", ipaddress.BitStringToIP(hitIP), "dstIP: ", dstIpAddress.String())
				println("(fullAssociativeLRUCacheEntry).NextHop: ", hitElem.Value.(fullAssociativeLRUCacheEntry).NextHop)
				println("(routingtable.Data).NextHop: ", item.(routingtable.Data).NextHop)
				panic("NextHop is different")
			}
		}
	}

	var entryIndexPtr *int
	entryIndex := int(dstIP)
	entryIndexPtr = &entryIndex

	cache.AssertImmutableCondition()

	return hit, entryIndexPtr
}

// CacheFiveTuple は、新しい FiveTuple をキャッシュします。
// キャッシュが満杯の場合、最も古いエントリを削除して新しいエントリを追加します。
// 置き換えられたエントリの FiveTuple を返します。
func (cache *FullAssociativeDstipNbitLRUCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	cache.AssertImmutableCondition()

	evictedFiveTuples := []*FiveTuple{}

	if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
		return evictedFiveTuples
	}

	oldestElem := cache.evictList.Back()

	replacedEntry := cache.evictList.Remove(oldestElem).(fullAssociativeLRUCacheEntry)

	delete(cache.Entries, cache.ReturnMaskedIP(replacedEntry.FiveTuple.DstIP))

	var newEntry fullAssociativeLRUCacheEntry
	if cache.debugMode {

		// デバッグモードの場合、ルーティングテーブルを参照してエントリを作成する
		maskDstIP := cache.ReturnMaskedIP(f.DstIP)
		_, item := cache.routingTable.SearchLongestIP(ipaddress.NewIPaddress(maskDstIP), int(cache.Refbits))

		newEntry = fullAssociativeLRUCacheEntry{
			FiveTuple: *f,
			NextHop:   item.(routingtable.Data).NextHop,
		}
	} else {
		newEntry = fullAssociativeLRUCacheEntry{
			FiveTuple: *f,
		}
	}

	newElem := cache.evictList.PushFront(newEntry)
	cache.Entries[cache.ReturnMaskedIP(f.DstIP)] = newElem

	cache.AssertImmutableCondition()

	if replacedEntry.FiveTuple == (FiveTuple{}) {
		return evictedFiveTuples
	}

	evictedFiveTuples = append(evictedFiveTuples, &replacedEntry.FiveTuple)

	return evictedFiveTuples
}

// InvalidateFiveTuple は、指定された FiveTuple をキャッシュから削除します。
// 削除が成功すると、キャッシュの整合性が再確認されます。
func (cache *FullAssociativeDstipNbitLRUCache) InvalidateFiveTuple(f *FiveTuple) {
	hitElem, hit := cache.Entries[cache.ReturnMaskedIP(f.DstIP)]

	if !hit {
		panic("entry not cached")
	}

	cache.evictList.Remove(hitElem)
	delete(cache.Entries, cache.ReturnMaskedIP((f.DstIP)))

	cache.evictList.PushBack(fullAssociativeLRUCacheEntry{})

	cache.AssertImmutableCondition()
}

// Clear は、キャッシュをクリアします。
// 現在は未実装で、呼び出されるとパニックを発生させます。
func (cache *FullAssociativeDstipNbitLRUCache) Clear() {
	panic("Not implemented")
}

// Description は、キャッシュの説明文字列を返します。
func (cache *FullAssociativeDstipNbitLRUCache) Description() string {
	return "FullAssociativeDstipNbitLRUCache"
}

// ParameterString は、キャッシュのパラメータをJSON形式の文字列として返します。
func (cache *FullAssociativeDstipNbitLRUCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Size\": %d, \"Refbits\": %d}", cache.Description(), cache.Size, cache.Refbits)
}

// NewFullAssociativeDstipNbitLRUCache は、新しい FullAssociativeDstipNbitLRUCache を作成します。
// refbits は参照ビットの数、size はキャッシュのサイズを指定します。
func NewFullAssociativeDstipNbitLRUCache(refbits uint, size uint, routingTable *routingtable.RoutingTablePatriciaTrie, debugMode bool) *FullAssociativeDstipNbitLRUCache {
	evictList := list.New()

	for i := 0; i < int(size); i++ {
		evictList.PushBack(fullAssociativeLRUCacheEntry{})
	}

	return &FullAssociativeDstipNbitLRUCache{
		Entries:      map[uint32]*list.Element{},
		Size:         size,
		Refbits:      refbits,
		evictList:    evictList,
		routingTable: routingTable,
		debugMode:    debugMode,
	}
}
