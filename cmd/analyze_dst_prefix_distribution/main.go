package main

import (
	"bufio"
	"encoding/binary"
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"html"
	"io"
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
	outputDir        string
	prefixLengths    []int
	topN             int
	progressInterval uint64
}

type summary struct {
	Trace             string
	StartedAt         time.Time
	FinishedAt        time.Time
	Format            string
	LinkType          string
	SnapLen           string
	TotalPackets      uint64
	IPv4Packets       uint64
	NonIPv4Packets    uint64
	ParseErrorPackets uint64
	ReadErrorPackets  uint64
}

type prefixRow struct {
	PrefixLength int
	Prefix       uint32
	Count        uint64
	Ratio        float64
}

type concentrationRow struct {
	PrefixLength   int
	UniquePrefixes int
	TopCounts      map[int]uint64
	TopRatios      map[int]float64
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}

	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		fatalf("create output dir: %v", err)
	}

	counts := make(map[int]map[uint32]uint64, len(opts.prefixLengths))
	for _, prefixLength := range opts.prefixLengths {
		counts[prefixLength] = make(map[uint32]uint64)
	}

	sum, err := analyze(opts, counts)
	if err != nil {
		fatalf("%v", err)
	}

	concentrations := make([]concentrationRow, 0, len(opts.prefixLengths))
	for _, prefixLength := range opts.prefixLengths {
		rows := buildRows(prefixLength, counts[prefixLength], sum.IPv4Packets)

		if err := writePrefixCSV(filepath.Join(opts.outputDir, fmt.Sprintf("prefix_%d.csv", prefixLength)), rows); err != nil {
			fatalf("write prefix csv: %v", err)
		}
		if err := writeTopSVG(filepath.Join(opts.outputDir, fmt.Sprintf("prefix_%d_top%d.svg", prefixLength, opts.topN)), rows, opts.topN, sum.Trace, prefixLength); err != nil {
			fatalf("write svg plot: %v", err)
		}
		concentrations = append(concentrations, buildConcentration(prefixLength, rows, sum.IPv4Packets))
	}

	if err := writeSummaryCSV(filepath.Join(opts.outputDir, "summary.csv"), sum, opts.prefixLengths); err != nil {
		fatalf("write summary csv: %v", err)
	}
	if err := writeConcentrationCSV(filepath.Join(opts.outputDir, "concentration.csv"), concentrations); err != nil {
		fatalf("write concentration csv: %v", err)
	}
	if err := writeSummaryMarkdown(filepath.Join(opts.outputDir, "summary.md"), sum, opts, concentrations); err != nil {
		fatalf("write summary markdown: %v", err)
	}
	if err := chownOutputTreeIfSudo(opts.outputDir); err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not restore output ownership after sudo: %v\n", err)
	}

	fmt.Fprintf(os.Stderr, "wrote destination prefix distribution report to %s\n", opts.outputDir)
}

func parseOptions() (options, error) {
	var rawPrefixLengths string
	opts := options{}

	flag.StringVar(&opts.trace, "trace", "", "pcap trace path")
	flag.StringVar(&rawPrefixLengths, "prefix-lengths", "8,16,24,32", "comma-separated IPv4 prefix lengths")
	flag.StringVar(&opts.outputDir, "output-dir", "", "output directory")
	flag.IntVar(&opts.topN, "top-n", 50, "number of prefixes to include in each SVG plot")
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

	prefixLengths, err := parsePrefixLengths(rawPrefixLengths)
	if err != nil {
		return opts, err
	}
	opts.prefixLengths = prefixLengths
	return opts, nil
}

func parsePrefixLengths(raw string) ([]int, error) {
	seen := map[int]bool{}
	var prefixLengths []int
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		prefixLength, err := strconv.Atoi(part)
		if err != nil {
			return nil, fmt.Errorf("invalid prefix length %q", part)
		}
		if prefixLength < 0 || prefixLength > 32 {
			return nil, fmt.Errorf("prefix length must be in 0..32: %d", prefixLength)
		}
		if !seen[prefixLength] {
			seen[prefixLength] = true
			prefixLengths = append(prefixLengths, prefixLength)
		}
	}
	if len(prefixLengths) == 0 {
		return nil, errors.New("--prefix-lengths must include at least one length")
	}
	sort.Ints(prefixLengths)
	return prefixLengths, nil
}

func analyze(opts options, counts map[int]map[uint32]uint64) (summary, error) {
	if isTextTrace(opts.trace) {
		return analyzeTextTrace(opts, counts)
	}
	return analyzeCapture(opts, counts)
}

func analyzeCapture(opts options, counts map[int]map[uint32]uint64) (summary, error) {
	reader, closer, format, snapLen, err := openCapture(opts.trace)
	if err != nil {
		return summary{}, fmt.Errorf("open trace: %w", err)
	}
	defer closer.Close()

	sum := summary{
		Trace:     opts.trace,
		StartedAt: time.Now(),
		Format:    format,
		LinkType:  reader.LinkType().String(),
		SnapLen:   snapLen,
	}

	decodeOptions := gopacket.DecodeOptions{Lazy: false, NoCopy: true}
	linkType := reader.LinkType()

	for {
		data, _, err := reader.ZeroCopyReadPacketData()
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			sum.ReadErrorPackets++
			return sum, fmt.Errorf("read packet after %d packets: %w", sum.TotalPackets, err)
		}

		sum.TotalPackets++
		if opts.progressInterval > 0 && sum.TotalPackets%opts.progressInterval == 0 {
			fmt.Fprintf(os.Stderr, "processed %d packets (IPv4: %d)\n", sum.TotalPackets, sum.IPv4Packets)
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
		if !ok || len(ipv4.DstIP.To4()) != 4 {
			sum.ParseErrorPackets++
			sum.NonIPv4Packets++
			continue
		}

		sum.IPv4Packets++
		dst := binary.BigEndian.Uint32(ipv4.DstIP.To4())
		for prefixLength, prefixCounts := range counts {
			prefixCounts[maskPrefix(dst, prefixLength)]++
		}
	}

	sum.FinishedAt = time.Now()
	return sum, nil
}

func analyzeTextTrace(opts options, counts map[int]map[uint32]uint64) (summary, error) {
	file, err := os.Open(opts.trace)
	if err != nil {
		return summary{}, fmt.Errorf("open text trace: %w", err)
	}
	defer file.Close()

	sum := summary{
		Trace:     opts.trace,
		StartedAt: time.Now(),
		Format:    "text-5tuple",
		LinkType:  "n/a",
		SnapLen:   "n/a",
	}

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		sum.TotalPackets++
		if opts.progressInterval > 0 && sum.TotalPackets%opts.progressInterval == 0 {
			fmt.Fprintf(os.Stderr, "processed %d packets (IPv4: %d)\n", sum.TotalPackets, sum.IPv4Packets)
		}

		dst, err := parseTextTraceDstIP(line)
		if err != nil {
			sum.ParseErrorPackets++
			sum.NonIPv4Packets++
			continue
		}

		sum.IPv4Packets++
		for prefixLength, prefixCounts := range counts {
			prefixCounts[maskPrefix(dst, prefixLength)]++
		}
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

func parseTextTraceDstIP(line string) (uint32, error) {
	record, err := splitTextTraceLine(line)
	if err != nil {
		return 0, err
	}

	var dstIPStr string
	switch len(record) {
	case 8:
		dstIPStr = record[3]
	case 7:
		dstIPStr = record[3]
	default:
		return 0, fmt.Errorf("expected 7 or 8 text trace fields, got %d", len(record))
	}

	ip := net.ParseIP(dstIPStr).To4()
	if ip == nil {
		return 0, fmt.Errorf("invalid IPv4 destination %q", dstIPStr)
	}
	return binary.BigEndian.Uint32(ip), nil
}

func splitTextTraceLine(line string) ([]string, error) {
	if strings.Contains(line, ",") {
		reader := csv.NewReader(strings.NewReader(line))
		reader.FieldsPerRecord = -1
		return reader.Read()
	}
	return strings.Fields(line), nil
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

func maskPrefix(ip uint32, prefixLength int) uint32 {
	if prefixLength == 0 {
		return 0
	}
	return ip & (uint32(0xffffffff) << uint(32-prefixLength))
}

func buildRows(prefixLength int, counts map[uint32]uint64, totalIPv4 uint64) []prefixRow {
	rows := make([]prefixRow, 0, len(counts))
	for prefix, count := range counts {
		ratio := 0.0
		if totalIPv4 > 0 {
			ratio = float64(count) / float64(totalIPv4)
		}
		rows = append(rows, prefixRow{
			PrefixLength: prefixLength,
			Prefix:       prefix,
			Count:        count,
			Ratio:        ratio,
		})
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Count != rows[j].Count {
			return rows[i].Count > rows[j].Count
		}
		return rows[i].Prefix < rows[j].Prefix
	})
	return rows
}

func writePrefixCSV(path string, rows []prefixRow) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	if err := writer.Write([]string{"rank", "prefix_length", "prefix", "count", "ratio"}); err != nil {
		return err
	}
	for index, row := range rows {
		if err := writer.Write([]string{
			strconv.Itoa(index + 1),
			strconv.Itoa(row.PrefixLength),
			formatCIDR(row.Prefix, row.PrefixLength),
			strconv.FormatUint(row.Count, 10),
			formatRatio(row.Ratio),
		}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeSummaryCSV(path string, sum summary, prefixLengths []int) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	records := [][]string{
		{"metric", "value"},
		{"trace", sum.Trace},
		{"format", sum.Format},
		{"link_type", sum.LinkType},
		{"snaplen", sum.SnapLen},
		{"total_packets", strconv.FormatUint(sum.TotalPackets, 10)},
		{"ipv4_packets", strconv.FormatUint(sum.IPv4Packets, 10)},
		{"non_ipv4_packets", strconv.FormatUint(sum.NonIPv4Packets, 10)},
		{"parse_error_packets", strconv.FormatUint(sum.ParseErrorPackets, 10)},
		{"read_error_packets", strconv.FormatUint(sum.ReadErrorPackets, 10)},
		{"prefix_lengths", joinInts(prefixLengths)},
		{"started_at", sum.StartedAt.Format(time.RFC3339)},
		{"finished_at", sum.FinishedAt.Format(time.RFC3339)},
		{"duration_seconds", fmt.Sprintf("%.3f", sum.FinishedAt.Sub(sum.StartedAt).Seconds())},
	}
	for _, record := range records {
		if err := writer.Write(record); err != nil {
			return err
		}
	}
	return writer.Error()
}

func buildConcentration(prefixLength int, rows []prefixRow, totalIPv4 uint64) concentrationRow {
	cutoffs := []int{1, 5, 10, 50, 100}
	result := concentrationRow{
		PrefixLength:   prefixLength,
		UniquePrefixes: len(rows),
		TopCounts:      make(map[int]uint64, len(cutoffs)),
		TopRatios:      make(map[int]float64, len(cutoffs)),
	}
	for _, cutoff := range cutoffs {
		var count uint64
		limit := cutoff
		if len(rows) < limit {
			limit = len(rows)
		}
		for i := 0; i < limit; i++ {
			count += rows[i].Count
		}
		result.TopCounts[cutoff] = count
		if totalIPv4 > 0 {
			result.TopRatios[cutoff] = float64(count) / float64(totalIPv4)
		}
	}
	return result
}

func writeConcentrationCSV(path string, rows []concentrationRow) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"prefix_length",
		"unique_prefixes",
		"top1_count",
		"top1_ratio",
		"top5_count",
		"top5_ratio",
		"top10_count",
		"top10_ratio",
		"top50_count",
		"top50_ratio",
		"top100_count",
		"top100_ratio",
	}
	if err := writer.Write(header); err != nil {
		return err
	}
	for _, row := range rows {
		record := []string{
			strconv.Itoa(row.PrefixLength),
			strconv.Itoa(row.UniquePrefixes),
			strconv.FormatUint(row.TopCounts[1], 10),
			formatRatio(row.TopRatios[1]),
			strconv.FormatUint(row.TopCounts[5], 10),
			formatRatio(row.TopRatios[5]),
			strconv.FormatUint(row.TopCounts[10], 10),
			formatRatio(row.TopRatios[10]),
			strconv.FormatUint(row.TopCounts[50], 10),
			formatRatio(row.TopRatios[50]),
			strconv.FormatUint(row.TopCounts[100], 10),
			formatRatio(row.TopRatios[100]),
		}
		if err := writer.Write(record); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeSummaryMarkdown(path string, sum summary, opts options, concentrations []concentrationRow) error {
	var builder strings.Builder
	traceBase := filepath.Base(sum.Trace)

	fmt.Fprintf(&builder, "# Destination prefix distribution: %s\n\n", traceBase)
	fmt.Fprintf(&builder, "Generated at `%s`.\n\n", sum.FinishedAt.Format(time.RFC3339))

	builder.WriteString("## Input\n\n")
	fmt.Fprintf(&builder, "- trace: `%s`\n", sum.Trace)
	fmt.Fprintf(&builder, "- format: `%s`\n", sum.Format)
	fmt.Fprintf(&builder, "- link type: `%s`\n", sum.LinkType)
	fmt.Fprintf(&builder, "- snaplen: `%s`\n", sum.SnapLen)
	fmt.Fprintf(&builder, "- prefix lengths: `%s`\n", joinInts(opts.prefixLengths))
	fmt.Fprintf(&builder, "- duration seconds: `%.3f`\n\n", sum.FinishedAt.Sub(sum.StartedAt).Seconds())

	builder.WriteString("## Packet summary\n\n")
	builder.WriteString("| metric | value |\n")
	builder.WriteString("| --- | ---: |\n")
	fmt.Fprintf(&builder, "| total packets | %d |\n", sum.TotalPackets)
	fmt.Fprintf(&builder, "| IPv4 packets | %d |\n", sum.IPv4Packets)
	fmt.Fprintf(&builder, "| non-IPv4 packets | %d |\n", sum.NonIPv4Packets)
	fmt.Fprintf(&builder, "| parse error packets | %d |\n", sum.ParseErrorPackets)
	fmt.Fprintf(&builder, "| pcap read errors | %d |\n\n", sum.ReadErrorPackets)

	builder.WriteString("## Concentration\n\n")
	builder.WriteString("| prefix length | unique prefixes | top1 | top5 | top10 | top50 | top100 |\n")
	builder.WriteString("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
	for _, row := range concentrations {
		fmt.Fprintf(
			&builder,
			"| /%d | %d | %.4f | %.4f | %.4f | %.4f | %.4f |\n",
			row.PrefixLength,
			row.UniquePrefixes,
			row.TopRatios[1],
			row.TopRatios[5],
			row.TopRatios[10],
			row.TopRatios[50],
			row.TopRatios[100],
		)
	}
	builder.WriteString("\n")

	builder.WriteString("## Files\n\n")
	builder.WriteString("- `summary.csv`: packet counters and run metadata.\n")
	builder.WriteString("- `concentration.csv`: unique-prefix counts and top-N concentration ratios.\n")
	for _, prefixLength := range opts.prefixLengths {
		fmt.Fprintf(&builder, "- `prefix_%d.csv`: full /%d distribution sorted by `count desc, prefix asc`.\n", prefixLength, prefixLength)
		fmt.Fprintf(&builder, "- `prefix_%d_top%d.svg`: top-%d /%d distribution plot.\n", prefixLength, opts.topN, opts.topN, prefixLength)
	}
	builder.WriteString("\n")

	builder.WriteString("## Rerun\n\n")
	builder.WriteString("```bash\n")
	fmt.Fprintf(&builder, "sudo ./scripts/analyze_dst_prefix_distribution \\\n")
	fmt.Fprintf(&builder, "  --trace %s \\\n", shellQuote(sum.Trace))
	fmt.Fprintf(&builder, "  --prefix-lengths %s \\\n", shellQuote(joinInts(opts.prefixLengths)))
	fmt.Fprintf(&builder, "  --top-n %d \\\n", opts.topN)
	fmt.Fprintf(&builder, "  --output-dir %s\n", shellQuote(opts.outputDir))
	builder.WriteString("```\n")

	return os.WriteFile(path, []byte(builder.String()), 0o644)
}

func writeTopSVG(path string, rows []prefixRow, topN int, trace string, prefixLength int) error {
	limit := topN
	if len(rows) < limit {
		limit = len(rows)
	}
	const (
		width       = 1120
		leftMargin  = 175
		rightMargin = 230
		topMargin   = 52
		rowHeight   = 23
		barHeight   = 15
		bottomPad   = 28
	)
	height := topMargin + limit*rowHeight + bottomPad
	plotWidth := width - leftMargin - rightMargin

	var maxCount uint64
	if limit > 0 {
		maxCount = rows[0].Count
	}

	var builder strings.Builder
	fmt.Fprintf(&builder, `<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">`+"\n", width, height, width, height)
	builder.WriteString(`<rect width="100%" height="100%" fill="#ffffff"/>` + "\n")
	fmt.Fprintf(&builder, `<text x="18" y="27" font-family="sans-serif" font-size="18" font-weight="700" fill="#1f2933">Top %d destination /%d prefixes</text>`+"\n", limit, prefixLength)
	fmt.Fprintf(&builder, `<text x="18" y="45" font-family="sans-serif" font-size="12" fill="#52606d">%s</text>`+"\n", html.EscapeString(trace))

	for i := 0; i < limit; i++ {
		row := rows[i]
		y := topMargin + i*rowHeight
		barWidth := 0
		if maxCount > 0 {
			barWidth = int(float64(row.Count) / float64(maxCount) * float64(plotWidth))
		}
		if barWidth < 1 && row.Count > 0 {
			barWidth = 1
		}

		fmt.Fprintf(&builder, `<text x="%d" y="%d" text-anchor="end" font-family="monospace" font-size="12" fill="#1f2933">%s</text>`+"\n", leftMargin-12, y+12, html.EscapeString(formatCIDR(row.Prefix, row.PrefixLength)))
		fmt.Fprintf(&builder, `<rect x="%d" y="%d" width="%d" height="%d" fill="#2f6f73"/>`+"\n", leftMargin, y, barWidth, barHeight)
		fmt.Fprintf(&builder, `<text x="%d" y="%d" font-family="sans-serif" font-size="12" fill="#1f2933">%d (%.4f)</text>`+"\n", leftMargin+barWidth+8, y+12, row.Count, row.Ratio)
	}

	builder.WriteString("</svg>\n")
	return os.WriteFile(path, []byte(builder.String()), 0o644)
}

func joinInts(values []int) string {
	parts := make([]string, 0, len(values))
	for _, value := range values {
		parts = append(parts, strconv.Itoa(value))
	}
	return strings.Join(parts, ",")
}

func formatCIDR(prefix uint32, prefixLength int) string {
	return fmt.Sprintf("%d.%d.%d.%d/%d", byte(prefix>>24), byte(prefix>>16), byte(prefix>>8), byte(prefix), prefixLength)
}

func formatRatio(ratio float64) string {
	return strconv.FormatFloat(ratio, 'f', 12, 64)
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
