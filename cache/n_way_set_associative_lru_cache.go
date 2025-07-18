package cache

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"os"
	"test-module/ipaddress"
	"test-module/routingtable"
)

type NWaySetAssociativeLRUCache struct {
	Sets         []FullAssociativeLRUCache // len(Sets) = Size / Way, each size == Way
	Way          uint
	Size         uint
	DepthSum     uint64
	RoutingTable routingtable.RoutingTablePatriciaTrie
}

func (cache *NWaySetAssociativeLRUCache) StatString() string {
	return fmt.Sprintf("%v", cache.DepthSum)
}

type NWaySetAssociativeLRUCacheStat struct {
	DepthSum uint64
}

func (cache *NWaySetAssociativeLRUCache) Stat() interface{} {
	return NWaySetAssociativeLRUCacheStat{
		DepthSum: cache.DepthSum,
	}
}

func (cache *NWaySetAssociativeLRUCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func fiveTupleToBigEndianByteArray(f *FiveTuple) []byte { //無視できないくらい遅いのでコメントアウト

	var buf bytes.Buffer
	binary.Write(&buf, binary.BigEndian, *f)
	return buf.Bytes()
}
func (cache *NWaySetAssociativeLRUCache) setIdxFromFiveTuple(f *FiveTuple) uint {
	maxSetIdx := cache.Size / cache.Way
	idx := binary.BigEndian.Uint32(fiveTupleToBigEndianByteArray(f)) % uint32(maxSetIdx)
	return uint(idx)
}

func (cache *NWaySetAssociativeLRUCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	setIdx := cache.setIdxFromFiveTuple(f)
	return cache.Sets[setIdx].IsCachedWithFiveTuple(f, update) // TODO: return meaningful value
}

func (cache *NWaySetAssociativeLRUCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	setIdx := cache.setIdxFromFiveTuple(f)

	_, prefix_item := cache.RoutingTable.SearchLongestIP(ipaddress.NewIPaddress(f.DstIP), 32)
	cache.DepthSum += prefix_item.(routingtable.Data).Depth

	return cache.Sets[setIdx].CacheFiveTuple(f)
}

func (cache *NWaySetAssociativeLRUCache) InvalidateFiveTuple(f *FiveTuple) {
	setIdx := cache.setIdxFromFiveTuple(f)
	cache.Sets[setIdx].InvalidateFiveTuple(f)
}

func (cache *NWaySetAssociativeLRUCache) Clear() {
	panic("Not implemented")
}

func (cache *NWaySetAssociativeLRUCache) Description() string {
	return "NWaySetAssociativeLRUCache"
}

func (cache *NWaySetAssociativeLRUCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Way\": %d, \"Size\": %d, \"DepthSum\": %d}", cache.Description(), cache.Way, cache.Size, cache.DepthSum)
}

func (cache *NWaySetAssociativeLRUCache) Parameter() Parameter {
	return &SetAssociativeParameter{
		Type: cache.Description(),
		Way:  cache.Way,
		Size: cache.Size,
	}
}

func NewNWaySetAssociativeLRUCache(size, way uint) *NWaySetAssociativeLRUCache {
	if size%way != 0 {
		panic("Size must be multiplier of way")
	}

	sets_size := size / way
	sets := make([]FullAssociativeLRUCache, sets_size)

	for i := uint(0); i < sets_size; i++ {
		sets[i] = *NewFullAssociativeLRUCache(way)
	}
	fp, err := os.Open("rules/wide.rib.20240625.1400.rule")
	if err != nil {
		panic(err)
	}
	defer fp.Close()

	routingtable := routingtable.NewRoutingTablePatriciaTrie()
	routingtable.ReadRule(fp)

	return &NWaySetAssociativeLRUCache{
		Sets:         sets,
		Way:          way,
		Size:         size,
		RoutingTable: *routingtable,
	}
}
