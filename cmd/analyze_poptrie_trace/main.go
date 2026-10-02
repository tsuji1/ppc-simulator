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
	"time"

	"test-module/ipaddress"
	"test-module/routingtable"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcap"
	"github.com/tsuji1/go-patricia/patricia"
)

type options struct {
	ruleFile         string
	traceFile        string
	outputDir        string
	maxPackets       uint64
	topN             int
	progressInterval uint64
}

type summary struct {
	StartedAt              time.Time
	FinishedAt             time.Time
	RuleFile               string
	TraceFile              string
	Processed              uint64
	ParseErrors            uint64
	DistinctDestinations   int
	RunCount               uint64
	MaxRunLength           uint64
	RunLengthTotal         uint64
	MatchedPrefixLengthSum uint64
	BinaryRadixDepthSum    uint64
	LPCTrieDepthSum        uint64
	DepthGreaterThan18     uint64
	DepthGreaterThan24     uint64
}

type analyzer struct {
	rt                         *routingtable.RoutingTablePatriciaTrie
	summary                    summary
	matchedPrefixLengthCounts  [33]uint64
	binaryRadixDepthCounts     [33]uint64
	lpcTrieDepthCounts         [33]uint64
	nextHopCounts              map[string]uint64
	distinctDestinations       map[uint32]struct{}
	previousDestination        uint32
	hasPreviousDestination     bool
	currentRunLength           uint64
	unsupportedDepthValueCount uint64
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}
	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		fatalf("create output dir: %v", err)
	}

	rt, err := loadRoutingTable(opts.ruleFile)
	if err != nil {
		fatalf("%v", err)
	}

	a := &analyzer{
		rt:                   rt,
		nextHopCounts:        make(map[string]uint64),
		distinctDestinations: make(map[uint32]struct{}),
		summary: summary{
			StartedAt: time.Now(),
			RuleFile:  opts.ruleFile,
			TraceFile: opts.traceFile,
		},
	}

	if err := scanTrace(opts, a); err != nil {
		fatalf("%v", err)
	}
	a.finishRun()
	a.summary.FinishedAt = time.Now()
	a.summary.DistinctDestinations = len(a.distinctDestinations)

	if err := writeOutputs(opts, a); err != nil {
		fatalf("%v", err)
	}
	fmt.Fprintf(os.Stderr, "wrote Poptrie trace LPM report to %s\n", opts.outputDir)
}

func parseOptions() (options, error) {
	opts := options{}
	flag.StringVar(&opts.ruleFile, "rulefile", "", "routing rule file")
	flag.StringVar(&opts.traceFile, "trace", "", "trace file (.dstip, simulator CSV, pcap, or pcapng)")
	flag.StringVar(&opts.outputDir, "output-dir", "", "output directory")
	flag.Uint64Var(&opts.maxPackets, "max", 0, "maximum packets to process; 0 reads all")
	flag.IntVar(&opts.topN, "top-n", 100, "number of next hops to include")
	flag.Uint64Var(&opts.progressInterval, "progress-interval", 1_000_000, "stderr progress interval; 0 disables")
	flag.Parse()
	if opts.ruleFile == "" {
		return opts, errors.New("--rulefile is required")
	}
	if opts.traceFile == "" {
		return opts, errors.New("--trace is required")
	}
	if opts.outputDir == "" {
		return opts, errors.New("--output-dir is required")
	}
	if opts.topN <= 0 {
		return opts, errors.New("--top-n must be positive")
	}
	return opts, nil
}

func loadRoutingTable(ruleFile string) (*routingtable.RoutingTablePatriciaTrie, error) {
	fp, err := os.Open(ruleFile)
	if err != nil {
		return nil, fmt.Errorf("open rule file: %w", err)
	}
	defer fp.Close()
	rt := routingtable.NewRoutingTablePatriciaTrie()
	rt.ReadRule(fp)
	return rt, nil
}

func scanTrace(opts options, a *analyzer) error {
	if strings.EqualFold(filepath.Ext(opts.traceFile), ".dstip") {
		fp, err := os.Open(opts.traceFile)
		if err != nil {
			return fmt.Errorf("open trace file: %w", err)
		}
		defer fp.Close()
		return scanDstIPTrace(fp, opts, a)
	}
	if isPcapPath(opts.traceFile) {
		return scanPcapTrace(opts, a)
	}

	fp, err := os.Open(opts.traceFile)
	if err != nil {
		return fmt.Errorf("open trace file: %w", err)
	}
	defer fp.Close()
	return scanSimulatorCSVTrace(fp, opts, a)
}

func isPcapPath(path string) bool {
	ext := strings.ToLower(filepath.Ext(path))
	return ext == ".pcap" || ext == ".pcapng"
}

func scanDstIPTrace(fp *os.File, opts options, a *analyzer) error {
	scanner := bufio.NewScanner(fp)
	scanner.Buffer(make([]byte, 1024), 1024*1024)
	for scanner.Scan() {
		if opts.maxPackets > 0 && a.summary.Processed >= opts.maxPackets {
			break
		}
		dst, err := parseIPv4(strings.TrimSpace(scanner.Text()))
		if err != nil {
			a.summary.ParseErrors++
			continue
		}
		a.add(dst, opts.progressInterval)
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("scan dstip trace: %w", err)
	}
	return nil
}

func scanSimulatorCSVTrace(fp *os.File, opts options, a *analyzer) error {
	reader := csv.NewReader(fp)
	reader.FieldsPerRecord = -1
	reader.ReuseRecord = true
	for {
		if opts.maxPackets > 0 && a.summary.Processed >= opts.maxPackets {
			break
		}
		record, err := reader.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			a.summary.ParseErrors++
			continue
		}
		if len(record) == 1 {
			record = strings.Fields(record[0])
		}
		dstField := ""
		switch {
		case len(record) == 1:
			dstField = record[0]
		case len(record) >= 4:
			dstField = record[3]
		default:
			a.summary.ParseErrors++
			continue
		}
		dst, err := parseIPv4(strings.TrimSpace(dstField))
		if err != nil {
			a.summary.ParseErrors++
			continue
		}
		a.add(dst, opts.progressInterval)
	}
	return nil
}

func scanPcapTrace(opts options, a *analyzer) error {
	handle, err := pcap.OpenOffline(opts.traceFile)
	if err != nil {
		return fmt.Errorf("open pcap trace: %w", err)
	}
	defer handle.Close()

	packetSource := gopacket.NewPacketSource(handle, handle.LinkType())
	packetSource.DecodeOptions = gopacket.DecodeOptions{Lazy: false, NoCopy: true}
	for packet := range packetSource.Packets() {
		if opts.maxPackets > 0 && a.summary.Processed >= opts.maxPackets {
			break
		}
		if packet.ErrorLayer() != nil {
			a.summary.ParseErrors++
		}
		ipLayer := packet.Layer(layers.LayerTypeIPv4)
		if ipLayer == nil {
			continue
		}
		ipv4, ok := ipLayer.(*layers.IPv4)
		if !ok || ipv4.DstIP.To4() == nil {
			a.summary.ParseErrors++
			continue
		}
		a.add(binary.BigEndian.Uint32(ipv4.DstIP.To4()), opts.progressInterval)
	}
	return nil
}

func parseIPv4(value string) (uint32, error) {
	ip := net.ParseIP(value).To4()
	if ip == nil {
		return 0, fmt.Errorf("invalid IPv4 address %q", value)
	}
	return binary.BigEndian.Uint32(ip), nil
}

func (a *analyzer) add(dst uint32, progressInterval uint64) {
	dstIP := ipaddress.NewIPaddress(dst)
	matchedPrefix, item := a.rt.SearchLongestIP(dstIP, 32)
	matchedLen := len(matchedPrefix)
	if matchedLen >= 0 && matchedLen <= 32 {
		a.matchedPrefixLengthCounts[matchedLen]++
	}

	binaryDepth := binaryRadixDepth(a.rt, dstIP)
	if binaryDepth >= 0 && binaryDepth <= 32 {
		a.binaryRadixDepthCounts[binaryDepth]++
	} else {
		a.unsupportedDepthValueCount++
	}
	if binaryDepth > 18 {
		a.summary.DepthGreaterThan18++
	}
	if binaryDepth > 24 {
		a.summary.DepthGreaterThan24++
	}

	lpcDepth := a.rt.GetDepth(dst)
	if lpcDepth >= 0 && lpcDepth <= 32 {
		a.lpcTrieDepthCounts[lpcDepth]++
	}

	a.summary.Processed++
	a.summary.MatchedPrefixLengthSum += uint64(matchedLen)
	if binaryDepth > 0 {
		a.summary.BinaryRadixDepthSum += uint64(binaryDepth)
	}
	if lpcDepth > 0 {
		a.summary.LPCTrieDepthSum += uint64(lpcDepth)
	}
	a.distinctDestinations[dst] = struct{}{}
	a.addRun(dst)

	nextHop := fmt.Sprintf("%v", item)
	if data, ok := item.(routingtable.Data); ok {
		nextHop = data.NextHop
	}
	a.nextHopCounts[nextHop]++

	if progressInterval > 0 && a.summary.Processed%progressInterval == 0 {
		fmt.Fprintf(os.Stderr, "processed %d packets\n", a.summary.Processed)
	}
}

func binaryRadixDepth(rt *routingtable.RoutingTablePatriciaTrie, dstIP ipaddress.IPaddress) int {
	depth := 0
	for i := 1; i <= 32; i++ {
		prefix := patricia.Prefix(dstIP.MaskedBitString(i))
		if !rt.RoutingTablePatriciaTrie.MatchSubtree(prefix) {
			break
		}
		depth = i
	}
	return depth
}

func (a *analyzer) addRun(dst uint32) {
	if !a.hasPreviousDestination {
		a.previousDestination = dst
		a.hasPreviousDestination = true
		a.currentRunLength = 1
		return
	}
	if dst == a.previousDestination {
		a.currentRunLength++
		return
	}
	a.finishRun()
	a.previousDestination = dst
	a.currentRunLength = 1
}

func (a *analyzer) finishRun() {
	if a.currentRunLength == 0 {
		return
	}
	a.summary.RunCount++
	a.summary.RunLengthTotal += a.currentRunLength
	if a.currentRunLength > a.summary.MaxRunLength {
		a.summary.MaxRunLength = a.currentRunLength
	}
	a.currentRunLength = 0
}

type countRow struct {
	Key   string
	Count uint64
}

func sortedCountRowsFromArray(counts [33]uint64) []countRow {
	rows := make([]countRow, 0, len(counts))
	for key, count := range counts {
		if count == 0 {
			continue
		}
		rows = append(rows, countRow{Key: strconv.Itoa(key), Count: count})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Count != rows[j].Count {
			return rows[i].Count > rows[j].Count
		}
		return rows[i].Key < rows[j].Key
	})
	return rows
}

func sortedCountRowsFromMap(counts map[string]uint64) []countRow {
	rows := make([]countRow, 0, len(counts))
	for key, count := range counts {
		rows = append(rows, countRow{Key: key, Count: count})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Count != rows[j].Count {
			return rows[i].Count > rows[j].Count
		}
		return rows[i].Key < rows[j].Key
	})
	return rows
}

func writeOutputs(opts options, a *analyzer) error {
	if err := writeSummaryCSV(filepath.Join(opts.outputDir, "summary.csv"), a); err != nil {
		return err
	}
	if err := writeDistributionCSV(filepath.Join(opts.outputDir, "matched_prefix_length_distribution.csv"), "matched_prefix_length", sortedCountRowsFromArray(a.matchedPrefixLengthCounts), a.summary.Processed); err != nil {
		return err
	}
	if err := writeDistributionCSV(filepath.Join(opts.outputDir, "binary_radix_depth_distribution.csv"), "binary_radix_depth", sortedCountRowsFromArray(a.binaryRadixDepthCounts), a.summary.Processed); err != nil {
		return err
	}
	if err := writeDistributionCSV(filepath.Join(opts.outputDir, "lpc_trie_depth_distribution.csv"), "lpc_trie_depth", sortedCountRowsFromArray(a.lpcTrieDepthCounts), a.summary.Processed); err != nil {
		return err
	}
	nextHopRows := sortedCountRowsFromMap(a.nextHopCounts)
	if len(nextHopRows) > opts.topN {
		nextHopRows = nextHopRows[:opts.topN]
	}
	if err := writeDistributionCSV(filepath.Join(opts.outputDir, "next_hop_top.csv"), "next_hop", nextHopRows, a.summary.Processed); err != nil {
		return err
	}
	if err := writeSummaryMarkdown(filepath.Join(opts.outputDir, "summary.md"), opts, a); err != nil {
		return err
	}
	return nil
}

func writeSummaryCSV(path string, a *analyzer) error {
	file, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create summary csv: %w", err)
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	rows := [][]string{
		{"metric", "value"},
		{"trace", a.summary.TraceFile},
		{"rule", a.summary.RuleFile},
		{"started_at", a.summary.StartedAt.Format(time.RFC3339)},
		{"finished_at", a.summary.FinishedAt.Format(time.RFC3339)},
		{"processed", strconv.FormatUint(a.summary.Processed, 10)},
		{"parse_errors", strconv.FormatUint(a.summary.ParseErrors, 10)},
		{"distinct_destinations", strconv.Itoa(a.summary.DistinctDestinations)},
		{"run_count", strconv.FormatUint(a.summary.RunCount, 10)},
		{"max_run_length", strconv.FormatUint(a.summary.MaxRunLength, 10)},
		{"average_run_length", fmt.Sprintf("%.6f", averageRunLength(a.summary))},
		{"matched_prefix_length_avg", fmt.Sprintf("%.6f", averageUint64(a.summary.MatchedPrefixLengthSum, a.summary.Processed))},
		{"binary_radix_depth_avg", fmt.Sprintf("%.6f", averageUint64(a.summary.BinaryRadixDepthSum, a.summary.Processed))},
		{"lpc_trie_depth_avg", fmt.Sprintf("%.6f", averageUint64(a.summary.LPCTrieDepthSum, a.summary.Processed))},
		{"depth_gt_18_count", strconv.FormatUint(a.summary.DepthGreaterThan18, 10)},
		{"depth_gt_18_ratio", fmt.Sprintf("%.12f", ratio(a.summary.DepthGreaterThan18, a.summary.Processed))},
		{"depth_gt_24_count", strconv.FormatUint(a.summary.DepthGreaterThan24, 10)},
		{"depth_gt_24_ratio", fmt.Sprintf("%.12f", ratio(a.summary.DepthGreaterThan24, a.summary.Processed))},
		{"unsupported_depth_value_count", strconv.FormatUint(a.unsupportedDepthValueCount, 10)},
	}
	return writer.WriteAll(rows)
}

func writeDistributionCSV(path string, keyName string, rows []countRow, total uint64) error {
	file, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create distribution csv: %w", err)
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	if err := writer.Write([]string{"rank", keyName, "count", "ratio"}); err != nil {
		return err
	}
	for rank, row := range rows {
		if err := writer.Write([]string{
			strconv.Itoa(rank + 1),
			row.Key,
			strconv.FormatUint(row.Count, 10),
			fmt.Sprintf("%.12f", ratio(row.Count, total)),
		}); err != nil {
			return err
		}
	}
	return nil
}

func writeSummaryMarkdown(path string, opts options, a *analyzer) error {
	lines := []string{
		"# Poptrie Synthetic Trace LPM Report",
		"",
		"## Input",
		"",
		fmt.Sprintf("- trace: `%s`", a.summary.TraceFile),
		fmt.Sprintf("- rule: `%s`", a.summary.RuleFile),
		fmt.Sprintf("- processed: `%d`", a.summary.Processed),
		fmt.Sprintf("- parse errors: `%d`", a.summary.ParseErrors),
		"",
		"## Summary",
		"",
		"| metric | value |",
		"| --- | ---: |",
		fmt.Sprintf("| distinct destinations | %d |", a.summary.DistinctDestinations),
		fmt.Sprintf("| max run length | %d |", a.summary.MaxRunLength),
		fmt.Sprintf("| average run length | %.6f |", averageRunLength(a.summary)),
		fmt.Sprintf("| matched prefix length avg | %.6f |", averageUint64(a.summary.MatchedPrefixLengthSum, a.summary.Processed)),
		fmt.Sprintf("| binary radix depth avg | %.6f |", averageUint64(a.summary.BinaryRadixDepthSum, a.summary.Processed)),
		fmt.Sprintf("| LPC trie depth avg | %.6f |", averageUint64(a.summary.LPCTrieDepthSum, a.summary.Processed)),
		fmt.Sprintf("| depth > 18 | %.4f |", ratio(a.summary.DepthGreaterThan18, a.summary.Processed)),
		fmt.Sprintf("| depth > 24 | %.4f |", ratio(a.summary.DepthGreaterThan24, a.summary.Processed)),
		"",
		"## Files",
		"",
		"- `summary.csv`",
		"- `matched_prefix_length_distribution.csv`",
		"- `binary_radix_depth_distribution.csv`",
		"- `lpc_trie_depth_distribution.csv`",
		"- `next_hop_top.csv`",
		"",
		"## Rerun",
		"",
		"```bash",
		"go run ./cmd/analyze_poptrie_trace \\",
		fmt.Sprintf("  --rulefile %s \\", opts.ruleFile),
		fmt.Sprintf("  --trace %s \\", opts.traceFile),
		fmt.Sprintf("  --output-dir %s", opts.outputDir),
		"```",
		"",
	}
	return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o644)
}

func averageRunLength(sum summary) float64 {
	if sum.RunCount == 0 {
		return 0
	}
	return float64(sum.RunLengthTotal) / float64(sum.RunCount)
}

func averageUint64(value uint64, total uint64) float64 {
	if total == 0 {
		return 0
	}
	return float64(value) / float64(total)
}

func ratio(value uint64, total uint64) float64 {
	if total == 0 {
		return 0
	}
	return float64(value) / float64(total)
}

func fatalf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
