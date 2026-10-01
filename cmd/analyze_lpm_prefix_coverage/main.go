// Command analyze_lpm_prefix_coverage measures how many distinct routing
// prefixes are actually selected by LPM at each prefix length.
package main

import (
	"bufio"
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

const bins = 33

type options struct {
	ruleFile         string
	traceFile        string
	label            string
	outputDir        string
	maxPackets       uint64
	checkpoints      string
	entryLimit       int
	progressInterval uint64
}

type prefixKey struct {
	network uint32
	length  uint8
}

type matcher struct {
	by24        []uint8
	longer      [bins]map[uint32]struct{}
	longLengths []int
	ribCounts   [bins]uint64
}

type snapshot struct {
	packets  uint64
	counts   [bins]uint64
	distinct [bins]uint64
}

type accumulator struct {
	counts      [bins]uint64
	prefixHits  map[prefixKey]uint64
	checkpoints []uint64
	next        int
	snapshots   []snapshot
	processed   uint64
}

type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}

type scanStats struct {
	totalPackets     uint64
	validPackets     uint64
	nonIPv4Packets   uint64
	nonTCPUDPPackets uint64
	parseErrors      uint64
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}
	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		fatalf("create output directory: %v", err)
	}
	m, ruleCount, err := loadRules(opts.ruleFile)
	if err != nil {
		fatalf("load rules: %v", err)
	}
	checkpoints, err := parseCheckpoints(opts.checkpoints, opts.maxPackets)
	if err != nil {
		fatalf("parse checkpoints: %v", err)
	}
	acc := newAccumulator(checkpoints)
	stats, err := scanTrace(opts.traceFile, opts.maxPackets, opts.progressInterval, func(dst uint32) {
		acc.observe(m.match(dst))
	})
	if err != nil {
		fatalf("scan trace: %v", err)
	}
	acc.finish()
	if stats.validPackets == 0 {
		fatalf("trace has no valid IPv4 TCP/UDP packets")
	}
	if err := writeCoverage(filepath.Join(opts.outputDir, "lpm_prefix_coverage.csv"), opts.label, acc.snapshots, m.ribCounts); err != nil {
		fatalf("write coverage CSV: %v", err)
	}
	if err := writeEntries(filepath.Join(opts.outputDir, "lpm_prefix_entries.csv"), opts.label, acc.prefixHits, acc.counts, opts.entryLimit); err != nil {
		fatalf("write entries CSV: %v", err)
	}
	if err := writeSummary(filepath.Join(opts.outputDir, "SUMMARY.md"), opts, stats, ruleCount, acc); err != nil {
		fatalf("write summary: %v", err)
	}
	fmt.Printf("label: %s\nvalid packets: %d\ndistinct selected prefixes: %d\noutput: %s\n",
		opts.label, stats.validPackets, len(acc.prefixHits), opts.outputDir)
}

func parseOptions() (options, error) {
	var opts options
	flag.StringVar(&opts.ruleFile, "rulefile", "", "routing rule file")
	flag.StringVar(&opts.traceFile, "trace", "", "pcap, pcapng, or simulator text trace")
	flag.StringVar(&opts.label, "label", "", "condition label written to CSV")
	flag.StringVar(&opts.outputDir, "output-dir", "", "output directory")
	flag.Uint64Var(&opts.maxPackets, "max", 0, "maximum valid IPv4 TCP/UDP packets; 0 reads all")
	flag.StringVar(&opts.checkpoints, "checkpoints", "100000,300000,1000000,3000000", "comma-separated valid-packet checkpoints")
	flag.IntVar(&opts.entryLimit, "entry-limit", 100, "maximum ranked prefixes per length in entries CSV; 0 writes all")
	flag.Uint64Var(&opts.progressInterval, "progress-interval", 1_000_000, "progress interval in valid packets; 0 disables")
	flag.Parse()
	if opts.ruleFile == "" || opts.traceFile == "" || opts.outputDir == "" {
		return opts, errors.New("--rulefile, --trace, and --output-dir are required")
	}
	if opts.label == "" {
		opts.label = filepath.Base(opts.traceFile)
	}
	if opts.entryLimit < 0 {
		return opts, errors.New("--entry-limit must be non-negative")
	}
	return opts, nil
}

func prefixMask(length int) uint32 {
	if length == 0 {
		return 0
	}
	return ^uint32(0) << (32 - length)
}

func (m *matcher) match(ip uint32) prefixKey {
	for _, length := range m.longLengths {
		network := ip & prefixMask(length)
		if _, ok := m.longer[length][network]; ok {
			return prefixKey{network: network, length: uint8(length)}
		}
	}
	length := int(m.by24[ip>>8])
	return prefixKey{network: ip & prefixMask(length), length: uint8(length)}
}

func loadRules(path string) (*matcher, int, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, 0, err
	}
	defer file.Close()
	m := &matcher{by24: make([]uint8, 1<<24)}
	var short [25][]uint32
	seen := make(map[prefixKey]struct{})
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		line := strings.TrimSpace(strings.SplitN(scanner.Text(), "#", 2)[0])
		if line == "" {
			continue
		}
		network, length, err := parseRulePrefix(strings.Fields(line))
		if err != nil {
			return nil, 0, fmt.Errorf("line %d: %w", lineNumber, err)
		}
		key := prefixKey{network: network, length: uint8(length)}
		if _, duplicate := seen[key]; duplicate {
			continue
		}
		seen[key] = struct{}{}
		m.ribCounts[length]++
		if length <= 24 {
			short[length] = append(short[length], network)
		} else {
			if m.longer[length] == nil {
				m.longer[length] = make(map[uint32]struct{})
			}
			m.longer[length][network] = struct{}{}
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, 0, err
	}
	for length := 0; length <= 24; length++ {
		span := 1 << (24 - length)
		for _, network := range short[length] {
			start := int(network >> 8)
			for offset := 0; offset < span; offset++ {
				m.by24[start+offset] = uint8(length)
			}
		}
	}
	for length := 32; length >= 25; length-- {
		if len(m.longer[length]) != 0 {
			m.longLengths = append(m.longLengths, length)
		}
	}
	return m, len(seen), nil
}

func parseRulePrefix(fields []string) (uint32, int, error) {
	if len(fields) == 0 {
		return 0, 0, errors.New("empty rule")
	}
	address := fields[0]
	length := -1
	if strings.Contains(address, "/") {
		ip, network, err := net.ParseCIDR(address)
		if err != nil || ip.To4() == nil {
			return 0, 0, fmt.Errorf("invalid IPv4 CIDR %q", address)
		}
		length, _ = network.Mask.Size()
		address = ip.String()
	} else {
		if len(fields) < 2 {
			return 0, 0, errors.New("expected '<ip> <prefix-length>'")
		}
		var err error
		length, err = strconv.Atoi(fields[1])
		if err != nil {
			return 0, 0, fmt.Errorf("invalid prefix length %q", fields[1])
		}
	}
	if length < 0 || length > 32 {
		return 0, 0, fmt.Errorf("prefix length out of range: %d", length)
	}
	ip := net.ParseIP(address).To4()
	if ip == nil {
		return 0, 0, fmt.Errorf("invalid IPv4 address %q", address)
	}
	return binary.BigEndian.Uint32(ip) & prefixMask(length), length, nil
}

func parseCheckpoints(value string, maximum uint64) ([]uint64, error) {
	seen := make(map[uint64]struct{})
	for _, part := range strings.Split(value, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		checkpoint, err := strconv.ParseUint(part, 10, 64)
		if err != nil || checkpoint == 0 {
			return nil, fmt.Errorf("invalid checkpoint %q", part)
		}
		if maximum == 0 || checkpoint <= maximum {
			seen[checkpoint] = struct{}{}
		}
	}
	if maximum > 0 {
		seen[maximum] = struct{}{}
	}
	result := make([]uint64, 0, len(seen))
	for checkpoint := range seen {
		result = append(result, checkpoint)
	}
	sort.Slice(result, func(i, j int) bool { return result[i] < result[j] })
	return result, nil
}

func newAccumulator(checkpoints []uint64) *accumulator {
	return &accumulator{prefixHits: make(map[prefixKey]uint64), checkpoints: checkpoints}
}

func (a *accumulator) observe(key prefixKey) {
	a.processed++
	a.counts[key.length]++
	a.prefixHits[key]++
	for a.next < len(a.checkpoints) && a.processed >= a.checkpoints[a.next] {
		a.takeSnapshot(a.checkpoints[a.next])
		a.next++
	}
}

func (a *accumulator) takeSnapshot(packets uint64) {
	item := snapshot{packets: packets, counts: a.counts}
	for key := range a.prefixHits {
		item.distinct[key.length]++
	}
	a.snapshots = append(a.snapshots, item)
}

func (a *accumulator) finish() {
	if a.processed == 0 {
		return
	}
	if len(a.snapshots) == 0 || a.snapshots[len(a.snapshots)-1].packets != a.processed {
		a.takeSnapshot(a.processed)
	}
}

func writeCoverage(path, label string, snapshots []snapshot, ribCounts [bins]uint64) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	w := csv.NewWriter(file)
	defer w.Flush()
	if err := w.Write([]string{"condition", "checkpoint_packets", "lpm_prefix_length", "packet_count", "packet_share", "distinct_lpm_prefixes", "distinct_share", "rib_prefixes", "rib_coverage"}); err != nil {
		return err
	}
	for _, item := range snapshots {
		var distinctTotal uint64
		for _, count := range item.distinct {
			distinctTotal += count
		}
		for length := 0; length < bins; length++ {
			packetShare := float64(item.counts[length]) / float64(item.packets)
			distinctShare := 0.0
			if distinctTotal != 0 {
				distinctShare = float64(item.distinct[length]) / float64(distinctTotal)
			}
			ribCoverage := 0.0
			if ribCounts[length] != 0 {
				ribCoverage = float64(item.distinct[length]) / float64(ribCounts[length])
			}
			row := []string{label, strconv.FormatUint(item.packets, 10), strconv.Itoa(length), strconv.FormatUint(item.counts[length], 10),
				strconv.FormatFloat(packetShare, 'g', 17, 64), strconv.FormatUint(item.distinct[length], 10),
				strconv.FormatFloat(distinctShare, 'g', 17, 64), strconv.FormatUint(ribCounts[length], 10),
				strconv.FormatFloat(ribCoverage, 'g', 17, 64)}
			if err := w.Write(row); err != nil {
				return err
			}
		}
	}
	return w.Error()
}

func writeEntries(path, label string, prefixHits map[prefixKey]uint64, counts [bins]uint64, limit int) error {
	type entry struct {
		key   prefixKey
		count uint64
	}
	byLength := [bins][]entry{}
	for key, count := range prefixHits {
		byLength[key.length] = append(byLength[key.length], entry{key: key, count: count})
	}
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	w := csv.NewWriter(file)
	defer w.Flush()
	if err := w.Write([]string{"condition", "lpm_prefix_length", "network_cidr", "packet_count", "share_within_length", "rank"}); err != nil {
		return err
	}
	for length := 0; length < bins; length++ {
		entries := byLength[length]
		sort.Slice(entries, func(i, j int) bool {
			if entries[i].count != entries[j].count {
				return entries[i].count > entries[j].count
			}
			return entries[i].key.network < entries[j].key.network
		})
		if limit > 0 && len(entries) > limit {
			entries = entries[:limit]
		}
		for index, item := range entries {
			share := float64(item.count) / float64(counts[length])
			ip := make(net.IP, net.IPv4len)
			binary.BigEndian.PutUint32(ip, item.key.network)
			if err := w.Write([]string{label, strconv.Itoa(length), fmt.Sprintf("%s/%d", ip.String(), length),
				strconv.FormatUint(item.count, 10), strconv.FormatFloat(share, 'g', 17, 64), strconv.Itoa(index + 1)}); err != nil {
				return err
			}
		}
	}
	return w.Error()
}

func writeSummary(path string, opts options, stats scanStats, ruleCount int, acc *accumulator) error {
	var text strings.Builder
	fmt.Fprintf(&text, "# LPM prefix coverage: %s\n\n", opts.label)
	fmt.Fprintf(&text, "- trace: `%s`\n- rule: `%s`\n- unique RIB prefixes: %d\n- valid IPv4 TCP/UDP packets: %d\n- distinct selected LPM prefixes: %d\n",
		opts.traceFile, opts.ruleFile, ruleCount, stats.validPackets, len(acc.prefixHits))
	fmt.Fprintf(&text, "- excluded: non-IPv4 %d, non-TCP/UDP %d, parse errors %d\n\n", stats.nonIPv4Packets, stats.nonTCPUDPPackets, stats.parseErrors)
	text.WriteString("`distinct_lpm_prefixes` counts each selected `(network, prefix length)` routing entry once, independent of its packet frequency.\n")
	return os.WriteFile(path, []byte(text.String()), 0o644)
}

func scanTrace(path string, maxPackets, progressInterval uint64, visit func(uint32)) (scanStats, error) {
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
		if !ok || ipv4.DstIP.To4() == nil {
			stats.parseErrors++
			continue
		}
		if ipv4.Protocol != layers.IPProtocolTCP && ipv4.Protocol != layers.IPProtocolUDP {
			stats.nonTCPUDPPackets++
			continue
		}
		stats.validPackets++
		visit(binary.BigEndian.Uint32(ipv4.DstIP.To4()))
		if progressInterval > 0 && stats.validPackets%progressInterval == 0 {
			fmt.Fprintf(os.Stderr, "%s: processed %d valid packets\n", filepath.Base(path), stats.validPackets)
		}
		if maxPackets > 0 && stats.validPackets >= maxPackets {
			break
		}
	}
	return stats, nil
}

func scanTextTrace(path string, maxPackets, progressInterval uint64, visit func(uint32)) (scanStats, error) {
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
		var dstText, proto string
		if len(record) == 7 {
			dstText, proto = record[3], strings.ToLower(record[4])
		} else if len(record) >= 8 {
			dstText, proto = record[3], strings.ToLower(record[5])
		} else {
			stats.parseErrors++
			continue
		}
		if proto != "tcp" && proto != "udp" && proto != "6" && proto != "17" {
			stats.nonTCPUDPPackets++
			continue
		}
		dst := net.ParseIP(dstText).To4()
		if dst == nil {
			stats.parseErrors++
			continue
		}
		stats.validPackets++
		visit(binary.BigEndian.Uint32(dst))
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

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", args...)
	os.Exit(1)
}
