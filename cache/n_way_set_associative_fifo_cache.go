package cache

import (
	"fmt"
)

type NWaySetAssociativeFIFOCache struct {
	Sets []FullAssociativeFIFOCache // len(Sets) = Size / Way, each size == Way
	Way  uint
	Size uint
}

func (cache *NWaySetAssociativeFIFOCache) StatString() string {
	return ""
}

func (cache *NWaySetAssociativeFIFOCache) Stat() interface{} {
	return struct{}{}
}

func (cache *NWaySetAssociativeFIFOCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *NWaySetAssociativeFIFOCache) setIdxFromFiveTuple(f *FiveTuple) uint {
	maxSetIdx := cache.Size / cache.Way
	idx := (uint(f.SrcIP) ^ uint(f.DstIP)) % maxSetIdx
	return uint(idx)
}

func (cache *NWaySetAssociativeFIFOCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	setIdx := cache.setIdxFromFiveTuple(f)
	return cache.Sets[setIdx].IsCachedWithFiveTuple(f, update) // TODO: return meaningful value
}

func (cache *NWaySetAssociativeFIFOCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	setIdx := cache.setIdxFromFiveTuple(f)
	return cache.Sets[setIdx].CacheFiveTuple(f)
}

func (cache *NWaySetAssociativeFIFOCache) InvalidateFiveTuple(f *FiveTuple) {
	setIdx := cache.setIdxFromFiveTuple(f)
	cache.Sets[setIdx].InvalidateFiveTuple(f)
}

func (cache *NWaySetAssociativeFIFOCache) Clear() {
	panic("Not implemented")
}

func (cache *NWaySetAssociativeFIFOCache) Description() string {
	return "NWaySetAssociativeFIFOCache"
}

func (cache *NWaySetAssociativeFIFOCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Way\": %d, \"Size\": %d}", cache.Description(), cache.Way, cache.Size)
}

func (cache *NWaySetAssociativeFIFOCache) Parameter() Parameter {
	return &SetAssociativeParameter{
		Type: cache.Description(),
		Way:  cache.Way,
		Size: cache.Size,
	}
}

func NewNWaySetAssociativeFIFOCache(size, way uint) *NWaySetAssociativeFIFOCache {
	if size%way != 0 {
		panic("Size must be multiplier of way")
	}

	sets_size := size / way
	sets := make([]FullAssociativeFIFOCache, sets_size)

	for i := uint(0); i < sets_size; i++ {
		sets[i] = *NewFullAssociativeFIFOCache(way)
	}

	return &NWaySetAssociativeFIFOCache{
		Sets: sets,
		Way:  way,
		Size: size,
	}
}
