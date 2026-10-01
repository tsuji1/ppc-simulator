// Command analyze_prefix16_traffic explains unusually large unique-destination
// counts inside one destination /16 in the simulator MinPacket population.
package main

import (
	"encoding/binary"
	"encoding/csv"
	"encoding/gob"
	"flag"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strconv"

	"test-module/cache"
)

var (
	gobPath   = flag.String("gob", "", "GOB file containing []cache.MinPacket")
	prefixRaw = flag.String("prefix16", "", "destination /16, e.g. 150.65.0.0")
	maxCount  = flag.Uint64("max", 0, "maximum packets to inspect; 0 means all")
	outputDir = flag.String("output-dir", "", "directory for detail CSVs")
	topCount  = flag.Int("top", 25, "number of top sources and destinations to write")
)

type trafficCount struct {
	packets uint64
	tcp     uint64
	udp     uint64
}

type rankedCount struct {
	ip         uint32
	packets    uint64
	tcp        uint64
	udp        uint64
	uniqueDsts int
}

func main() {
	flag.Parse()
	if *gobPath == "" || *prefixRaw == "" || *outputDir == "" {
		fatalf("-gob, -prefix16, and -output-dir are required")
	}
	if *topCount <= 0 {
		fatalf("-top must be positive")
	}
	prefix16 := parsePrefix16(*prefixRaw)
	packets := decodePackets(*gobPath)
	limit := uint64(len(packets))
	if *maxCount > 0 && *maxCount < limit {
		limit = *maxCount
	}

	sources := make(map[uint32]*trafficCount)
	destinations := make(map[uint32]*trafficCount)
	leafCounts := make(map[int8]uint64)
	var matching uint64
	for i := uint64(0); i < limit; i++ {
		packet := packets[i]
		if packet.DstIP>>16 != prefix16 {
			continue
		}
		matching++
		increment(sources, packet.SrcIP, packet.Proto)
		increment(destinations, packet.DstIP, packet.Proto)
		leafCounts[packet.IsLeafIndex]++
	}

	rankedSources := rankCounts(sources)
	if len(rankedSources) > *topCount {
		rankedSources = rankedSources[:*topCount]
	}
	topSourceDestinations := make(map[uint32]map[uint32]struct{}, len(rankedSources))
	for _, source := range rankedSources {
		topSourceDestinations[source.ip] = make(map[uint32]struct{})
	}
	for i := uint64(0); i < limit; i++ {
		packet := packets[i]
		if packet.DstIP>>16 != prefix16 {
			continue
		}
		if destinationsForSource, ok := topSourceDestinations[packet.SrcIP]; ok {
			destinationsForSource[packet.DstIP] = struct{}{}
		}
	}
	for index := range rankedSources {
		rankedSources[index].uniqueDsts = len(topSourceDestinations[rankedSources[index].ip])
	}

	rankedDestinations := rankCounts(destinations)
	destinationPacketCounts := make([]uint64, 0, len(destinations))
	var singlePacketDestinations int
	for _, count := range destinations {
		destinationPacketCounts = append(destinationPacketCounts, count.packets)
		if count.packets == 1 {
			singlePacketDestinations++
		}
	}
	sort.Slice(destinationPacketCounts, func(i int, j int) bool {
		return destinationPacketCounts[i] < destinationPacketCounts[j]
	})

	if err := os.MkdirAll(*outputDir, 0o755); err != nil {
		fatalf("create output directory: %v", err)
	}
	if err := writeRankedCSV(filepath.Join(*outputDir, "top_sources.csv"), rankedSources, true); err != nil {
		fatalf("write top sources: %v", err)
	}
	if len(rankedDestinations) > *topCount {
		rankedDestinations = rankedDestinations[:*topCount]
	}
	if err := writeRankedCSV(filepath.Join(*outputDir, "top_destinations.csv"), rankedDestinations, false); err != nil {
		fatalf("write top destinations: %v", err)
	}
	if err := writeLeafCSV(filepath.Join(*outputDir, "leaf_lengths.csv"), leafCounts); err != nil {
		fatalf("write leaf lengths: %v", err)
	}

	fmt.Printf("decoded_packets=%d\n", len(packets))
	fmt.Printf("inspected_packets=%d\n", limit)
	fmt.Printf("destination_prefix=%s/16\n", formatPrefix16(prefix16))
	fmt.Printf("matching_packets=%d\n", matching)
	fmt.Printf("unique_destination_ips=%d\n", len(destinations))
	fmt.Printf("missing_destination_ips=%d\n", 1<<16-len(destinations))
	fmt.Printf("unique_source_ips=%d\n", len(sources))
	fmt.Printf("single_packet_destinations=%d\n", singlePacketDestinations)
	fmt.Printf("dst_packets_p50=%d\n", quantile(destinationPacketCounts, 0.50))
	fmt.Printf("dst_packets_p90=%d\n", quantile(destinationPacketCounts, 0.90))
	fmt.Printf("dst_packets_p99=%d\n", quantile(destinationPacketCounts, 0.99))
	if len(rankedSources) > 0 {
		top := rankedSources[0]
		fmt.Printf(
			"top_source=%s packets=%d unique_destinations=%d tcp=%d udp=%d\n",
			formatIP(top.ip),
			top.packets,
			top.uniqueDsts,
			top.tcp,
			top.udp,
		)
	}
	if len(rankedDestinations) > 0 {
		top := rankedDestinations[0]
		fmt.Printf(
			"top_destination=%s packets=%d tcp=%d udp=%d\n",
			formatIP(top.ip),
			top.packets,
			top.tcp,
			top.udp,
		)
	}
}

func parsePrefix16(raw string) uint32 {
	ip := net.ParseIP(raw).To4()
	if ip == nil {
		fatalf("invalid IPv4 address: %s", raw)
	}
	return binary.BigEndian.Uint32(ip) >> 16
}

func formatPrefix16(prefix16 uint32) string {
	return fmt.Sprintf("%d.%d.0.0", prefix16>>8, prefix16&0xff)
}

func formatIP(value uint32) string {
	buffer := make(net.IP, 4)
	binary.BigEndian.PutUint32(buffer, value)
	return buffer.String()
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

func increment(counts map[uint32]*trafficCount, ip uint32, protocol string) {
	count := counts[ip]
	if count == nil {
		count = &trafficCount{}
		counts[ip] = count
	}
	count.packets++
	switch protocol {
	case "tcp":
		count.tcp++
	case "udp":
		count.udp++
	}
}

func rankCounts(counts map[uint32]*trafficCount) []rankedCount {
	rows := make([]rankedCount, 0, len(counts))
	for ip, count := range counts {
		rows = append(rows, rankedCount{
			ip:      ip,
			packets: count.packets,
			tcp:     count.tcp,
			udp:     count.udp,
		})
	}
	sort.Slice(rows, func(i int, j int) bool {
		if rows[i].packets != rows[j].packets {
			return rows[i].packets > rows[j].packets
		}
		return rows[i].ip < rows[j].ip
	})
	return rows
}

func quantile(values []uint64, fraction float64) uint64 {
	if len(values) == 0 {
		return 0
	}
	index := int(fraction * float64(len(values)-1))
	return values[index]
}

func writeRankedCSV(path string, rows []rankedCount, includeUniqueDestinations bool) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	header := []string{"rank", "ip", "packets", "tcp_packets", "udp_packets"}
	if includeUniqueDestinations {
		header = append(header, "unique_destination_ips")
	}
	if err := writer.Write(header); err != nil {
		return err
	}
	for index, row := range rows {
		record := []string{
			strconv.Itoa(index + 1),
			formatIP(row.ip),
			strconv.FormatUint(row.packets, 10),
			strconv.FormatUint(row.tcp, 10),
			strconv.FormatUint(row.udp, 10),
		}
		if includeUniqueDestinations {
			record = append(record, strconv.Itoa(row.uniqueDsts))
		}
		if err := writer.Write(record); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeLeafCSV(path string, counts map[int8]uint64) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	if err := writer.Write([]string{"leaf_length", "packets"}); err != nil {
		return err
	}
	lengths := make([]int, 0, len(counts))
	for length := range counts {
		lengths = append(lengths, int(length))
	}
	sort.Ints(lengths)
	for _, length := range lengths {
		if err := writer.Write([]string{
			strconv.Itoa(length),
			strconv.FormatUint(counts[int8(length)], 10),
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
