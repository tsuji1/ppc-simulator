package cache

import (
	"bytes"
	"encoding/binary"
	"fmt"

	"hash/crc32"
)

type NWaySetAssociativeDstipNbitLRUCache struct {
	Sets []FullAssociativeDstipNbitLRUCache // len(Sets) = Size / Way, each size == Way
	Way  uint
	Size uint
	Refbits uint
}

func returnMaskedIP(IP uint32, refbits uint) uint32 {
	temp := IP
	temp = temp>>(32-refbits)
	temp = temp<<(32-refbits)
	return temp
}

func fiveTupleDstipNbitToBigEndianByteArray(f *FiveTuple, refbits uint) []byte {
	var buf bytes.Buffer
	binary.Write(&buf, binary.BigEndian, returnMaskedIP(f.DstIP, refbits))
	return buf.Bytes()
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) StatString() string {
	return ""
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) setIdxFromFiveTuple(f *FiveTuple) uint {
	maxSetIdx := cache.Size / cache.Way
	crc := crc32.ChecksumIEEE(fiveTupleDstipNbitToBigEndianByteArray(f, cache.Refbits))
	return uint(crc) % maxSetIdx
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	setIdx := cache.setIdxFromFiveTuple(f)
	return cache.Sets[setIdx].IsCachedWithFiveTuple(f, update) // TODO: return meaningful value
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	setIdx := cache.setIdxFromFiveTuple(f)
	return cache.Sets[setIdx].CacheFiveTuple(f)
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) InvalidateFiveTuple(f *FiveTuple) {
	setIdx := cache.setIdxFromFiveTuple(f)
	cache.Sets[setIdx].InvalidateFiveTuple(f)
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) Clear() {
	panic("Not implemented")
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) Description() string {
	return "NWaySetAssociativeDstipNbitLRUCache"
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Way\": %d, \"Size\": %d}", cache.Description(), cache.Way, cache.Size)
}

func NewNWaySetAssociativeDstipNbitLRUCache(refbits, size, way uint) *NWaySetAssociativeDstipNbitLRUCache {
	if size%way != 0 {
		panic("Size must be multiplier of way")
	}

	sets_size := size / way
	sets := make([]FullAssociativeDstipNbitLRUCache, sets_size)

	for i := uint(0); i < sets_size; i++ {
		sets[i] = *NewFullAssociativeDstipNbitLRUCache(refbits, way)
	}

	return &NWaySetAssociativeDstipNbitLRUCache{
		Sets: sets,
		Way:  way,
		Size: size,
		Refbits: refbits,
	}
}
