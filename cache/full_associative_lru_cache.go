package cache

import (
	"container/list"
	"fmt"
)

// FullAssociativeLRUCache は完全連想LRUキャッシュを表します。
type FullAssociativeLRUCache struct {
	Entries map[FiveTuple]*list.Element
	Size    uint

	evictList *list.List
}

type fullAssociativeLRUCacheEntry struct {
	Refered   int
	FiveTuple FiveTuple
	NextHop   string
}

// StatString はキャッシュの統計情報を文字列で返します。
func (cache *FullAssociativeLRUCache) StatString() string {
	return ""
}

func (cache *FullAssociativeLRUCache) Stat() interface{} {
	return struct{}{}
}

// AssertImmutableCondition はキャッシュの不変条件をチェックします。
func (cache *FullAssociativeLRUCache) AssertImmutableCondition() {
	if int(cache.Size) < len(cache.Entries) {
		panic(fmt.Sprintln("len(cache.Entries):", len(cache.Entries), ", expected: less than or equal to", cache.Size))
	}

	if cache.evictList.Len() != int(cache.Size) {
		panic(fmt.Sprintln("cache.evictList.Len():", cache.evictList.Len(), ", expected: ", cache.Size))
	}
}

// IsCached はパケットがキャッシュにあるかをチェックし、オプションでLRUリスト内の位置を更新します。
func (cache *FullAssociativeLRUCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

// IsCachedWithFiveTuple はFiveTupleがキャッシュにあるかをチェックし、オプションでLRUリスト内の位置を更新します。
func (cache *FullAssociativeLRUCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hitElem, hit := cache.Entries[*f]

	cache.AssertImmutableCondition()

	if hit && update {
		cache.evictList.MoveToFront(hitElem)

		// 参照カウントを更新
		hitEntry := hitElem.Value.(fullAssociativeLRUCacheEntry)
		hitElem.Value = fullAssociativeLRUCacheEntry{
			Refered:   hitEntry.Refered + 1,
			FiveTuple: hitEntry.FiveTuple,
		}
	}

	cache.AssertImmutableCondition()

	return hit, nil
}

// CacheFiveTuple はFiveTupleをキャッシュに追加し、必要に応じて最も最近使用されていないエントリを削除します。
func (cache *FullAssociativeLRUCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	cache.AssertImmutableCondition()

	evictedFiveTuples := []*FiveTuple{}

	if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
		return evictedFiveTuples
	}

	oldestElem := cache.evictList.Back()

	replacedEntry := cache.evictList.Remove(oldestElem).(fullAssociativeLRUCacheEntry)
	delete(cache.Entries, replacedEntry.FiveTuple)

	newEntry := fullAssociativeLRUCacheEntry{
		FiveTuple: *f,
	}

	newElem := cache.evictList.PushFront(newEntry)
	cache.Entries[*f] = newElem

	cache.AssertImmutableCondition()

	if replacedEntry.FiveTuple == (FiveTuple{}) {
		return evictedFiveTuples
	}

	evictedFiveTuples = append(evictedFiveTuples, &replacedEntry.FiveTuple)

	return evictedFiveTuples
}

// InvalidateFiveTuple はキャッシュからFiveTupleを削除します。
func (cache *FullAssociativeLRUCache) InvalidateFiveTuple(f *FiveTuple) {
	hitElem, hit := cache.Entries[*f]

	if !hit {
		panic("entry not cached")
	}

	cache.evictList.Remove(hitElem)
	delete(cache.Entries, *f)

	cache.evictList.PushBack(fullAssociativeLRUCacheEntry{})

	cache.AssertImmutableCondition()
}

// Clear はキャッシュからすべてのエントリを削除します。
func (cache *FullAssociativeLRUCache) Clear() {
	panic("未実装")
}

// Description はキャッシュの文字列表現を返します。
func (cache *FullAssociativeLRUCache) Description() string {
	return "FullAssociativeLRUCache"
}

// ParameterString はキャッシュのパラメータを文字列で返します。
func (cache *FullAssociativeLRUCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Size\": %d}", cache.Description(), cache.Size)
}

// NewFullAssociativeLRUCache は指定されたサイズの新しいFullAssociativeLRUCacheを作成します。
func NewFullAssociativeLRUCache(size uint) *FullAssociativeLRUCache {
	evictList := list.New()

	for i := 0; i < int(size); i++ {
		evictList.PushBack(fullAssociativeLRUCacheEntry{})
	}

	return &FullAssociativeLRUCache{
		Entries:   map[FiveTuple]*list.Element{},
		Size:      size,
		evictList: evictList,
	}
}
func (c *FullAssociativeLRUCache) Parameter() Parameter {
	return &FullAssociativeParameter{
		Type: c.Description(),
		Size: c.Size,
	}
}
