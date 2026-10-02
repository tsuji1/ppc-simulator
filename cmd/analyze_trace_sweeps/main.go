// Command analyze_trace_sweeps finds high-fanout source IPs in a trace.
// A source is a sweep candidate when it sends to many distinct destinations;
// the report also measures whether those destinations are numerically close.
package main

import (
	"embed"
	"encoding/binary"
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcapgo"
)

//go:embed known_hosts.csv
var knownHostsFS embed.FS

type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}

type sourceInfo struct {
	src     uint32
	packets uint64
	dsts    map[uint32]uint64
	ports   map[serviceKey]*serviceStats
	first   float64
	last    float64
}

type serviceKey struct {
	protocol string
	port     uint16
}

type serviceStats struct {
	packets uint64
	dsts    map[uint32]struct{}
}

type knownHost struct {
	IP             string
	Network        string
	Allocation     string
	Organization   string
	ASN            string
	ReverseDNS     string
	Role           string
	Classification string
	EvidenceURL    string
}

type packetObservation struct {
	src       uint32
	dst       uint32
	timestamp float64
	protocol  string
	srcPort   uint16
}

type sweepStats struct {
	adjacentIncrease uint64
	adjacentDecrease uint64
	adjacentNear     uint64
	transitions      uint64
}

type candidate struct {
	info  sourceInfo
	sweep sweepStats
}

type options struct {
	trace      string
	outputDir  string
	maxPackets uint64
	top        int
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}
	infos, valid, err := firstPass(opts)
	if err != nil {
		fatalf("first pass: %v", err)
	}
	candidates := rankCandidates(infos, opts.top)
	if err := secondPass(opts, candidates); err != nil {
		fatalf("second pass: %v", err)
	}
	knownHosts, err := loadKnownHosts()
	if err != nil {
		fatalf("load known hosts: %v", err)
	}
	if err := writeReport(opts, candidates, infos, knownHosts, valid); err != nil {
		fatalf("write report: %v", err)
	}
	fmt.Printf("valid TCP/UDP packets: %d\n", valid)
	for _, item := range candidates {
		fmt.Printf("%s packets=%d unique_dst=%d unique_dst16=%d unique_dst24=%d near_transitions=%d/%d\n",
			ipText(item.info.src), item.info.packets, len(item.info.dsts), uniquePrefixCount(item.info.dsts, 16),
			uniquePrefixCount(item.info.dsts, 24), item.sweep.adjacentNear, item.sweep.transitions)
	}
	fmt.Printf("output: %s\n", opts.outputDir)
}

func parseOptions() (options, error) {
	var opts options
	flag.StringVar(&opts.trace, "trace", "", "pcap or pcapng trace")
	flag.StringVar(&opts.outputDir, "output-dir", "", "output directory")
	flag.Uint64Var(&opts.maxPackets, "max", 0, "maximum valid IPv4 TCP/UDP packets; 0 reads all")
	flag.IntVar(&opts.top, "top", 20, "number of high-fanout source IPs to report")
	flag.Parse()
	if opts.trace == "" || opts.outputDir == "" {
		return opts, errors.New("--trace and --output-dir are required")
	}
	if opts.top <= 0 {
		return opts, errors.New("--top must be positive")
	}
	return opts, nil
}

func firstPass(opts options) (map[uint32]*sourceInfo, uint64, error) {
	infos := make(map[uint32]*sourceInfo)
	knownHosts, err := loadKnownHosts()
	if err != nil {
		return nil, 0, err
	}
	knownIPs := make(map[uint32]struct{}, len(knownHosts))
	for _, host := range knownHosts {
		value, parseErr := parseIPv4(host.IP)
		if parseErr != nil {
			return nil, 0, parseErr
		}
		knownIPs[value] = struct{}{}
	}
	valid := uint64(0)
	err = readPackets(opts.trace, opts.maxPackets, func(packet packetObservation) bool {
		valid++
		item := infos[packet.src]
		if item == nil {
			item = &sourceInfo{src: packet.src, dsts: make(map[uint32]uint64), first: packet.timestamp, last: packet.timestamp}
			if _, ok := knownIPs[packet.src]; ok {
				item.ports = make(map[serviceKey]*serviceStats)
			}
			infos[packet.src] = item
		}
		item.packets++
		item.dsts[packet.dst]++
		item.last = packet.timestamp
		if item.ports != nil {
			key := serviceKey{protocol: packet.protocol, port: packet.srcPort}
			stats := item.ports[key]
			if stats == nil {
				stats = &serviceStats{dsts: make(map[uint32]struct{})}
				item.ports[key] = stats
			}
			stats.packets++
			stats.dsts[packet.dst] = struct{}{}
		}
		return true
	})
	return infos, valid, err
}

func rankCandidates(infos map[uint32]*sourceInfo, top int) []candidate {
	items := make([]candidate, 0, len(infos))
	for _, info := range infos {
		items = append(items, candidate{info: *info})
	}
	sort.Slice(items, func(i, j int) bool {
		if len(items[i].info.dsts) != len(items[j].info.dsts) {
			return len(items[i].info.dsts) > len(items[j].info.dsts)
		}
		if items[i].info.packets != items[j].info.packets {
			return items[i].info.packets > items[j].info.packets
		}
		return items[i].info.src < items[j].info.src
	})
	if len(items) > top {
		items = items[:top]
	}
	return items
}

func secondPass(opts options, candidates []candidate) error {
	wanted := make(map[uint32]int, len(candidates))
	for index := range candidates {
		wanted[candidates[index].info.src] = index
	}
	last := make(map[uint32]uint32, len(candidates))
	err := readPackets(opts.trace, opts.maxPackets, func(packet packetObservation) bool {
		index, ok := wanted[packet.src]
		if !ok {
			return true
		}
		if previous, exists := last[packet.src]; exists {
			candidates[index].sweep.transitions++
			difference := int64(packet.dst) - int64(previous)
			switch {
			case difference == 1:
				candidates[index].sweep.adjacentIncrease++
			case difference == -1:
				candidates[index].sweep.adjacentDecrease++
			}
			if difference >= -256 && difference <= 256 {
				candidates[index].sweep.adjacentNear++
			}
		}
		last[packet.src] = packet.dst
		return true
	})
	return err
}

func readPackets(path string, maxPackets uint64, visit func(packetObservation) bool) error {
	if strings.ToLower(filepath.Ext(path)) != ".pcapng" {
		// This command intentionally handles binary captures only; the sweep
		// question concerns the non-anonymous PCAP files.
	}
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	var reader packetReader
	if strings.EqualFold(filepath.Ext(path), ".pcapng") {
		reader, err = pcapgo.NewNgReader(file, pcapgo.DefaultNgReaderOptions)
	} else {
		reader, err = pcapgo.NewReader(file)
	}
	if err != nil {
		return err
	}
	decodeOptions := gopacket.DecodeOptions{Lazy: false, NoCopy: true}
	valid := uint64(0)
	for {
		data, captureInfo, readErr := reader.ZeroCopyReadPacketData()
		if errors.Is(readErr, io.EOF) {
			return nil
		}
		if readErr != nil {
			return readErr
		}
		packet := gopacket.NewPacket(data, reader.LinkType(), decodeOptions)
		layer := packet.Layer(layers.LayerTypeIPv4)
		if layer == nil {
			continue
		}
		ipv4, ok := layer.(*layers.IPv4)
		if !ok || ipv4.SrcIP.To4() == nil || ipv4.DstIP.To4() == nil {
			continue
		}
		if ipv4.Protocol != layers.IPProtocolTCP && ipv4.Protocol != layers.IPProtocolUDP {
			continue
		}
		protocol := ""
		var srcPort uint16
		switch ipv4.Protocol {
		case layers.IPProtocolTCP:
			transport, ok := packet.Layer(layers.LayerTypeTCP).(*layers.TCP)
			if !ok {
				continue
			}
			protocol = "tcp"
			srcPort = uint16(transport.SrcPort)
		case layers.IPProtocolUDP:
			transport, ok := packet.Layer(layers.LayerTypeUDP).(*layers.UDP)
			if !ok {
				continue
			}
			protocol = "udp"
			srcPort = uint16(transport.SrcPort)
		}
		valid++
		if !visit(packetObservation{
			src:       binary.BigEndian.Uint32(ipv4.SrcIP.To4()),
			dst:       binary.BigEndian.Uint32(ipv4.DstIP.To4()),
			timestamp: float64(captureInfo.Timestamp.UnixNano()) / 1e9,
			protocol:  protocol,
			srcPort:   srcPort,
		}) {
			return nil
		}
		if maxPackets > 0 && valid >= maxPackets {
			return nil
		}
	}
}

func uniquePrefixCount(dsts map[uint32]uint64, length uint) int {
	seen := make(map[uint32]struct{})
	var mask uint32
	if length == 0 {
		mask = 0
	} else {
		mask = ^uint32(0) << (32 - length)
	}
	for dst := range dsts {
		seen[dst&mask] = struct{}{}
	}
	return len(seen)
}

func writeReport(opts options, candidates []candidate, infos map[uint32]*sourceInfo, knownHosts []knownHost, valid uint64) error {
	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		return err
	}
	file, err := os.Create(filepath.Join(opts.outputDir, "sweep_sources.csv"))
	if err != nil {
		return err
	}
	w := csv.NewWriter(file)
	if err := w.Write([]string{"rank", "source_ip", "packets", "unique_dst", "unique_dst16", "unique_dst24", "first_epoch", "last_epoch", "span_seconds", "adjacent_increase", "adjacent_decrease", "adjacent_abs_delta_le_256", "source_consecutive_transitions", "known_organization", "known_asn", "known_reverse_dns", "known_role"}); err != nil {
		file.Close()
		return err
	}
	for index, item := range candidates {
		span := item.info.last - item.info.first
		host := findKnownHost(knownHosts, ipText(item.info.src))
		if err := w.Write([]string{strconv.Itoa(index + 1), ipText(item.info.src), strconv.FormatUint(item.info.packets, 10), strconv.Itoa(len(item.info.dsts)),
			strconv.Itoa(uniquePrefixCount(item.info.dsts, 16)), strconv.Itoa(uniquePrefixCount(item.info.dsts, 24)),
			strconv.FormatFloat(item.info.first, 'f', 6, 64), strconv.FormatFloat(item.info.last, 'f', 6, 64), strconv.FormatFloat(span, 'f', 6, 64),
			strconv.FormatUint(item.sweep.adjacentIncrease, 10), strconv.FormatUint(item.sweep.adjacentDecrease, 10), strconv.FormatUint(item.sweep.adjacentNear, 10), strconv.FormatUint(item.sweep.transitions, 10),
			host.Organization, host.ASN, host.ReverseDNS, host.Role}); err != nil {
			file.Close()
			return err
		}
		destinationFile, err := os.Create(filepath.Join(opts.outputDir, fmt.Sprintf("destinations_%02d_%s.csv", index+1, strings.ReplaceAll(ipText(item.info.src), ".", "_"))))
		if err != nil {
			file.Close()
			return err
		}
		destinationWriter := csv.NewWriter(destinationFile)
		if err := destinationWriter.Write([]string{"destination_ip", "packets_from_source"}); err != nil {
			destinationFile.Close()
			file.Close()
			return err
		}
		dsts := make([]uint32, 0, len(item.info.dsts))
		for dst := range item.info.dsts {
			dsts = append(dsts, dst)
		}
		sort.Slice(dsts, func(i, j int) bool { return dsts[i] < dsts[j] })
		for _, dst := range dsts {
			if err := destinationWriter.Write([]string{ipText(dst), strconv.FormatUint(item.info.dsts[dst], 10)}); err != nil {
				destinationFile.Close()
				file.Close()
				return err
			}
		}
		destinationWriter.Flush()
		destinationFile.Close()
	}
	w.Flush()
	if err := w.Error(); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := writeKnownHostReport(opts.outputDir, infos, knownHosts); err != nil {
		return err
	}
	return writeSummary(opts, infos, knownHosts, valid)
}

func loadKnownHosts() ([]knownHost, error) {
	file, err := knownHostsFS.Open("known_hosts.csv")
	if err != nil {
		return nil, err
	}
	defer file.Close()
	reader := csv.NewReader(file)
	rows, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 || len(rows[0]) != 9 {
		return nil, errors.New("known_hosts.csv has an invalid header")
	}
	hosts := make([]knownHost, 0, len(rows)-1)
	for rowIndex, row := range rows[1:] {
		if len(row) != 9 {
			return nil, fmt.Errorf("known_hosts.csv row %d: expected 9 columns, got %d", rowIndex+2, len(row))
		}
		if _, err := parseIPv4(row[0]); err != nil {
			return nil, fmt.Errorf("known_hosts.csv row %d: %w", rowIndex+2, err)
		}
		hosts = append(hosts, knownHost{row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8]})
	}
	return hosts, nil
}

func parseIPv4(text string) (uint32, error) {
	ip := net.ParseIP(text).To4()
	if ip == nil {
		return 0, fmt.Errorf("invalid IPv4 address %q", text)
	}
	return binary.BigEndian.Uint32(ip), nil
}

func findKnownHost(hosts []knownHost, ip string) knownHost {
	for _, host := range hosts {
		if host.IP == ip {
			return host
		}
	}
	return knownHost{}
}

func writeKnownHostReport(outputDir string, infos map[uint32]*sourceInfo, hosts []knownHost) error {
	path := filepath.Join(outputDir, "known_research_hosts.csv")
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	w := csv.NewWriter(file)
	header := []string{"source_ip", "observed_as_source", "packets", "unique_dst", "unique_dst16", "unique_dst24", "first_epoch", "last_epoch", "span_seconds", "top_source_services", "network", "allocation", "organization", "asn", "reverse_dns", "role", "classification", "evidence_url"}
	if err := w.Write(header); err != nil {
		file.Close()
		return err
	}
	for _, host := range hosts {
		value, _ := parseIPv4(host.IP)
		info := infos[value]
		row := []string{host.IP, "false", "0", "0", "0", "0", "", "", "", "", host.Network, host.Allocation, host.Organization, host.ASN, host.ReverseDNS, host.Role, host.Classification, host.EvidenceURL}
		if info != nil {
			row[1] = "true"
			row[2] = strconv.FormatUint(info.packets, 10)
			row[3] = strconv.Itoa(len(info.dsts))
			row[4] = strconv.Itoa(uniquePrefixCount(info.dsts, 16))
			row[5] = strconv.Itoa(uniquePrefixCount(info.dsts, 24))
			row[6] = strconv.FormatFloat(info.first, 'f', 6, 64)
			row[7] = strconv.FormatFloat(info.last, 'f', 6, 64)
			row[8] = strconv.FormatFloat(info.last-info.first, 'f', 6, 64)
			row[9] = formatTopServices(info.ports, 5)
		}
		if err := w.Write(row); err != nil {
			file.Close()
			return err
		}
	}
	w.Flush()
	if err := w.Error(); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

func formatTopServices(ports map[serviceKey]*serviceStats, limit int) string {
	type item struct {
		key   serviceKey
		stats *serviceStats
	}
	items := make([]item, 0, len(ports))
	for key, stats := range ports {
		items = append(items, item{key, stats})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].stats.packets != items[j].stats.packets {
			return items[i].stats.packets > items[j].stats.packets
		}
		if items[i].key.protocol != items[j].key.protocol {
			return items[i].key.protocol < items[j].key.protocol
		}
		return items[i].key.port < items[j].key.port
	})
	if len(items) > limit {
		items = items[:limit]
	}
	parts := make([]string, 0, len(items))
	for _, entry := range items {
		parts = append(parts, fmt.Sprintf("%s/%d:%d packets,%d dst", entry.key.protocol, entry.key.port, entry.stats.packets, len(entry.stats.dsts)))
	}
	return strings.Join(parts, "; ")
}

func writeSummary(opts options, infos map[uint32]*sourceInfo, hosts []knownHost, valid uint64) error {
	var builder strings.Builder
	fmt.Fprintf(&builder, "# Non-anonymous trace sweep candidates\n\n- trace: `%s`\n- valid IPv4 TCP/UDP packets: %d\n- ranking: distinct destination IP count per source\n- `adjacent_*` counts numerically consecutive destinations in the source's packet order (not proof of a scanner).\n", opts.trace, valid)
	builder.WriteString("\n## Known university/research-network hosts\n\n| IP | observed packets | unique destinations | organization / ASN | reverse DNS | role |\n|---|---:|---:|---|---|---|\n")
	for _, host := range hosts {
		value, _ := parseIPv4(host.IP)
		packets, destinations := uint64(0), 0
		if info := infos[value]; info != nil {
			packets, destinations = info.packets, len(info.dsts)
		}
		fmt.Fprintf(&builder, "| `%s` | %d | %d | %s / %s | `%s` | %s |\n", host.IP, packets, destinations, host.Organization, host.ASN, host.ReverseDNS, host.Role)
	}
	builder.WriteString("\nThe registry and reverse-DNS fields provide attribution context, not a traffic verdict. High fan-out from a known mirror or university host can be ordinary distribution traffic; ports, packet direction, and payload/context must still be checked before calling it a scanner. See `known_research_hosts.csv` for source-port evidence and provenance links.\n")
	return os.WriteFile(filepath.Join(opts.outputDir, "SUMMARY.md"), []byte(builder.String()), 0o644)
}

func ipText(value uint32) string {
	ip := make(net.IP, net.IPv4len)
	binary.BigEndian.PutUint32(ip, value)
	return ip.String()
}

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", args...)
	os.Exit(1)
}
