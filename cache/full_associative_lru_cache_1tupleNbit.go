package cache

import (
	"container/list"
	"fmt"
)

type FullAssociativeDstipNbitLRUCache struct {
	Entries map[uint32]*list.Element
	Size    uint
	Refbits uint

	evictList *list.List
}

func (cache *FullAssociativeDstipNbitLRUCache) ReturnMaskedIP(IP uint32) uint32 {
	var temp uint32

	temp = IP
	temp = temp >> (32 - cache.Refbits)
	temp = temp << (32 - cache.Refbits)
	return temp
}

func (cache *FullAssociativeDstipNbitLRUCache) StatString() string {
	return ""
}

func (cache *FullAssociativeDstipNbitLRUCache) AssertImmutableCondition() {
	if int(cache.Size) < len(cache.Entries) {
		panic(fmt.Sprintln("len(cache.Entries):", len(cache.Entries), ", expected: less than or equal to", cache.Size))
	}

	if cache.evictList.Len() != int(cache.Size) {
		panic(fmt.Sprintln("cache.evictList.Len():", cache.evictList.Len(), ", expected: ", cache.Size))
	}
}

func (cache *FullAssociativeDstipNbitLRUCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *FullAssociativeDstipNbitLRUCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hitElem, hit := cache.Entries[cache.ReturnMaskedIP(f.DstIP)]

	cache.AssertImmutableCondition()

	if hit && update {
		cache.evictList.MoveToFront(hitElem)

		// update refered count
		hitEntry := hitElem.Value.(fullAssociativeLRUCacheEntry)
		hitElem.Value = fullAssociativeLRUCacheEntry{
			Refered:   hitEntry.Refered + 1,
			FiveTuple: hitEntry.FiveTuple,
		}
	}

	cache.AssertImmutableCondition()

	return hit, nil
}

func (cache *FullAssociativeDstipNbitLRUCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	cache.AssertImmutableCondition()

	evictedFiveTuples := []*FiveTuple{}

	if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
		return evictedFiveTuples
	}

	oldestElem := cache.evictList.Back()

	replacedEntry := cache.evictList.Remove(oldestElem).(fullAssociativeLRUCacheEntry)
	delete(cache.Entries, cache.ReturnMaskedIP(replacedEntry.FiveTuple.DstIP))

	newEntry := fullAssociativeLRUCacheEntry{
		FiveTuple: *f,
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

func (cache *FullAssociativeDstipNbitLRUCache) Clear() {
	panic("Not implemented")
}

func (cache *FullAssociativeDstipNbitLRUCache) Description() string {
	return "FullAssociativeDstipNbitLRUCache"
}

func (cache *FullAssociativeDstipNbitLRUCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Size\": %d, \"Refbits\": %d}", cache.Description(), cache.Size, cache.Refbits)
}

func NewFullAssociativeDstipNbitLRUCache(refbits uint, size uint) *FullAssociativeDstipNbitLRUCache {
	evictList := list.New()

	for i := 0; i < int(size); i++ {
		evictList.PushBack(fullAssociativeLRUCacheEntry{})
	}

	return &FullAssociativeDstipNbitLRUCache{
		Entries:   map[uint32]*list.Element{},
		Size:      size,
		Refbits:   refbits,
		evictList: evictList,
	}
}
