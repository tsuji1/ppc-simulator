package cache

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"strings"
	"test-module/routingtable"
)

type NWaySetAssociativeDstipNbitLRUCache struct {
	Sets               []FullAssociativeDstipNbitLRUCache // len(Sets) = Size / Way, each size == Way
	Way                uint
	Size               uint
	Refbits            uint
	routingTable       *routingtable.RoutingTablePatriciaTrie
	debugMode          bool
	ParentCache        Cache
	IndexInParentCache int
	IsFull             bool
	// Index は set index の作り方。空なら CRC32、MPIndexDirect なら key（上位 Refbits bit）の下位 bit。
	// direct では index に使った bit が set の位置で決まるので、tag は Refbits - log2(sets) bit で足りる。
	Index string
}

const (
	MPIndexCRC    = "crc"
	MPIndexDirect = "direct"
)

// NormalizeMPIndex は MP の index 指定を内部表現にする。CRC は従来の結果と一致させるため空文字にする。
func NormalizeMPIndex(index string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(index)) {
	case "", MPIndexCRC:
		return "", nil
	case MPIndexDirect:
		return MPIndexDirect, nil
	default:
		return "", fmt.Errorf("invalid MP index %q (want crc or direct)", index)
	}
}

func returnMaskedIP(IP uint32, refbits uint) uint32 {
	temp := IP
	temp = temp >> (32 - refbits)
	temp = temp << (32 - refbits)
	return temp
}

func fiveTupleDstipNbitToBigEndianByteArray(f *FiveTuple, refbits uint) []byte {
	var buf bytes.Buffer
	binary.Write(&buf, binary.BigEndian, returnMaskedIP(f.DstIP, refbits))
	return buf.Bytes()
}

func uint32ToBytes(ip uint32) []byte {
	return []byte{
		byte(ip >> 24),
		byte(ip >> 16),
		byte(ip >> 8),
		byte(ip),
	}
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) StatString() string {
	return ""
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) Stat() interface{} {
	return struct{}{}
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) IsCached(p *Packet, update bool) (bool, *int) {
	return cache.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) setIdxFromMaskedDstIp(f *FiveTuple) uint {
	maxSetIdx := cache.Size / cache.Way
	if cache.Index == MPIndexDirect {
		key := uint(0)
		if cache.Refbits > 0 {
			key = uint(f.DstIP >> (32 - cache.Refbits))
		}
		return key % maxSetIdx
	}
	dstIP := returnMaskedIP(f.DstIP, cache.Refbits)

	crc := crc32.ChecksumIEEE(uint32ToBytes(dstIP))
	return uint(crc) % maxSetIdx
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	setIdx := cache.setIdxFromMaskedDstIp(f)
	return cache.Sets[setIdx].IsCachedWithFiveTuple(f, update) // TODO: return meaningful value
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	setIdx := cache.setIdxFromMaskedDstIp(f)
	description := cache.ParentCache.Description()
	evictedFiveTuples := cache.Sets[setIdx].CacheFiveTuple(f)

	switch {
	case strings.HasPrefix(description, "MultiLayerCacheInclusive"):
		cache.ParentCache.(*MultiLayerCacheInclusive).CacheInserted[cache.IndexInParentCache] += 1
		cache.ParentCache.(*MultiLayerCacheInclusive).CacheReplacedByLayer[cache.IndexInParentCache] += uint(len(evictedFiveTuples))
		break
	default:
	}

	return evictedFiveTuples
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) InvalidateFiveTuple(f *FiveTuple) {
	setIdx := cache.setIdxFromMaskedDstIp(f)
	cache.Sets[setIdx].InvalidateFiveTuple(f)
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) Clear() {
	panic("Not implemented")
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) Description() string {
	return "NbitNWaySetAssociativeDstipLRUCache"
	// "NWaySetAssociativeDstipNbitLRUCache"
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) ParameterString() string {
	if cache.Index != "" {
		return fmt.Sprintf("{\"Type\": \"%s\", \"Way\": %d, \"Size\": %d , \"Ref\": %d, \"Index\": \"%s\"}", cache.Description(), cache.Way, cache.Size, cache.Refbits, cache.Index)
	}
	return fmt.Sprintf("{\"Type\": \"%s\", \"Way\": %d, \"Size\": %d , \"Ref\": %d}", cache.Description(), cache.Way, cache.Size, cache.Refbits)
}

func (cache *NWaySetAssociativeDstipNbitLRUCache) Parameter() Parameter {
	return &NbitSetAssociativeParameter{
		Type:    cache.Description(),
		Way:     int(cache.Way),
		Size:    int(cache.Size),
		Refbits: int(cache.Refbits),
		Index:   cache.Index,
	}
}
func NewNWaySetAssociativeDstipNbitLRUCache(refbits, size, way uint, routingTable *routingtable.RoutingTablePatriciaTrie, debugMode bool, parentCache Cache, indexInParentCache int) *NWaySetAssociativeDstipNbitLRUCache {
	if size%way != 0 {
		panic("Size must be multiplier of way")
	}

	sets_size := size / way
	sets := make([]FullAssociativeDstipNbitLRUCache, sets_size)

	for i := uint(0); i < sets_size; i++ {
		sets[i] = *NewFullAssociativeDstipNbitLRUCache(refbits, way, routingTable, debugMode)
	}

	return &NWaySetAssociativeDstipNbitLRUCache{
		Sets:               sets,
		Way:                way,
		Size:               size,
		Refbits:            refbits,
		routingTable:       routingTable,
		debugMode:          debugMode,
		ParentCache:        parentCache,
		IndexInParentCache: indexInParentCache,
		IsFull:             false,
	}
}
