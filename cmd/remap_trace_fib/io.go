package main

// Trace and rule helpers copied from cmd/fit_trace_tree_lpm so that the
// remapped traces use exactly the same packet filter (IPv4 TCP/UDP).

import (
	"bufio"
	"encoding/binary"
	"encoding/csv"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcapgo"
)

type rulePrefix struct {
	network uint32
	length  int
}

type lpmMatch struct {
	network uint32
	length  int
}

// ruleSet keeps the unique prefixes and a /24-expanded LPM table.
type ruleSet struct {
	prefixes    []rulePrefix
	by24        []uint8
	longer      [33]map[uint32]struct{}
	longLengths []int
}

func loadRules(path string) (*ruleSet, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	rules := &ruleSet{by24: make([]uint8, 1<<24)}
	seen := map[rulePrefix]struct{}{}
	var short [25][]uint32
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	line := 0
	for scanner.Scan() {
		line++
		text := strings.TrimSpace(strings.SplitN(scanner.Text(), "#", 2)[0])
		if text == "" {
			continue
		}
		network, length, err := parseRulePrefix(strings.Fields(text))
		if err != nil {
			return nil, fmt.Errorf("rule line %d: %w", line, err)
		}
		prefix := rulePrefix{network, length}
		if _, ok := seen[prefix]; ok {
			continue
		}
		seen[prefix] = struct{}{}
		rules.prefixes = append(rules.prefixes, prefix)
		if length <= 24 {
			short[length] = append(short[length], network)
		} else {
			if rules.longer[length] == nil {
				rules.longer[length] = map[uint32]struct{}{}
			}
			rules.longer[length][network] = struct{}{}
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	for length := 0; length <= 24; length++ {
		span := 1 << (24 - length)
		for _, network := range short[length] {
			start := int(network >> 8)
			for offset := 0; offset < span; offset++ {
				rules.by24[start+offset] = uint8(length)
			}
		}
	}
	for length := 32; length >= 25; length-- {
		if len(rules.longer[length]) > 0 {
			rules.longLengths = append(rules.longLengths, length)
		}
	}
	return rules, nil
}

func (rules *ruleSet) matchPrefix(ip uint32) lpmMatch {
	for _, length := range rules.longLengths {
		if _, ok := rules.longer[length][ip&prefixMask(length)]; ok {
			return lpmMatch{network: ip & prefixMask(length), length: length}
		}
	}
	length := int(rules.by24[ip>>8])
	return lpmMatch{network: ip & prefixMask(length), length: length}
}

type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}

type tracePacket struct {
	src   uint32
	dst   uint32
	proto string
}

type scanStats struct {
	totalPackets     uint64
	validPackets     uint64
	nonIPv4Packets   uint64
	nonTCPUDPPackets uint64
	parseErrors      uint64
}

func scanTrace(path string, maxPackets, progressInterval uint64, visit func(tracePacket) error) (scanStats, error) {
	if isTextTrace(path) {
		return scanTextTrace(path, maxPackets, progressInterval, visit)
	}
	reader, closer, err := openCapture(path)
	if err != nil {
		return scanStats{}, err
	}
	defer closer.Close()

	stats := scanStats{}
	decodeOptions := gopacket.DecodeOptions{Lazy: false, NoCopy: true}
	for {
		data, _, err := reader.ZeroCopyReadPacketData()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return stats, err
		}
		stats.totalPackets++
		packet := gopacket.NewPacket(data, reader.LinkType(), decodeOptions)
		if packet.ErrorLayer() != nil {
			stats.parseErrors++
		}
		ipLayer := packet.Layer(layers.LayerTypeIPv4)
		if ipLayer == nil {
			stats.nonIPv4Packets++
			continue
		}
		ipv4, ok := ipLayer.(*layers.IPv4)
		if !ok || ipv4.SrcIP.To4() == nil || ipv4.DstIP.To4() == nil {
			stats.parseErrors++
			continue
		}
		proto := ""
		switch ipv4.Protocol {
		case layers.IPProtocolTCP:
			proto = "tcp"
		case layers.IPProtocolUDP:
			proto = "udp"
		default:
			stats.nonTCPUDPPackets++
			continue
		}
		stats.validPackets++
		if err := visit(tracePacket{
			src:   binary.BigEndian.Uint32(ipv4.SrcIP.To4()),
			dst:   binary.BigEndian.Uint32(ipv4.DstIP.To4()),
			proto: proto,
		}); err != nil {
			return stats, err
		}
		if progressInterval > 0 && stats.validPackets%progressInterval == 0 {
			fmt.Fprintf(os.Stderr, "%s: processed %d valid packets\n", filepath.Base(path), stats.validPackets)
		}
		if maxPackets > 0 && stats.validPackets >= maxPackets {
			break
		}
	}
	return stats, nil
}

func scanTextTrace(path string, maxPackets, progressInterval uint64, visit func(tracePacket) error) (scanStats, error) {
	file, err := os.Open(path)
	if err != nil {
		return scanStats{}, err
	}
	defer file.Close()
	stats := scanStats{}
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		stats.totalPackets++
		record, err := splitTraceLine(line)
		if err != nil || len(record) < 4 {
			stats.parseErrors++
			continue
		}
		var srcText, dstText, proto string
		if len(record) == 7 {
			srcText, dstText, proto = record[2], record[3], strings.ToLower(record[4])
		} else if len(record) >= 8 {
			srcText, dstText, proto = record[1], record[3], strings.ToLower(record[5])
		} else {
			stats.parseErrors++
			continue
		}
		if proto != "tcp" && proto != "udp" && proto != "6" && proto != "17" {
			stats.nonTCPUDPPackets++
			continue
		}
		if proto == "6" {
			proto = "tcp"
		} else if proto == "17" {
			proto = "udp"
		}
		srcIP := net.ParseIP(srcText).To4()
		dstIP := net.ParseIP(dstText).To4()
		if srcIP == nil || dstIP == nil {
			stats.parseErrors++
			continue
		}
		stats.validPackets++
		if err := visit(tracePacket{src: binary.BigEndian.Uint32(srcIP), dst: binary.BigEndian.Uint32(dstIP), proto: proto}); err != nil {
			return stats, err
		}
		if progressInterval > 0 && stats.validPackets%progressInterval == 0 {
			fmt.Fprintf(os.Stderr, "%s: processed %d valid packets\n", filepath.Base(path), stats.validPackets)
		}
		if maxPackets > 0 && stats.validPackets >= maxPackets {
			break
		}
	}
	return stats, scanner.Err()
}

func splitTraceLine(line string) ([]string, error) {
	if strings.Contains(line, ",") {
		reader := csv.NewReader(strings.NewReader(line))
		reader.FieldsPerRecord = -1
		return reader.Read()
	}
	return strings.Fields(line), nil
}

func isTextTrace(path string) bool {
	switch strings.ToLower(filepath.Ext(path)) {
	case ".txt", ".csv", ".tsv", ".p7", ".data":
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
	if strings.EqualFold(filepath.Ext(path), ".pcapng") {
		reader, err := pcapgo.NewNgReader(file, pcapgo.DefaultNgReaderOptions)
		if err != nil {
			file.Close()
			return nil, nil, err
		}
		return reader, file, nil
	}
	reader, err := pcapgo.NewReader(file)
	if err != nil {
		file.Close()
		return nil, nil, err
	}
	return reader, file, nil
}

func appendIPv4(buffer []byte, value uint32) []byte {
	buffer = strconv.AppendUint(buffer, uint64(value>>24), 10)
	buffer = append(buffer, '.')
	buffer = strconv.AppendUint(buffer, uint64((value>>16)&0xff), 10)
	buffer = append(buffer, '.')
	buffer = strconv.AppendUint(buffer, uint64((value>>8)&0xff), 10)
	buffer = append(buffer, '.')
	return strconv.AppendUint(buffer, uint64(value&0xff), 10)
}

func parseRulePrefix(fields []string) (uint32, int, error) {
	if len(fields) == 0 {
		return 0, 0, errors.New("empty rule")
	}
	address := fields[0]
	prefixLength := -1
	if strings.Contains(address, "/") {
		ip, network, err := net.ParseCIDR(address)
		if err != nil || ip.To4() == nil {
			return 0, 0, fmt.Errorf("invalid IPv4 CIDR %q", address)
		}
		prefixLength, _ = network.Mask.Size()
		address = ip.String()
	} else {
		if len(fields) < 2 {
			return 0, 0, errors.New("expected '<ip> <prefix-length>'")
		}
		value, err := strconv.Atoi(fields[1])
		if err != nil {
			return 0, 0, fmt.Errorf("invalid prefix length %q", fields[1])
		}
		prefixLength = value
	}
	if prefixLength < 0 || prefixLength > 32 {
		return 0, 0, fmt.Errorf("prefix length out of range: %d", prefixLength)
	}
	ip := net.ParseIP(address).To4()
	if ip == nil {
		return 0, 0, fmt.Errorf("invalid IPv4 address %q", address)
	}
	value := binary.BigEndian.Uint32(ip)
	return value & prefixMask(prefixLength), prefixLength, nil
}

func prefixMask(prefixLength int) uint32 {
	if prefixLength == 0 {
		return 0
	}
	return ^uint32(0) << (32 - prefixLength)
}
