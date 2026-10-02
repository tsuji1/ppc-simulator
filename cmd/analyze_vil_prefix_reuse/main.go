package main

import (
	"encoding/csv"
	"encoding/gob"
	"flag"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"test-module/cache"
)

type prefixKey struct {
	Length  uint8
	Network uint32
}

type prefixStats struct {
	Packets      uint64
	DstIPs       map[uint32]uint64
	ExactKeys    map[prefixKey]uint64
	LeafPackets  [33]uint64
	LeafKeys     [33]map[uint32]uint64
	FirstPacket  uint64
	LastPacket   uint64
	ActiveWindow uint64
}

type leafSummary struct {
	Length                    int
	Packets                   uint64
	UniqueDstIPs              uint64
	UniquePrefixes            uint64
	PacketShare               float64
	ColdMissRateDstIP         float64
	ColdMissRatePrefix        float64
	CrossIPColdMissSavings    uint64
	CrossIPColdMissSavingsPct float64
}

type bucketRow struct {
	Prefix18            uint32
	Packets             uint64
	UniqueDstIPs        int
	ExactKeys           int
	LeafLengths         int
	Leaf18Packets       uint64
	Leaf19Packets       uint64
	Leaf20To24Packets   uint64
	LeafAbove24Packets  uint64
	MoreSpecificPackets uint64
	MoreSpecificShare   float64
	ExactKeysOverWay    bool
	ActiveWindowPackets uint64
	PacketsPerExactKey  float64
	DstIPsPerExactKey   float64
}

var (
	gobPath   = flag.String("gob", "", "gob file containing []cache.MinPacket")
	maxPacket = flag.Uint64("max", 10_000_000, "maximum packets to analyze; 0 means all")
	minTag    = flag.Int("min-tag", 9, "minimum UnifiedCache tag length")
	maxTag    = flag.Int("max-tag", 24, "maximum UnifiedCache tag length")
	way       = flag.Int("way", 8, "set associativity used for overload classification")
	outputDir = flag.String("output-dir", "scripts/reports/vil_prefix_reuse", "output directory")
)

func main() {
	flag.Parse()
	if *gobPath == "" {
		fatalf("-gob is required")
	}
	if *minTag < 0 || *minTag > 31 || *maxTag < *minTag || *maxTag > 31 {
		fatalf("invalid tag range %d..%d", *minTag, *maxTag)
	}
	if *way <= 0 {
		fatalf("-way must be positive")
	}

	packets := decodePackets(*gobPath)
	limit := uint64(len(packets))
	if *maxPacket > 0 && *maxPacket < limit {
		limit = *maxPacket
	}

	buckets := make(map[uint32]*prefixStats)
	leafDstIPs := [33]map[uint32]uint64{}
	leafPrefixes := [33]map[uint32]uint64{}
	var validPackets uint64
	var cacheablePackets uint64
	var rejectedAboveMax uint64

	for packetIndex := uint64(0); packetIndex < limit; packetIndex++ {
		packet := packets[packetIndex]
		if packet.FiveTuple() == nil {
			continue
		}
		leafLength := int(packet.IsLeafIndex)
		if leafLength < 0 || leafLength > 32 {
			continue
		}
		validPackets++

		bucket := packet.DstIP >> 14
		stats := buckets[bucket]
		if stats == nil {
			stats = &prefixStats{
				DstIPs:       make(map[uint32]uint64),
				ExactKeys:    make(map[prefixKey]uint64),
				FirstPacket:  packetIndex,
				LastPacket:   packetIndex,
				ActiveWindow: 1,
			}
			buckets[bucket] = stats
		}
		stats.Packets++
		stats.DstIPs[packet.DstIP]++
		stats.LeafPackets[leafLength]++
		stats.LastPacket = packetIndex
		stats.ActiveWindow = stats.LastPacket - stats.FirstPacket + 1

		if leafDstIPs[leafLength] == nil {
			leafDstIPs[leafLength] = make(map[uint32]uint64)
		}
		leafDstIPs[leafLength][packet.DstIP]++
		if leafPrefixes[leafLength] == nil {
			leafPrefixes[leafLength] = make(map[uint32]uint64)
		}
		leafPrefixes[leafLength][networkAtLength(packet.DstIP, leafLength)]++

		effectiveLength, ok := effectiveTagLength(leafLength, *minTag, *maxTag)
		if !ok {
			if leafLength > *maxTag {
				rejectedAboveMax++
			}
			continue
		}
		cacheablePackets++
		network := packet.DstIP >> (32 - effectiveLength)
		key := prefixKey{Length: uint8(effectiveLength), Network: network}
		stats.ExactKeys[key]++
		if stats.LeafKeys[leafLength] == nil {
			stats.LeafKeys[leafLength] = make(map[uint32]uint64)
		}
		stats.LeafKeys[leafLength][network]++
	}

	leafRows := buildLeafRows(validPackets, leafDstIPs, leafPrefixes)
	bucketRows := buildBucketRows(buckets, *way)
	if err := os.MkdirAll(*outputDir, 0o755); err != nil {
		fatalf("create output directory: %v", err)
	}
	writeLeafCSV(filepath.Join(*outputDir, "leaf_prefix_reuse.csv"), leafRows)
	writeBucketCSV(filepath.Join(*outputDir, "prefix18_bucket_fragmentation.csv"), bucketRows)
	writeReport(
		filepath.Join(*outputDir, "REPORT.md"),
		limit,
		validPackets,
		cacheablePackets,
		rejectedAboveMax,
		leafRows,
		bucketRows,
	)
	fmt.Printf("Saved report directory: %s\n", *outputDir)
	fmt.Printf("decoded packets: %d, analyzed: %d, valid TCP/UDP: %d\n", len(packets), limit, validPackets)
}

func decodePackets(path string) []cache.MinPacket {
	file, err := os.Open(path)
	if err != nil {
		fatalf("open gob: %v", err)
	}
	defer file.Close()
	var packets []cache.MinPacket
	if err := gob.NewDecoder(file).Decode(&packets); err != nil {
		fatalf("decode gob: %v", err)
	}
	return packets
}

func effectiveTagLength(leafLength, minLength, maxLength int) (int, bool) {
	if leafLength < 0 || leafLength >= 32 {
		return 0, false
	}
	if leafLength > maxLength {
		return 0, false
	}
	if leafLength < minLength {
		return minLength, true
	}
	return leafLength, true
}

func networkAtLength(dstIP uint32, length int) uint32 {
	switch {
	case length <= 0:
		return 0
	case length >= 32:
		return dstIP
	default:
		return dstIP >> (32 - length)
	}
}

func buildLeafRows(
	totalPackets uint64,
	dstIPs [33]map[uint32]uint64,
	prefixes [33]map[uint32]uint64,
) []leafSummary {
	rows := make([]leafSummary, 0, 33)
	for length := 0; length <= 32; length++ {
		var packets uint64
		for _, count := range dstIPs[length] {
			packets += count
		}
		if packets == 0 {
			continue
		}
		uniqueIPs := uint64(len(dstIPs[length]))
		uniquePrefixes := uint64(len(prefixes[length]))
		savings := uint64(0)
		if uniqueIPs > uniquePrefixes {
			savings = uniqueIPs - uniquePrefixes
		}
		rows = append(rows, leafSummary{
			Length:                    length,
			Packets:                   packets,
			UniqueDstIPs:              uniqueIPs,
			UniquePrefixes:            uniquePrefixes,
			PacketShare:               percent(packets, totalPackets),
			ColdMissRateDstIP:         percent(uniqueIPs, packets),
			ColdMissRatePrefix:        percent(uniquePrefixes, packets),
			CrossIPColdMissSavings:    savings,
			CrossIPColdMissSavingsPct: percent(savings, uniqueIPs),
		})
	}
	return rows
}

func buildBucketRows(buckets map[uint32]*prefixStats, way int) []bucketRow {
	rows := make([]bucketRow, 0, len(buckets))
	for prefix18, stats := range buckets {
		leafLengths := 0
		for length := 0; length <= 32; length++ {
			if stats.LeafPackets[length] > 0 {
				leafLengths++
			}
		}
		var leaf20To24 uint64
		for length := 20; length <= 24; length++ {
			leaf20To24 += stats.LeafPackets[length]
		}
		var leafAbove24 uint64
		for length := 25; length <= 32; length++ {
			leafAbove24 += stats.LeafPackets[length]
		}
		var moreSpecific uint64
		for length := 19; length <= 32; length++ {
			moreSpecific += stats.LeafPackets[length]
		}
		exactKeyCount := len(stats.ExactKeys)
		rows = append(rows, bucketRow{
			Prefix18:            prefix18,
			Packets:             stats.Packets,
			UniqueDstIPs:        len(stats.DstIPs),
			ExactKeys:           exactKeyCount,
			LeafLengths:         leafLengths,
			Leaf18Packets:       stats.LeafPackets[18],
			Leaf19Packets:       stats.LeafPackets[19],
			Leaf20To24Packets:   leaf20To24,
			LeafAbove24Packets:  leafAbove24,
			MoreSpecificPackets: moreSpecific,
			MoreSpecificShare:   percent(moreSpecific, stats.Packets),
			ExactKeysOverWay:    exactKeyCount > way,
			ActiveWindowPackets: stats.ActiveWindow,
			PacketsPerExactKey:  ratio(stats.Packets, uint64(exactKeyCount)),
			DstIPsPerExactKey:   ratio(uint64(len(stats.DstIPs)), uint64(exactKeyCount)),
		})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Packets != rows[j].Packets {
			return rows[i].Packets > rows[j].Packets
		}
		return rows[i].Prefix18 < rows[j].Prefix18
	})
	return rows
}

func writeLeafCSV(path string, rows []leafSummary) {
	file := create(path)
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	must(writer.Write([]string{
		"leaf_length", "packets", "packet_share_percent", "unique_dst_ips",
		"unique_cache_prefixes", "dst_ip_cold_miss_rate_percent",
		"prefix_cold_miss_rate_percent", "cross_ip_cold_miss_savings",
		"cross_ip_cold_miss_savings_percent_of_unique_ips",
	}))
	for _, row := range rows {
		must(writer.Write([]string{
			strconv.Itoa(row.Length),
			strconv.FormatUint(row.Packets, 10),
			formatFloat(row.PacketShare),
			strconv.FormatUint(row.UniqueDstIPs, 10),
			strconv.FormatUint(row.UniquePrefixes, 10),
			formatFloat(row.ColdMissRateDstIP),
			formatFloat(row.ColdMissRatePrefix),
			strconv.FormatUint(row.CrossIPColdMissSavings, 10),
			formatFloat(row.CrossIPColdMissSavingsPct),
		}))
	}
}

func writeBucketCSV(path string, rows []bucketRow) {
	file := create(path)
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	must(writer.Write([]string{
		"prefix18", "packets", "unique_dst_ips", "exact_variable_keys",
		"leaf_lengths", "leaf18_packets", "leaf19_packets", "leaf20_24_packets",
		"leaf_above24_packets", "more_specific_packets", "more_specific_share_percent",
		"exact_keys_over_way", "active_window_packets", "packets_per_exact_key",
		"dst_ips_per_exact_key",
	}))
	for _, row := range rows {
		must(writer.Write([]string{
			prefixString(row.Prefix18, 18),
			strconv.FormatUint(row.Packets, 10),
			strconv.Itoa(row.UniqueDstIPs),
			strconv.Itoa(row.ExactKeys),
			strconv.Itoa(row.LeafLengths),
			strconv.FormatUint(row.Leaf18Packets, 10),
			strconv.FormatUint(row.Leaf19Packets, 10),
			strconv.FormatUint(row.Leaf20To24Packets, 10),
			strconv.FormatUint(row.LeafAbove24Packets, 10),
			strconv.FormatUint(row.MoreSpecificPackets, 10),
			formatFloat(row.MoreSpecificShare),
			strconv.FormatBool(row.ExactKeysOverWay),
			strconv.FormatUint(row.ActiveWindowPackets, 10),
			formatFloat(row.PacketsPerExactKey),
			formatFloat(row.DstIPsPerExactKey),
		}))
	}
}

func writeReport(
	path string,
	analyzed uint64,
	valid uint64,
	cacheable uint64,
	rejected uint64,
	leafRows []leafSummary,
	bucketRows []bucketRow,
) {
	var overloadedBuckets uint64
	var overloadedPackets uint64
	var totalBucketPackets uint64
	var moreSpecificPackets uint64
	var leaf18, leaf19 *leafSummary
	for index := range leafRows {
		row := &leafRows[index]
		if row.Length == 18 {
			leaf18 = row
		}
		if row.Length == 19 {
			leaf19 = row
		}
	}
	for _, row := range bucketRows {
		totalBucketPackets += row.Packets
		moreSpecificPackets += row.MoreSpecificPackets
		if row.ExactKeysOverWay {
			overloadedBuckets++
			overloadedPackets += row.Packets
		}
	}

	var builder strings.Builder
	fmt.Fprintf(&builder, "# VIL prefix reuse analysis\n\n")
	fmt.Fprintf(&builder, "- source gob: `%s`\n", *gobPath)
	fmt.Fprintf(&builder, "- analyzed records: %d\n", analyzed)
	fmt.Fprintf(&builder, "- valid TCP/UDP packets: %d\n", valid)
	fmt.Fprintf(&builder, "- exclusive tag range: /%d../%d\n", *minTag, *maxTag)
	fmt.Fprintf(&builder, "- cacheable packets by leaf length: %d (%.6f%%)\n", cacheable, percent(cacheable, valid))
	fmt.Fprintf(&builder, "- rejected because LPM leaf is finer than /%d: %d (%.6f%%)\n\n", *maxTag, rejected, percent(rejected, valid))

	fmt.Fprintf(&builder, "## Exact /18 and /19 cross-IP reuse\n\n")
	fmt.Fprintf(&builder, "| leaf | packets | unique dst IPs | unique cache prefixes | cold misses saved by cross-IP sharing | savings / unique IP |\n")
	fmt.Fprintf(&builder, "|---:|---:|---:|---:|---:|---:|\n")
	for _, row := range []*leafSummary{leaf18, leaf19} {
		if row == nil {
			continue
		}
		fmt.Fprintf(
			&builder,
			"| /%d | %d | %d | %d | %d | %.6f%% |\n",
			row.Length,
			row.Packets,
			row.UniqueDstIPs,
			row.UniquePrefixes,
			row.CrossIPColdMissSavings,
			row.CrossIPColdMissSavingsPct,
		)
	}

	fmt.Fprintf(&builder, "\n## /18 bucket fragmentation\n\n")
	fmt.Fprintf(&builder, "- active /18 buckets: %d\n", len(bucketRows))
	fmt.Fprintf(&builder, "- packets whose LPM result is finer than /18: %d (%.6f%%)\n", moreSpecificPackets, percent(moreSpecificPackets, totalBucketPackets))
	fmt.Fprintf(
		&builder,
		"- active /18 buckets with more than %d distinct variable-length keys: %d (%.6f%% of buckets), carrying %d packets (%.6f%% of packets)\n\n",
		*way,
		overloadedBuckets,
		percent(overloadedBuckets, uint64(len(bucketRows))),
		overloadedPackets,
		percent(overloadedPackets, totalBucketPackets),
	)

	fmt.Fprintf(&builder, "## Hottest /18 buckets\n\n")
	fmt.Fprintf(&builder, "| /18 bucket | packets | unique IPs | exact variable keys | >%d keys | finer-than-/18 share |\n", *way)
	fmt.Fprintf(&builder, "|---|---:|---:|---:|---:|---:|\n")
	top := 20
	if len(bucketRows) < top {
		top = len(bucketRows)
	}
	for _, row := range bucketRows[:top] {
		fmt.Fprintf(
			&builder,
			"| %s | %d | %d | %d | %t | %.6f%% |\n",
			prefixString(row.Prefix18, 18),
			row.Packets,
			row.UniqueDstIPs,
			row.ExactKeys,
			row.ExactKeysOverWay,
			row.MoreSpecificShare,
		)
	}

	fmt.Fprintf(&builder, "\n## Interpretation guardrail\n\n")
	fmt.Fprintf(
		&builder,
		"`cross_ip_cold_miss_savings` is the cold-miss reduction from using the exact LPM prefix instead of /32 for packets with that leaf length. "+
			"It is an upper-bound locality indicator, not the measured finite-cache hit-rate gain. "+
			"Different exact LPM prefixes inside one /18 are kept separate because merging them may change the forwarding result.\n",
	)
	must(os.WriteFile(path, []byte(builder.String()), 0o644))
}

func prefixString(network uint32, length int) string {
	ip := make(net.IP, 4)
	value := network << (32 - length)
	ip[0] = byte(value >> 24)
	ip[1] = byte(value >> 16)
	ip[2] = byte(value >> 8)
	ip[3] = byte(value)
	return fmt.Sprintf("%s/%d", ip.String(), length)
}

func percent(numerator, denominator uint64) float64 {
	if denominator == 0 {
		return 0
	}
	return float64(numerator) / float64(denominator) * 100
}

func ratio(numerator, denominator uint64) float64 {
	if denominator == 0 {
		return 0
	}
	return float64(numerator) / float64(denominator)
}

func formatFloat(value float64) string {
	return strconv.FormatFloat(value, 'f', 6, 64)
}

func create(path string) *os.File {
	file, err := os.Create(path)
	if err != nil {
		fatalf("create %s: %v", path, err)
	}
	return file
}

func must(err error) {
	if err != nil {
		fatalf("%v", err)
	}
}

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
