package main

// Trace parsing is copied without semantic changes from windowed_hitrate at
// 01af7e2. Keep the production command and its packet/leaf semantics untouched.
import (
	"bufio"
	"encoding/binary"
	"encoding/csv"
	"errors"
	"fmt"
	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcapgo"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"test-module/cache"
	"test-module/ipaddress"
	"test-module/routingtable"
)

type options struct {
	ruleFile, trace           string
	maxPackets, progressEvery uint64
}
type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}
type processStats struct {
	totalPackets, validPackets, nonIPv4Packets, nonTCPUDPPackets, parseErrorPackets, readErrorPackets uint64
}

func loadRoutingTable(ruleFile string) (*routingtable.RoutingTablePatriciaTrie, error) {
	file, err := os.Open(ruleFile)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	table := routingtable.NewRoutingTablePatriciaTrie()
	table.ReadRule(file)
	return table, nil
}

func processTrace(opts options, routingTable *routingtable.RoutingTablePatriciaTrie, handlePacket func(*cache.MinPacket) error) (processStats, error) {
	if isTextTrace(opts.trace) {
		return processTextTrace(opts, routingTable, handlePacket)
	}
	return processCapture(opts, routingTable, handlePacket)
}

func processCapture(opts options, routingTable *routingtable.RoutingTablePatriciaTrie, handlePacket func(*cache.MinPacket) error) (processStats, error) {
	reader, closer, err := openCapture(opts.trace)
	if err != nil {
		return processStats{}, fmt.Errorf("open trace: %w", err)
	}
	defer closer.Close()

	stats := processStats{}
	decodeOptions := gopacket.DecodeOptions{Lazy: false, NoCopy: true}
	linkType := reader.LinkType()

	for {
		data, _, err := reader.ZeroCopyReadPacketData()
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			stats.readErrorPackets++
			return stats, fmt.Errorf("read packet after %d packets: %w", stats.totalPackets, err)
		}
		stats.totalPackets++

		packet := gopacket.NewPacket(data, linkType, decodeOptions)
		if packet.ErrorLayer() != nil {
			stats.parseErrorPackets++
		}

		minPacket, ok := packetToMinPacket(packet, routingTable)
		switch {
		case ok:
			stats.validPackets++
			if err := handlePacket(&minPacket); err != nil {
				return stats, err
			}
			if shouldStopOrReport(opts, stats.validPackets) {
				return stats, nil
			}
		case packet.Layer(layers.LayerTypeIPv4) == nil:
			stats.nonIPv4Packets++
		default:
			stats.nonTCPUDPPackets++
		}
	}
	return stats, nil
}

func processTextTrace(opts options, routingTable *routingtable.RoutingTablePatriciaTrie, handlePacket func(*cache.MinPacket) error) (processStats, error) {
	file, err := os.Open(opts.trace)
	if err != nil {
		return processStats{}, fmt.Errorf("open text trace: %w", err)
	}
	defer file.Close()

	stats := processStats{}
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		stats.totalPackets++

		minPacket, err := textLineToMinPacket(line, routingTable)
		if err != nil {
			stats.parseErrorPackets++
			continue
		}
		if minPacket.FiveTuple() == nil {
			stats.nonTCPUDPPackets++
			continue
		}
		stats.validPackets++
		if err := handlePacket(&minPacket); err != nil {
			return stats, err
		}
		if shouldStopOrReport(opts, stats.validPackets) {
			return stats, nil
		}
	}
	if err := scanner.Err(); err != nil {
		stats.readErrorPackets++
		return stats, fmt.Errorf("read text trace after %d packets: %w", stats.totalPackets, err)
	}
	return stats, nil
}

func shouldStopOrReport(opts options, validPackets uint64) bool {
	if opts.progressEvery > 0 && validPackets%opts.progressEvery == 0 {
		fmt.Fprintf(os.Stderr, "processed %d valid simulator packets\n", validPackets)
	}
	return opts.maxPackets > 0 && validPackets >= opts.maxPackets
}

func packetToMinPacket(packet gopacket.Packet, routingTable *routingtable.RoutingTablePatriciaTrie) (cache.MinPacket, bool) {
	ipLayer := packet.Layer(layers.LayerTypeIPv4)
	if ipLayer == nil {
		return cache.MinPacket{}, false
	}
	ipv4, ok := ipLayer.(*layers.IPv4)
	if !ok || len(ipv4.SrcIP.To4()) != 4 || len(ipv4.DstIP.To4()) != 4 {
		return cache.MinPacket{}, false
	}

	proto := ""
	switch ipv4.Protocol {
	case layers.IPProtocolTCP:
		proto = "tcp"
	case layers.IPProtocolUDP:
		proto = "udp"
	default:
		return cache.MinPacket{}, false
	}

	src := binary.BigEndian.Uint32(ipv4.SrcIP.To4())
	dst := binary.BigEndian.Uint32(ipv4.DstIP.To4())
	return cache.MinPacket{
		Proto:       proto,
		SrcIP:       src,
		DstIP:       dst,
		IsLeafIndex: leafIndex(dst, routingTable),
	}, true
}

func textLineToMinPacket(line string, routingTable *routingtable.RoutingTablePatriciaTrie) (cache.MinPacket, error) {
	record, err := splitTextTraceLine(line)
	if err != nil {
		return cache.MinPacket{}, err
	}

	var srcIPStr, dstIPStr, protoStr string
	switch len(record) {
	case 8:
		srcIPStr = record[1]
		dstIPStr = record[3]
		protoStr = record[5]
	case 7:
		srcIPStr = record[2]
		dstIPStr = record[3]
		protoStr = record[4]
	default:
		return cache.MinPacket{}, fmt.Errorf("expected 7 or 8 text trace fields, got %d", len(record))
	}

	proto, ok := normalizeProto(protoStr)
	if !ok {
		return cache.MinPacket{Proto: strings.ToLower(protoStr)}, nil
	}
	srcIP := net.ParseIP(srcIPStr).To4()
	dstIP := net.ParseIP(dstIPStr).To4()
	if srcIP == nil || dstIP == nil {
		return cache.MinPacket{}, fmt.Errorf("invalid IPv4 src/dst: %q %q", srcIPStr, dstIPStr)
	}
	src := binary.BigEndian.Uint32(srcIP)
	dst := binary.BigEndian.Uint32(dstIP)
	return cache.MinPacket{
		Proto:       proto,
		SrcIP:       src,
		DstIP:       dst,
		IsLeafIndex: leafIndex(dst, routingTable),
	}, nil
}

func normalizeProto(raw string) (string, bool) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "tcp", "6":
		return "tcp", true
	case "udp", "17":
		return "udp", true
	default:
		return "", false
	}
}

func splitTextTraceLine(line string) ([]string, error) {
	if strings.Contains(line, ",") {
		reader := csv.NewReader(strings.NewReader(line))
		reader.FieldsPerRecord = -1
		return reader.Read()
	}
	return strings.Fields(line), nil
}

func leafIndex(dstIP uint32, routingTable *routingtable.RoutingTablePatriciaTrie) int8 {
	ip := ipaddress.NewIPaddress(dstIP)
	for i := 0; i < 33; i++ {
		if routingTable.IsLeaf(ip, i) {
			return int8(i)
		}
	}
	return 0
}

func isTextTrace(path string) bool {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".csv", ".tsv", ".p7", ".data", ".txt":
		return true
	default:
		return false
	}
}

func openCapture(path string) (packetReader, io.Closer, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}

	reader, err := pcapgo.NewReader(file)
	if err == nil {
		return reader, file, nil
	}

	if _, seekErr := file.Seek(0, io.SeekStart); seekErr != nil {
		file.Close()
		return nil, nil, fmt.Errorf("pcap reader failed (%v), then seek failed: %w", err, seekErr)
	}

	ngReader, ngErr := pcapgo.NewNgReader(file, pcapgo.DefaultNgReaderOptions)
	if ngErr == nil {
		return ngReader, file, nil
	}

	file.Close()
	return nil, nil, fmt.Errorf("pcap reader failed (%v); pcapng reader failed (%v)", err, ngErr)
}
