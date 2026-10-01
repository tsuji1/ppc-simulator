// Command export_crc16_raw16_set_distribution counts Chicago trace accesses per
// UnifiedCache set for CRC32(/16) and direct /16 indexing.
//
// Dynamic counts every packet, static IP counts every distinct destination
// IPv4 address exactly once, and static prefix counts every distinct /16 index
// input exactly once. The input is the simulator's decoded MinPacket GOB, so
// the population is identical to the packets supplied to a simulation.
package main

import (
	"encoding/csv"
	"encoding/gob"
	"flag"
	"fmt"
	"hash/crc32"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"test-module/cache"
)

var (
	gobPath               = flag.String("gob", "", "GOB file containing []cache.MinPacket")
	setCount              = flag.Uint("sets", 128, "number of cache sets")
	maxCount              = flag.Uint64("max", 0, "maximum packets to count; 0 means all")
	tagMin                = flag.Int("tag-min", 9, "minimum cacheable prefix length")
	tagMax                = flag.Int("tag-max", 24, "maximum cacheable prefix length")
	output                = flag.String("output", "", "output CSV path")
	prefixBreakdownOutput = flag.String(
		"prefix-breakdown-output",
		"",
		"optional per-/16 packet and unique-destination-IP CSV path",
	)
)

type cachePrefixKey struct {
	length  int8
	network uint32
}

func main() {
	flag.Parse()
	if *gobPath == "" {
		fatalf("-gob is required")
	}
	if *output == "" {
		fatalf("-output is required")
	}
	if *setCount == 0 || *setCount&(*setCount-1) != 0 {
		fatalf("-sets must be a positive power of two")
	}
	if *tagMin < 0 || *tagMax >= 32 || *tagMin > *tagMax {
		fatalf("tag range must satisfy 0 <= tag-min <= tag-max < 32")
	}

	packets := decodePackets(*gobPath)
	limit := uint64(len(packets))
	if *maxCount > 0 && *maxCount < limit {
		limit = *maxCount
	}

	dynamicCRC := make([]uint64, *setCount)
	dynamicRaw := make([]uint64, *setCount)
	cacheableDynamicCRC := make([]uint64, *setCount)
	cacheableDynamicRaw := make([]uint64, *setCount)
	uniqueDstIPs := make(map[uint32]struct{})
	uniquePrefix16s := make(map[uint32]struct{})
	prefix16Packets := make(map[uint32]uint64)
	uniqueCachePrefixes := make(map[cachePrefixKey]struct{})
	uniqueCachePrefixesCRC := make([]map[cachePrefixKey]struct{}, *setCount)
	uniqueCachePrefixesRaw := make([]map[cachePrefixKey]struct{}, *setCount)
	for setID := uint(0); setID < *setCount; setID++ {
		uniqueCachePrefixesCRC[setID] = make(map[cachePrefixKey]struct{})
		uniqueCachePrefixesRaw[setID] = make(map[cachePrefixKey]struct{})
	}
	for i := uint64(0); i < limit; i++ {
		packet := packets[i]
		dstIP := packet.DstIP
		crcSet, rawSet := setIndices(dstIP, *setCount)
		dynamicCRC[crcSet]++
		dynamicRaw[rawSet]++
		uniqueDstIPs[dstIP] = struct{}{}
		prefix16 := dstIP >> 16
		uniquePrefix16s[prefix16] = struct{}{}
		prefix16Packets[prefix16]++

		key, cacheable := cachePrefix(packet, *tagMin, *tagMax)
		if cacheable {
			cacheableDynamicCRC[crcSet]++
			cacheableDynamicRaw[rawSet]++
			uniqueCachePrefixes[key] = struct{}{}
			uniqueCachePrefixesCRC[crcSet][key] = struct{}{}
			uniqueCachePrefixesRaw[rawSet][key] = struct{}{}
		}
	}

	staticCRC := make([]uint64, *setCount)
	staticRaw := make([]uint64, *setCount)
	for dstIP := range uniqueDstIPs {
		crcSet, rawSet := setIndices(dstIP, *setCount)
		staticCRC[crcSet]++
		staticRaw[rawSet]++
	}
	if *prefixBreakdownOutput != "" {
		if err := writePrefixBreakdown(
			*prefixBreakdownOutput,
			uniqueDstIPs,
			prefix16Packets,
			*setCount,
		); err != nil {
			fatalf("write prefix breakdown CSV: %v", err)
		}
	}

	uniquePrefixCRC := make([]uint64, *setCount)
	uniquePrefixRaw := make([]uint64, *setCount)
	for prefix16 := range uniquePrefix16s {
		crcSet, rawSet := setIndices(prefix16<<16, *setCount)
		uniquePrefixCRC[crcSet]++
		uniquePrefixRaw[rawSet]++
	}

	uniqueCachePrefixCRC := make([]uint64, *setCount)
	uniqueCachePrefixRaw := make([]uint64, *setCount)
	for setID := uint(0); setID < *setCount; setID++ {
		uniqueCachePrefixCRC[setID] = uint64(len(uniqueCachePrefixesCRC[setID]))
		uniqueCachePrefixRaw[setID] = uint64(len(uniqueCachePrefixesRaw[setID]))
	}

	if err := writeCSV(
		*output,
		dynamicCRC,
		dynamicRaw,
		staticCRC,
		staticRaw,
		uniquePrefixCRC,
		uniquePrefixRaw,
		cacheableDynamicCRC,
		cacheableDynamicRaw,
		uniqueCachePrefixCRC,
		uniqueCachePrefixRaw,
	); err != nil {
		fatalf("write CSV: %v", err)
	}

	fmt.Printf("decoded_packets=%d\n", len(packets))
	fmt.Printf("counted_packets=%d\n", limit)
	fmt.Printf("unique_destination_ips=%d\n", len(uniqueDstIPs))
	fmt.Printf("unique_destination_prefix16s=%d\n", len(uniquePrefix16s))
	fmt.Printf("unique_cache_prefixes=%d\n", len(uniqueCachePrefixes))
	fmt.Printf("cacheable_packets=%d\n", sumCounts(cacheableDynamicCRC))
	fmt.Printf("tag_range=%d-%d\n", *tagMin, *tagMax)
	fmt.Printf("sets=%d\n", *setCount)
	fmt.Printf("output=%s\n", *output)
	if *prefixBreakdownOutput != "" {
		fmt.Printf("prefix_breakdown_output=%s\n", *prefixBreakdownOutput)
	}
}

func writePrefixBreakdown(
	path string,
	uniqueDstIPs map[uint32]struct{},
	prefix16Packets map[uint32]uint64,
	sets uint,
) error {
	uniqueIPsByPrefix := make(map[uint32]uint64)
	for dstIP := range uniqueDstIPs {
		uniqueIPsByPrefix[dstIP>>16]++
	}
	prefixes := make([]uint32, 0, len(prefix16Packets))
	for prefix16 := range prefix16Packets {
		prefixes = append(prefixes, prefix16)
	}
	sort.Slice(prefixes, func(i int, j int) bool { return prefixes[i] < prefixes[j] })

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	if err := writer.Write([]string{
		"prefix16",
		"network",
		"unique_destination_ips",
		"packets",
		"crc16_set",
		"raw16_set",
	}); err != nil {
		return err
	}
	for _, prefix16 := range prefixes {
		crcSet, rawSet := setIndices(prefix16<<16, sets)
		network := fmt.Sprintf("%d.%d.0.0/16", prefix16>>8, prefix16&0xff)
		if err := writer.Write([]string{
			strconv.FormatUint(uint64(prefix16), 10),
			network,
			strconv.FormatUint(uniqueIPsByPrefix[prefix16], 10),
			strconv.FormatUint(prefix16Packets[prefix16], 10),
			strconv.FormatUint(uint64(crcSet), 10),
			strconv.FormatUint(uint64(rawSet), 10),
		}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func cachePrefix(packet cache.MinPacket, minimum int, maximum int) (cachePrefixKey, bool) {
	leafLength := int(packet.IsLeafIndex)
	if leafLength < 0 || leafLength >= 32 || leafLength > maximum {
		return cachePrefixKey{}, false
	}
	cacheLength := leafLength
	if cacheLength < minimum {
		cacheLength = minimum
	}
	network := packet.DstIP >> (32 - cacheLength)
	return cachePrefixKey{length: int8(cacheLength), network: network}, true
}

func sumCounts(values []uint64) uint64 {
	var total uint64
	for _, value := range values {
		total += value
	}
	return total
}

func decodePackets(path string) []cache.MinPacket {
	file, err := os.Open(path)
	if err != nil {
		fatalf("open GOB: %v", err)
	}
	defer file.Close()

	var packets []cache.MinPacket
	if err := gob.NewDecoder(file).Decode(&packets); err != nil {
		fatalf("decode GOB: %v", err)
	}
	return packets
}

func setIndices(dstIP uint32, sets uint) (uint, uint) {
	prefix16 := dstIP >> 16
	bytes := []byte{
		byte(prefix16 >> 24),
		byte(prefix16 >> 16),
		byte(prefix16 >> 8),
		byte(prefix16),
	}
	crcSet := uint(crc32.ChecksumIEEE(bytes)) % sets
	rawSet := uint(prefix16) & (sets - 1)
	return crcSet, rawSet
}

func writeCSV(
	path string,
	dynamicCRC []uint64,
	dynamicRaw []uint64,
	staticCRC []uint64,
	staticRaw []uint64,
	uniquePrefixCRC []uint64,
	uniquePrefixRaw []uint64,
	cacheableDynamicCRC []uint64,
	cacheableDynamicRaw []uint64,
	uniqueCachePrefixCRC []uint64,
	uniqueCachePrefixRaw []uint64,
) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()
	if err := writer.Write([]string{
		"set_id",
		"dynamic_crc16_packets",
		"dynamic_raw16_packets",
		"static_crc16_unique_ips",
		"static_raw16_unique_ips",
		"static_crc16_unique_prefix16s",
		"static_raw16_unique_prefix16s",
		"cacheable_crc16_packets",
		"cacheable_raw16_packets",
		"static_crc16_unique_cache_prefixes",
		"static_raw16_unique_cache_prefixes",
	}); err != nil {
		return err
	}
	for setID := range dynamicCRC {
		if err := writer.Write([]string{
			strconv.Itoa(setID),
			strconv.FormatUint(dynamicCRC[setID], 10),
			strconv.FormatUint(dynamicRaw[setID], 10),
			strconv.FormatUint(staticCRC[setID], 10),
			strconv.FormatUint(staticRaw[setID], 10),
			strconv.FormatUint(uniquePrefixCRC[setID], 10),
			strconv.FormatUint(uniquePrefixRaw[setID], 10),
			strconv.FormatUint(cacheableDynamicCRC[setID], 10),
			strconv.FormatUint(cacheableDynamicRaw[setID], 10),
			strconv.FormatUint(uniqueCachePrefixCRC[setID], 10),
			strconv.FormatUint(uniqueCachePrefixRaw[setID], 10),
		}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
