package main

import (
	"bufio"
	"encoding/binary"
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"math/bits"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcapgo"
)

type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}

type options struct {
	trace            string
	traceKind        string
	outputDir        string
	topN             int
	maxPackets       uint64
	progressInterval uint64
}

type summary struct {
	Trace                     string
	TraceKind                 string
	StartedAt                 time.Time
	FinishedAt                time.Time
	Format                    string
	LinkType                  string
	SnapLen                   string
	MaxPackets                uint64
	TotalPackets              uint64
	IPv4Packets               uint64
	NonIPv4Packets            uint64
	ParseErrorPackets         uint64
	ReadErrorPackets          uint64
	TransportParseErrorPacket uint64
	ProtocolPackets           map[uint8]uint64
	IPv4Bytes                 uint64
}

type flowKey struct {
	Proto   uint8
	SrcIP   uint32
	DstIP   uint32
	SrcPort uint16
	DstPort uint16
}

type flowStats struct {
	Key       flowKey
	Packets   uint64
	Bytes     uint64
	FirstSeen time.Time
	LastSeen  time.Time
}

type flowRow struct {
	Rank            int
	Key             flowKey
	Packets         uint64
	Bytes           uint64
	DurationSeconds float64
	FirstSeen       time.Time
	LastSeen        time.Time
}

type aggregateStats struct {
	UniqueFlows          int
	OnePacketFlows       uint64
	OnePacketFlowRatio   float64
	PacketPercentiles    percentileStats
	BytePercentiles      percentileStats
	DurationPercentiles  floatPercentileStats
	TopFlowPacketShares  map[int]float64
	TopFlowPacketCounts  map[int]uint64
	TotalFlowPackets     uint64
	TotalFlowBytes       uint64
	MaxPacketsPerFlow    uint64
	MaxBytesPerFlow      uint64
	MaxDurationPerFlow   float64
	MedianPacketsPerFlow uint64
}

type percentileStats struct {
	P50 uint64
	P90 uint64
	P99 uint64
	Max uint64
}

type floatPercentileStats struct {
	P50 float64
	P90 float64
	P99 float64
	Max float64
}

type binStats struct {
	Lower     uint64
	Upper     uint64
	Flows     uint64
	Packets   uint64
	Bytes     uint64
	FlowRatio float64
	PacketPct float64
	BytePct   float64
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}

	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		fatalf("create output dir: %v", err)
	}

	flows := make(map[flowKey]*flowStats)
	sum, err := analyze(opts, flows)
	if err != nil {
		fatalf("%v", err)
	}

	rows := buildFlowRows(flows)
	agg := buildAggregate(rows)
	bins := buildBins(rows, agg)

	if err := writeSummaryCSV(filepath.Join(opts.outputDir, "flow_summary.csv"), sum, agg, opts); err != nil {
		fatalf("write flow summary csv: %v", err)
	}
	if err := writeProtocolCountsCSV(filepath.Join(opts.outputDir, "protocol_counts.csv"), sum); err != nil {
		fatalf("write protocol counts csv: %v", err)
	}
	if err := writeFlowLengthsCSV(filepath.Join(opts.outputDir, "flow_lengths.csv"), rows); err != nil {
		fatalf("write flow lengths csv: %v", err)
	}
	if err := writeFlowBinsCSV(filepath.Join(opts.outputDir, "flow_length_bins.csv"), bins); err != nil {
		fatalf("write flow length bins csv: %v", err)
	}
	if err := writeTopFlowsCSV(filepath.Join(opts.outputDir, "top_flows.csv"), rows, opts.topN); err != nil {
		fatalf("write top flows csv: %v", err)
	}
	if err := writeSummaryMarkdown(filepath.Join(opts.outputDir, "flow_stats_summary.md"), sum, agg, opts); err != nil {
		fatalf("write summary markdown: %v", err)
	}
	if err := chownOutputTreeIfSudo(opts.outputDir); err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not restore output ownership after sudo: %v\n", err)
	}

	fmt.Fprintf(os.Stderr, "wrote flow statistics report to %s\n", opts.outputDir)
}

func parseOptions() (options, error) {
	opts := options{}

	flag.StringVar(&opts.trace, "trace", "", "pcap trace path")
	flag.StringVar(&opts.traceKind, "trace-kind", "", "trace kind label such as non-anonymized or anonymized")
	flag.StringVar(&opts.outputDir, "output-dir", "", "output directory")
	flag.IntVar(&opts.topN, "top-n", 100, "number of flows to include in top_flows.csv")
	flag.Uint64Var(&opts.maxPackets, "max-packets", 0, "maximum packets to read; 0 reads the whole trace")
	flag.Uint64Var(&opts.progressInterval, "progress-interval", 10_000_000, "stderr progress interval in packets; 0 disables progress")
	flag.Parse()

	if opts.trace == "" {
		return opts, errors.New("--trace is required")
	}
	if opts.outputDir == "" {
		return opts, errors.New("--output-dir is required")
	}
	if opts.topN <= 0 {
		return opts, errors.New("--top-n must be positive")
	}
	if opts.traceKind == "" {
		opts.traceKind = "unspecified"
	}
	return opts, nil
}

func analyze(opts options, flows map[flowKey]*flowStats) (summary, error) {
	if isTextTrace(opts.trace) {
		return analyzeTextTrace(opts, flows)
	}
	return analyzeCapture(opts, flows)
}

func analyzeCapture(opts options, flows map[flowKey]*flowStats) (summary, error) {
	reader, closer, format, snapLen, err := openCapture(opts.trace)
	if err != nil {
		return summary{}, fmt.Errorf("open trace: %w", err)
	}
	defer closer.Close()

	sum := summary{
		Trace:           opts.trace,
		TraceKind:       opts.traceKind,
		StartedAt:       time.Now(),
		Format:          format,
		LinkType:        reader.LinkType().String(),
		SnapLen:         snapLen,
		MaxPackets:      opts.maxPackets,
		ProtocolPackets: make(map[uint8]uint64),
	}

	decodeOptions := gopacket.DecodeOptions{Lazy: false, NoCopy: true}
	linkType := reader.LinkType()

	for {
		if opts.maxPackets > 0 && sum.TotalPackets >= opts.maxPackets {
			break
		}

		data, captureInfo, err := reader.ZeroCopyReadPacketData()
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			sum.ReadErrorPackets++
			return sum, fmt.Errorf("read packet after %d packets: %w", sum.TotalPackets, err)
		}

		sum.TotalPackets++
		if opts.progressInterval > 0 && sum.TotalPackets%opts.progressInterval == 0 {
			fmt.Fprintf(
				os.Stderr,
				"processed %d packets (IPv4: %d, flows: %d)\n",
				sum.TotalPackets,
				sum.IPv4Packets,
				len(flows),
			)
		}

		packet := gopacket.NewPacket(data, linkType, decodeOptions)
		if packet.ErrorLayer() != nil {
			sum.ParseErrorPackets++
		}

		ipLayer := packet.Layer(layers.LayerTypeIPv4)
		if ipLayer == nil {
			sum.NonIPv4Packets++
			continue
		}

		ipv4, ok := ipLayer.(*layers.IPv4)
		if !ok || len(ipv4.SrcIP.To4()) != 4 || len(ipv4.DstIP.To4()) != 4 {
			sum.ParseErrorPackets++
			sum.NonIPv4Packets++
			continue
		}

		key := flowKey{
			Proto: uint8(ipv4.Protocol),
			SrcIP: binary.BigEndian.Uint32(ipv4.SrcIP.To4()),
			DstIP: binary.BigEndian.Uint32(ipv4.DstIP.To4()),
		}
		if !fillTransportPorts(packet, ipv4.Protocol, &key) {
			sum.TransportParseErrorPacket++
		}

		packetLength := uint64(captureInfo.Length)
		if packetLength == 0 {
			packetLength = uint64(len(data))
		}

		sum.IPv4Packets++
		sum.IPv4Bytes += packetLength
		sum.ProtocolPackets[key.Proto]++
		addFlowPacket(flows, key, packetLength, captureInfo.Timestamp)
	}

	sum.FinishedAt = time.Now()
	return sum, nil
}

type textTracePacket struct {
	Key                 flowKey
	Length              uint64
	Timestamp           time.Time
	TransportParseError bool
}

func analyzeTextTrace(opts options, flows map[flowKey]*flowStats) (summary, error) {
	file, err := os.Open(opts.trace)
	if err != nil {
		return summary{}, fmt.Errorf("open text trace: %w", err)
	}
	defer file.Close()

	sum := summary{
		Trace:           opts.trace,
		TraceKind:       opts.traceKind,
		StartedAt:       time.Now(),
		Format:          "text-5tuple",
		LinkType:        "n/a",
		SnapLen:         "n/a",
		MaxPackets:      opts.maxPackets,
		ProtocolPackets: make(map[uint8]uint64),
	}

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		if opts.maxPackets > 0 && sum.TotalPackets >= opts.maxPackets {
			break
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		sum.TotalPackets++
		if opts.progressInterval > 0 && sum.TotalPackets%opts.progressInterval == 0 {
			fmt.Fprintf(
				os.Stderr,
				"processed %d packets (IPv4: %d, flows: %d)\n",
				sum.TotalPackets,
				sum.IPv4Packets,
				len(flows),
			)
		}

		packet, err := parseTextTraceLine(line)
		if err != nil {
			sum.ParseErrorPackets++
			continue
		}
		if packet.TransportParseError {
			sum.TransportParseErrorPacket++
		}

		sum.IPv4Packets++
		sum.IPv4Bytes += packet.Length
		sum.ProtocolPackets[packet.Key.Proto]++
		addFlowPacket(flows, packet.Key, packet.Length, packet.Timestamp)
	}
	if err := scanner.Err(); err != nil {
		sum.ReadErrorPackets++
		return sum, fmt.Errorf("read text trace after %d packets: %w", sum.TotalPackets, err)
	}

	sum.FinishedAt = time.Now()
	return sum, nil
}

func isTextTrace(path string) bool {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".csv", ".tsv", ".p7", ".data", ".txt":
		return true
	default:
		return false
	}
}

func parseTextTraceLine(line string) (textTracePacket, error) {
	record, err := splitTextTraceLine(line)
	if err != nil {
		return textTracePacket{}, err
	}
	return parseTextTraceRecord(record)
}

func splitTextTraceLine(line string) ([]string, error) {
	if strings.Contains(line, ",") {
		reader := csv.NewReader(strings.NewReader(line))
		reader.FieldsPerRecord = -1
		return reader.Read()
	}
	return strings.Fields(line), nil
}

func parseTextTraceRecord(record []string) (textTracePacket, error) {
	var timeStr, lengthStr, protoStr, srcIPStr, srcPortStr, dstIPStr, dstPortStr string
	switch len(record) {
	case 8:
		timeStr = record[0]
		srcIPStr = record[1]
		srcPortStr = record[2]
		dstIPStr = record[3]
		dstPortStr = record[4]
		protoStr = record[5]
		lengthStr = record[7]
	case 7:
		timeStr = record[0]
		lengthStr = record[1]
		srcIPStr = record[2]
		dstIPStr = record[3]
		protoStr = record[4]
		srcPortStr = record[5]
		dstPortStr = record[6]
	default:
		return textTracePacket{}, fmt.Errorf("expected 7 or 8 text trace fields, got %d", len(record))
	}

	timestamp, err := parseRelativeTimestamp(timeStr)
	if err != nil {
		return textTracePacket{}, err
	}
	srcIP, err := parseIPv4Uint32(srcIPStr)
	if err != nil {
		return textTracePacket{}, err
	}
	dstIP, err := parseIPv4Uint32(dstIPStr)
	if err != nil {
		return textTracePacket{}, err
	}
	proto, err := parseTraceProtocol(protoStr)
	if err != nil {
		return textTracePacket{}, err
	}
	length, err := strconv.ParseUint(lengthStr, 10, 64)
	if err != nil {
		return textTracePacket{}, fmt.Errorf("invalid packet length %q: %w", lengthStr, err)
	}

	srcPort, srcPortErr := parseTracePort(srcPortStr)
	dstPort, dstPortErr := parseTracePort(dstPortStr)
	transportParseError := srcPortErr != nil || dstPortErr != nil
	if proto == uint8(layers.IPProtocolTCP) || proto == uint8(layers.IPProtocolUDP) {
		if srcPortErr != nil {
			return textTracePacket{}, srcPortErr
		}
		if dstPortErr != nil {
			return textTracePacket{}, dstPortErr
		}
	}

	return textTracePacket{
		Key: flowKey{
			Proto:   proto,
			SrcIP:   srcIP,
			DstIP:   dstIP,
			SrcPort: srcPort,
			DstPort: dstPort,
		},
		Length:              length,
		Timestamp:           timestamp,
		TransportParseError: transportParseError,
	}, nil
}

func parseRelativeTimestamp(raw string) (time.Time, error) {
	seconds, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid timestamp %q: %w", raw, err)
	}
	if seconds < 0 {
		return time.Time{}, fmt.Errorf("negative timestamp %q", raw)
	}
	whole, frac := math.Modf(seconds)
	nsec := int64(math.Round(frac * 1_000_000_000))
	if nsec == 1_000_000_000 {
		whole++
		nsec = 0
	}
	return time.Unix(int64(whole), nsec).UTC(), nil
}

func parseIPv4Uint32(raw string) (uint32, error) {
	ip := net.ParseIP(raw).To4()
	if ip == nil {
		return 0, fmt.Errorf("invalid IPv4 address %q", raw)
	}
	return binary.BigEndian.Uint32(ip), nil
}

func parseTraceProtocol(raw string) (uint8, error) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "tcp":
		return uint8(layers.IPProtocolTCP), nil
	case "udp":
		return uint8(layers.IPProtocolUDP), nil
	case "icmp", "icmpv4":
		return uint8(layers.IPProtocolICMPv4), nil
	}
	value, err := strconv.ParseUint(raw, 0, 8)
	if err != nil {
		return 0, fmt.Errorf("invalid protocol %q: %w", raw, err)
	}
	return uint8(value), nil
}

func parseTracePort(raw string) (uint16, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" || raw == "-" {
		return 0, nil
	}
	value, err := strconv.ParseUint(raw, 10, 16)
	if err != nil {
		return 0, fmt.Errorf("invalid port %q: %w", raw, err)
	}
	return uint16(value), nil
}

func fillTransportPorts(packet gopacket.Packet, protocol layers.IPProtocol, key *flowKey) bool {
	switch protocol {
	case layers.IPProtocolTCP:
		layer := packet.Layer(layers.LayerTypeTCP)
		tcp, ok := layer.(*layers.TCP)
		if !ok {
			return false
		}
		key.SrcPort = uint16(tcp.SrcPort)
		key.DstPort = uint16(tcp.DstPort)
		return true
	case layers.IPProtocolUDP:
		layer := packet.Layer(layers.LayerTypeUDP)
		udp, ok := layer.(*layers.UDP)
		if !ok {
			return false
		}
		key.SrcPort = uint16(udp.SrcPort)
		key.DstPort = uint16(udp.DstPort)
		return true
	case layers.IPProtocolICMPv4:
		return true
	default:
		return true
	}
}

func addFlowPacket(flows map[flowKey]*flowStats, key flowKey, packetLength uint64, timestamp time.Time) {
	stats := flows[key]
	if stats == nil {
		flows[key] = &flowStats{
			Key:       key,
			Packets:   1,
			Bytes:     packetLength,
			FirstSeen: timestamp,
			LastSeen:  timestamp,
		}
		return
	}

	stats.Packets++
	stats.Bytes += packetLength
	if timestamp.Before(stats.FirstSeen) {
		stats.FirstSeen = timestamp
	}
	if timestamp.After(stats.LastSeen) {
		stats.LastSeen = timestamp
	}
}

func openCapture(path string) (packetReader, io.Closer, string, string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, "", "", err
	}

	reader, err := pcapgo.NewReader(file)
	if err == nil {
		return reader, file, "pcap", strconv.FormatUint(uint64(reader.Snaplen()), 10), nil
	}

	if _, seekErr := file.Seek(0, io.SeekStart); seekErr != nil {
		file.Close()
		return nil, nil, "", "", fmt.Errorf("pcap reader failed (%v), then seek failed: %w", err, seekErr)
	}

	ngReader, ngErr := pcapgo.NewNgReader(file, pcapgo.DefaultNgReaderOptions)
	if ngErr == nil {
		return ngReader, file, "pcapng", "n/a", nil
	}

	file.Close()
	return nil, nil, "", "", fmt.Errorf("pcap reader failed (%v); pcapng reader failed (%v)", err, ngErr)
}

func buildFlowRows(flows map[flowKey]*flowStats) []flowRow {
	rows := make([]flowRow, 0, len(flows))
	for _, stats := range flows {
		rows = append(rows, flowRow{
			Key:             stats.Key,
			Packets:         stats.Packets,
			Bytes:           stats.Bytes,
			DurationSeconds: durationSeconds(stats.FirstSeen, stats.LastSeen),
			FirstSeen:       stats.FirstSeen,
			LastSeen:        stats.LastSeen,
		})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Packets != rows[j].Packets {
			return rows[i].Packets > rows[j].Packets
		}
		if rows[i].Bytes != rows[j].Bytes {
			return rows[i].Bytes > rows[j].Bytes
		}
		return compareFlowKey(rows[i].Key, rows[j].Key)
	})
	for i := range rows {
		rows[i].Rank = i + 1
	}
	return rows
}

func compareFlowKey(left, right flowKey) bool {
	if left.Proto != right.Proto {
		return left.Proto < right.Proto
	}
	if left.SrcIP != right.SrcIP {
		return left.SrcIP < right.SrcIP
	}
	if left.DstIP != right.DstIP {
		return left.DstIP < right.DstIP
	}
	if left.SrcPort != right.SrcPort {
		return left.SrcPort < right.SrcPort
	}
	return left.DstPort < right.DstPort
}

func buildAggregate(rows []flowRow) aggregateStats {
	agg := aggregateStats{
		UniqueFlows:         len(rows),
		TopFlowPacketShares: make(map[int]float64),
		TopFlowPacketCounts: make(map[int]uint64),
	}
	if len(rows) == 0 {
		return agg
	}

	packetValues := make([]uint64, 0, len(rows))
	byteValues := make([]uint64, 0, len(rows))
	durationValues := make([]float64, 0, len(rows))

	for _, row := range rows {
		packetValues = append(packetValues, row.Packets)
		byteValues = append(byteValues, row.Bytes)
		durationValues = append(durationValues, row.DurationSeconds)
		agg.TotalFlowPackets += row.Packets
		agg.TotalFlowBytes += row.Bytes
		if row.Packets == 1 {
			agg.OnePacketFlows++
		}
	}

	sort.Slice(packetValues, func(i, j int) bool { return packetValues[i] < packetValues[j] })
	sort.Slice(byteValues, func(i, j int) bool { return byteValues[i] < byteValues[j] })
	sort.Float64s(durationValues)

	agg.PacketPercentiles = percentileStats{
		P50: percentileUint(packetValues, 0.50),
		P90: percentileUint(packetValues, 0.90),
		P99: percentileUint(packetValues, 0.99),
		Max: packetValues[len(packetValues)-1],
	}
	agg.BytePercentiles = percentileStats{
		P50: percentileUint(byteValues, 0.50),
		P90: percentileUint(byteValues, 0.90),
		P99: percentileUint(byteValues, 0.99),
		Max: byteValues[len(byteValues)-1],
	}
	agg.DurationPercentiles = floatPercentileStats{
		P50: percentileFloat(durationValues, 0.50),
		P90: percentileFloat(durationValues, 0.90),
		P99: percentileFloat(durationValues, 0.99),
		Max: durationValues[len(durationValues)-1],
	}
	agg.MaxPacketsPerFlow = agg.PacketPercentiles.Max
	agg.MaxBytesPerFlow = agg.BytePercentiles.Max
	agg.MaxDurationPerFlow = agg.DurationPercentiles.Max
	agg.MedianPacketsPerFlow = agg.PacketPercentiles.P50
	agg.OnePacketFlowRatio = float64(agg.OnePacketFlows) / float64(len(rows))

	cutoffs := []int{1, 5, 10, 50, 100}
	for _, cutoff := range cutoffs {
		var packets uint64
		limit := cutoff
		if len(rows) < limit {
			limit = len(rows)
		}
		for i := 0; i < limit; i++ {
			packets += rows[i].Packets
		}
		agg.TopFlowPacketCounts[cutoff] = packets
		if agg.TotalFlowPackets > 0 {
			agg.TopFlowPacketShares[cutoff] = float64(packets) / float64(agg.TotalFlowPackets)
		}
	}

	return agg
}

func buildBins(rows []flowRow, agg aggregateStats) []binStats {
	binsByLower := make(map[uint64]*binStats)
	for _, row := range rows {
		lower, upper := packetBin(row.Packets)
		current := binsByLower[lower]
		if current == nil {
			current = &binStats{Lower: lower, Upper: upper}
			binsByLower[lower] = current
		}
		current.Flows++
		current.Packets += row.Packets
		current.Bytes += row.Bytes
	}

	lowers := make([]uint64, 0, len(binsByLower))
	for lower := range binsByLower {
		lowers = append(lowers, lower)
	}
	sort.Slice(lowers, func(i, j int) bool { return lowers[i] < lowers[j] })

	result := make([]binStats, 0, len(lowers))
	for _, lower := range lowers {
		row := *binsByLower[lower]
		if agg.UniqueFlows > 0 {
			row.FlowRatio = float64(row.Flows) / float64(agg.UniqueFlows)
		}
		if agg.TotalFlowPackets > 0 {
			row.PacketPct = float64(row.Packets) / float64(agg.TotalFlowPackets)
		}
		if agg.TotalFlowBytes > 0 {
			row.BytePct = float64(row.Bytes) / float64(agg.TotalFlowBytes)
		}
		result = append(result, row)
	}
	return result
}

func packetBin(packets uint64) (uint64, uint64) {
	if packets <= 1 {
		return 1, 1
	}
	exp := bits.Len64(packets) - 1
	lower := uint64(1) << uint(exp)
	if exp >= 63 {
		return lower, math.MaxUint64
	}
	upper := (uint64(1) << uint(exp+1)) - 1
	return lower, upper
}

func writeSummaryCSV(path string, sum summary, agg aggregateStats, opts options) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	rows := [][]string{
		{"metric", "value"},
		{"trace", sum.Trace},
		{"trace_kind", sum.TraceKind},
		{"format", sum.Format},
		{"link_type", sum.LinkType},
		{"snaplen", sum.SnapLen},
		{"flow_definition", "directional_ipv4_5_tuple"},
		{"included_non_tcp_udp_icmp_ipv4_in_flow_stats", "true"},
		{"max_packets", formatUint(sum.MaxPackets)},
		{"top_n", strconv.Itoa(opts.topN)},
		{"total_packets", formatUint(sum.TotalPackets)},
		{"ipv4_packets", formatUint(sum.IPv4Packets)},
		{"non_ipv4_packets", formatUint(sum.NonIPv4Packets)},
		{"parse_error_packets", formatUint(sum.ParseErrorPackets)},
		{"read_error_packets", formatUint(sum.ReadErrorPackets)},
		{"transport_parse_error_packets", formatUint(sum.TransportParseErrorPacket)},
		{"ipv4_bytes", formatUint(sum.IPv4Bytes)},
		{"tcp_packets", formatUint(sum.ProtocolPackets[uint8(layers.IPProtocolTCP)])},
		{"udp_packets", formatUint(sum.ProtocolPackets[uint8(layers.IPProtocolUDP)])},
		{"icmp_packets", formatUint(sum.ProtocolPackets[uint8(layers.IPProtocolICMPv4)])},
		{"other_ipv4_packets", formatUint(otherProtocolPackets(sum.ProtocolPackets))},
		{"unique_flow_count", strconv.Itoa(agg.UniqueFlows)},
		{"one_packet_flow_count", formatUint(agg.OnePacketFlows)},
		{"one_packet_flow_ratio", formatFloat(agg.OnePacketFlowRatio)},
		{"top1_flow_packet_count", formatUint(agg.TopFlowPacketCounts[1])},
		{"top1_flow_packet_share", formatFloat(agg.TopFlowPacketShares[1])},
		{"top5_flow_packet_count", formatUint(agg.TopFlowPacketCounts[5])},
		{"top5_flow_packet_share", formatFloat(agg.TopFlowPacketShares[5])},
		{"top10_flow_packet_count", formatUint(agg.TopFlowPacketCounts[10])},
		{"top10_flow_packet_share", formatFloat(agg.TopFlowPacketShares[10])},
		{"top50_flow_packet_count", formatUint(agg.TopFlowPacketCounts[50])},
		{"top50_flow_packet_share", formatFloat(agg.TopFlowPacketShares[50])},
		{"top100_flow_packet_count", formatUint(agg.TopFlowPacketCounts[100])},
		{"top100_flow_packet_share", formatFloat(agg.TopFlowPacketShares[100])},
		{"p50_packets_per_flow", formatUint(agg.PacketPercentiles.P50)},
		{"p90_packets_per_flow", formatUint(agg.PacketPercentiles.P90)},
		{"p99_packets_per_flow", formatUint(agg.PacketPercentiles.P99)},
		{"max_packets_per_flow", formatUint(agg.PacketPercentiles.Max)},
		{"p50_bytes_per_flow", formatUint(agg.BytePercentiles.P50)},
		{"p90_bytes_per_flow", formatUint(agg.BytePercentiles.P90)},
		{"p99_bytes_per_flow", formatUint(agg.BytePercentiles.P99)},
		{"max_bytes_per_flow", formatUint(agg.BytePercentiles.Max)},
		{"p50_duration_seconds", formatFloat(agg.DurationPercentiles.P50)},
		{"p90_duration_seconds", formatFloat(agg.DurationPercentiles.P90)},
		{"p99_duration_seconds", formatFloat(agg.DurationPercentiles.P99)},
		{"max_duration_seconds", formatFloat(agg.DurationPercentiles.Max)},
		{"started_at", sum.StartedAt.Format(time.RFC3339Nano)},
		{"finished_at", sum.FinishedAt.Format(time.RFC3339Nano)},
		{"runtime_seconds", formatFloat(sum.FinishedAt.Sub(sum.StartedAt).Seconds())},
	}

	for _, row := range rows {
		if err := writer.Write(row); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeProtocolCountsCSV(path string, sum summary) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	if err := writer.Write([]string{"protocol_number", "protocol_name", "packets", "ratio_of_ipv4"}); err != nil {
		return err
	}

	protocols := make([]uint8, 0, len(sum.ProtocolPackets))
	for protocol := range sum.ProtocolPackets {
		protocols = append(protocols, protocol)
	}
	sort.Slice(protocols, func(i, j int) bool {
		left := sum.ProtocolPackets[protocols[i]]
		right := sum.ProtocolPackets[protocols[j]]
		if left != right {
			return left > right
		}
		return protocols[i] < protocols[j]
	})

	for _, protocol := range protocols {
		count := sum.ProtocolPackets[protocol]
		ratio := 0.0
		if sum.IPv4Packets > 0 {
			ratio = float64(count) / float64(sum.IPv4Packets)
		}
		if err := writer.Write([]string{
			strconv.Itoa(int(protocol)),
			protocolName(protocol),
			formatUint(count),
			formatFloat(ratio),
		}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeFlowLengthsCSV(path string, rows []flowRow) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"rank",
		"protocol_number",
		"protocol",
		"src_ip",
		"dst_ip",
		"src_port",
		"dst_port",
		"packets",
		"bytes",
		"duration_seconds",
		"first_seen",
		"last_seen",
	}
	if err := writer.Write(header); err != nil {
		return err
	}
	for _, row := range rows {
		if err := writer.Write(flowRecord(row)); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeTopFlowsCSV(path string, rows []flowRow, topN int) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"rank",
		"protocol_number",
		"protocol",
		"src_ip",
		"dst_ip",
		"src_port",
		"dst_port",
		"packets",
		"bytes",
		"duration_seconds",
		"first_seen",
		"last_seen",
	}
	if err := writer.Write(header); err != nil {
		return err
	}

	limit := topN
	if len(rows) < limit {
		limit = len(rows)
	}
	for i := 0; i < limit; i++ {
		if err := writer.Write(flowRecord(rows[i])); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeFlowBinsCSV(path string, bins []binStats) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"packet_count_lower",
		"packet_count_upper",
		"flow_count",
		"flow_ratio",
		"packet_sum",
		"packet_ratio",
		"byte_sum",
		"byte_ratio",
	}
	if err := writer.Write(header); err != nil {
		return err
	}

	for _, row := range bins {
		if err := writer.Write([]string{
			formatUint(row.Lower),
			formatUint(row.Upper),
			formatUint(row.Flows),
			formatFloat(row.FlowRatio),
			formatUint(row.Packets),
			formatFloat(row.PacketPct),
			formatUint(row.Bytes),
			formatFloat(row.BytePct),
		}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeSummaryMarkdown(path string, sum summary, agg aggregateStats, opts options) error {
	var builder strings.Builder
	traceBase := filepath.Base(sum.Trace)

	fmt.Fprintf(&builder, "# Flow statistics: %s\n\n", traceBase)
	fmt.Fprintf(&builder, "Generated at `%s`.\n\n", sum.FinishedAt.Format(time.RFC3339))

	builder.WriteString("## Input\n\n")
	fmt.Fprintf(&builder, "- trace: `%s`\n", sum.Trace)
	fmt.Fprintf(&builder, "- trace kind: `%s`\n", sum.TraceKind)
	fmt.Fprintf(&builder, "- format: `%s`\n", sum.Format)
	fmt.Fprintf(&builder, "- link type: `%s`\n", sum.LinkType)
	fmt.Fprintf(&builder, "- snaplen: `%s`\n", sum.SnapLen)
	if sum.MaxPackets > 0 {
		fmt.Fprintf(&builder, "- max packets: `%d`\n", sum.MaxPackets)
	} else {
		builder.WriteString("- max packets: `all`\n")
	}
	builder.WriteString("- flow definition: directional IPv4 5-tuple (`proto`, `src_ip`, `dst_ip`, `src_port`, `dst_port`).\n")
	builder.WriteString("- TCP and UDP use L4 ports. ICMP and other IPv4 protocols use `src_port=0`, `dst_port=0`.\n")
	builder.WriteString("- Non TCP/UDP/ICMP IPv4 packets are included in flow statistics and broken out in `protocol_counts.csv`.\n\n")

	builder.WriteString("## Packet summary\n\n")
	builder.WriteString("| metric | value |\n")
	builder.WriteString("| --- | ---: |\n")
	fmt.Fprintf(&builder, "| total packets | %d |\n", sum.TotalPackets)
	fmt.Fprintf(&builder, "| IPv4 packets | %d |\n", sum.IPv4Packets)
	fmt.Fprintf(&builder, "| TCP packets | %d |\n", sum.ProtocolPackets[uint8(layers.IPProtocolTCP)])
	fmt.Fprintf(&builder, "| UDP packets | %d |\n", sum.ProtocolPackets[uint8(layers.IPProtocolUDP)])
	fmt.Fprintf(&builder, "| ICMP packets | %d |\n", sum.ProtocolPackets[uint8(layers.IPProtocolICMPv4)])
	fmt.Fprintf(&builder, "| other IPv4 packets | %d |\n", otherProtocolPackets(sum.ProtocolPackets))
	fmt.Fprintf(&builder, "| transport parse error packets | %d |\n", sum.TransportParseErrorPacket)
	fmt.Fprintf(&builder, "| parse error packets | %d |\n", sum.ParseErrorPackets)
	fmt.Fprintf(&builder, "| runtime seconds | %.3f |\n\n", sum.FinishedAt.Sub(sum.StartedAt).Seconds())

	builder.WriteString("## Flow summary\n\n")
	builder.WriteString("| metric | value |\n")
	builder.WriteString("| --- | ---: |\n")
	fmt.Fprintf(&builder, "| unique flows | %d |\n", agg.UniqueFlows)
	fmt.Fprintf(&builder, "| one-packet flows | %d |\n", agg.OnePacketFlows)
	fmt.Fprintf(&builder, "| one-packet flow ratio | %.6f |\n", agg.OnePacketFlowRatio)
	fmt.Fprintf(&builder, "| top 1 flow packet share | %.6f |\n", agg.TopFlowPacketShares[1])
	fmt.Fprintf(&builder, "| top 10 flow packet share | %.6f |\n", agg.TopFlowPacketShares[10])
	fmt.Fprintf(&builder, "| top 100 flow packet share | %.6f |\n", agg.TopFlowPacketShares[100])
	fmt.Fprintf(&builder, "| p50 packets per flow | %d |\n", agg.PacketPercentiles.P50)
	fmt.Fprintf(&builder, "| p90 packets per flow | %d |\n", agg.PacketPercentiles.P90)
	fmt.Fprintf(&builder, "| p99 packets per flow | %d |\n", agg.PacketPercentiles.P99)
	fmt.Fprintf(&builder, "| max packets per flow | %d |\n", agg.PacketPercentiles.Max)
	fmt.Fprintf(&builder, "| p50 bytes per flow | %d |\n", agg.BytePercentiles.P50)
	fmt.Fprintf(&builder, "| p90 bytes per flow | %d |\n", agg.BytePercentiles.P90)
	fmt.Fprintf(&builder, "| p99 bytes per flow | %d |\n", agg.BytePercentiles.P99)
	fmt.Fprintf(&builder, "| max bytes per flow | %d |\n", agg.BytePercentiles.Max)
	fmt.Fprintf(&builder, "| p50 duration seconds | %.6f |\n", agg.DurationPercentiles.P50)
	fmt.Fprintf(&builder, "| p90 duration seconds | %.6f |\n", agg.DurationPercentiles.P90)
	fmt.Fprintf(&builder, "| p99 duration seconds | %.6f |\n", agg.DurationPercentiles.P99)
	fmt.Fprintf(&builder, "| max duration seconds | %.6f |\n\n", agg.DurationPercentiles.Max)

	builder.WriteString("## Files\n\n")
	builder.WriteString("- `flow_summary.csv`: run metadata, packet counters, flow count, concentration, and percentiles.\n")
	builder.WriteString("- `flow_lengths.csv`: one row per directional flow, sorted by packet count descending.\n")
	builder.WriteString("- `flow_length_bins.csv`: log2-binned packets-per-flow distribution.\n")
	builder.WriteString("- `top_flows.csv`: top flows by packet count.\n")
	builder.WriteString("- `protocol_counts.csv`: IPv4 protocol packet counts.\n\n")

	builder.WriteString("## Rerun\n\n")
	builder.WriteString("```bash\n")
	fmt.Fprintf(&builder, "sudo ./scripts/analyze_flow_stats \\\n")
	fmt.Fprintf(&builder, "  --trace %s \\\n", shellQuote(sum.Trace))
	fmt.Fprintf(&builder, "  --trace-kind %s \\\n", shellQuote(sum.TraceKind))
	if sum.MaxPackets > 0 {
		fmt.Fprintf(&builder, "  --max-packets %d \\\n", sum.MaxPackets)
	}
	fmt.Fprintf(&builder, "  --top-n %d \\\n", opts.topN)
	fmt.Fprintf(&builder, "  --output-dir %s\n", shellQuote(opts.outputDir))
	builder.WriteString("```\n")

	return os.WriteFile(path, []byte(builder.String()), 0o644)
}

func flowRecord(row flowRow) []string {
	return []string{
		strconv.Itoa(row.Rank),
		strconv.Itoa(int(row.Key.Proto)),
		protocolName(row.Key.Proto),
		formatIPv4(row.Key.SrcIP),
		formatIPv4(row.Key.DstIP),
		strconv.Itoa(int(row.Key.SrcPort)),
		strconv.Itoa(int(row.Key.DstPort)),
		formatUint(row.Packets),
		formatUint(row.Bytes),
		formatFloat(row.DurationSeconds),
		formatTime(row.FirstSeen),
		formatTime(row.LastSeen),
	}
}

func percentileUint(sortedValues []uint64, q float64) uint64 {
	if len(sortedValues) == 0 {
		return 0
	}
	index := percentileIndex(len(sortedValues), q)
	return sortedValues[index]
}

func percentileFloat(sortedValues []float64, q float64) float64 {
	if len(sortedValues) == 0 {
		return 0
	}
	index := percentileIndex(len(sortedValues), q)
	return sortedValues[index]
}

func percentileIndex(length int, q float64) int {
	if q <= 0 {
		return 0
	}
	if q >= 1 {
		return length - 1
	}
	index := int(math.Ceil(q*float64(length))) - 1
	if index < 0 {
		return 0
	}
	if index >= length {
		return length - 1
	}
	return index
}

func durationSeconds(firstSeen, lastSeen time.Time) float64 {
	if firstSeen.IsZero() || lastSeen.IsZero() || lastSeen.Before(firstSeen) {
		return 0
	}
	return lastSeen.Sub(firstSeen).Seconds()
}

func otherProtocolPackets(protocolPackets map[uint8]uint64) uint64 {
	var count uint64
	for protocol, packets := range protocolPackets {
		switch layers.IPProtocol(protocol) {
		case layers.IPProtocolTCP, layers.IPProtocolUDP, layers.IPProtocolICMPv4:
			continue
		default:
			count += packets
		}
	}
	return count
}

func protocolName(protocol uint8) string {
	switch layers.IPProtocol(protocol) {
	case layers.IPProtocolTCP:
		return "TCP"
	case layers.IPProtocolUDP:
		return "UDP"
	case layers.IPProtocolICMPv4:
		return "ICMP"
	default:
		return fmt.Sprintf("IP:%d", protocol)
	}
}

func formatIPv4(value uint32) string {
	return fmt.Sprintf("%d.%d.%d.%d", byte(value>>24), byte(value>>16), byte(value>>8), byte(value))
}

func formatUint(value uint64) string {
	return strconv.FormatUint(value, 10)
}

func formatFloat(value float64) string {
	return strconv.FormatFloat(value, 'f', 12, 64)
}

func formatTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.Format(time.RFC3339Nano)
}

func shellQuote(value string) string {
	if value == "" {
		return "''"
	}
	if strings.IndexFunc(value, func(r rune) bool {
		return !(r == '/' || r == '.' || r == '_' || r == '-' || r == ',' || r == ':' || r == '+' || r == '=' || (r >= '0' && r <= '9') || (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z'))
	}) == -1 {
		return value
	}
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func chownOutputTreeIfSudo(outputDir string) error {
	if os.Geteuid() != 0 {
		return nil
	}
	rawUID := os.Getenv("SUDO_UID")
	rawGID := os.Getenv("SUDO_GID")
	if rawUID == "" || rawGID == "" {
		return nil
	}
	uid, err := strconv.Atoi(rawUID)
	if err != nil {
		return fmt.Errorf("invalid SUDO_UID %q: %w", rawUID, err)
	}
	gid, err := strconv.Atoi(rawGID)
	if err != nil {
		return fmt.Errorf("invalid SUDO_GID %q: %w", rawGID, err)
	}
	return filepath.WalkDir(outputDir, func(path string, _ os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		return os.Chown(path, uid, gid)
	})
}

func fatalf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", args...)
	os.Exit(1)
}
