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

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcapgo"

	"test-module/cache"
	"test-module/ipaddress"
	"test-module/routingtable"
	"test-module/simulator"
)

const defaultTagLengthWay8 = "9-24,9-24,9-24,9-24,9-24,9-24,9-24,9-24"
const (
	windowModeWarm = "warm"
	windowModeCold = "cold"
)

type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}

type options struct {
	ruleFile        string
	trace           string
	outputDir       string
	outputCSV       string
	windows         []uint64
	maxPackets      uint64
	progressEvery   uint64
	way             int
	mpCapacities    []int
	mpRefbits       []int
	psCapacity      int
	psIndexTypes    []int
	cacheTagLength  [][2]int
	insertionPolicy string
	windowMode      string
}

type configSpec struct {
	id              string
	label           string
	family          string
	capacityConfig  string
	totalCapacity   int
	refbitsConfig   string
	way             int
	cacheIndexType  string
	cacheTagLength  string
	insertionPolicy string
	definition      simulator.SimulatorDefinition
}

type runState struct {
	config            configSpec
	sim               *simulator.SimpleCacheSimulator
	cumulativePackets uint64
	cumulativeHits    uint64
	windowCounters    []windowCounter
}

type windowCounter struct {
	size        uint64
	index       uint64
	startPacket uint64
	packets     uint64
	hits        uint64
}

type coldRunState struct {
	config            configSpec
	sim               *simulator.SimpleCacheSimulator
	counter           windowCounter
	cumulativePackets uint64
	cumulativeHits    uint64
}

type processStats struct {
	totalPackets      uint64
	validPackets      uint64
	nonIPv4Packets    uint64
	nonTCPUDPPackets  uint64
	parseErrorPackets uint64
	readErrorPackets  uint64
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}

	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		fatalf("create output dir: %v", err)
	}
	if opts.outputCSV == "" {
		opts.outputCSV = defaultOutputCSV(opts)
	}

	routingTable, err := loadRoutingTable(opts.ruleFile)
	if err != nil {
		fatalf("load routing table: %v", err)
	}

	configs, err := buildConfigSpecs(opts)
	if err != nil {
		fatalf("build config specs: %v", err)
	}

	outputFile, err := os.Create(opts.outputCSV)
	if err != nil {
		fatalf("create csv: %v", err)
	}
	defer outputFile.Close()

	writer := csv.NewWriter(outputFile)
	if err := writer.Write(csvHeader()); err != nil {
		fatalf("write csv header: %v", err)
	}

	startedAt := time.Now()
	var stats processStats
	if opts.windowMode == windowModeCold {
		coldRuns, err := buildColdRuns(configs, opts, routingTable)
		if err != nil {
			fatalf("build cold runs: %v", err)
		}
		stats, err = processTrace(opts, routingTable, func(packet *cache.MinPacket) error {
			return processMinPacketCold(writer, opts, startedAt, routingTable, coldRuns, packet)
		})
		if err != nil {
			fatalf("process trace: %v", err)
		}
		for i := range coldRuns {
			if err := flushPartialColdWindow(writer, opts, startedAt, &coldRuns[i]); err != nil {
				fatalf("flush partial cold windows: %v", err)
			}
		}
	} else {
		runs, err := buildWarmRuns(configs, opts, routingTable)
		if err != nil {
			fatalf("build warm runs: %v", err)
		}
		stats, err = processTrace(opts, routingTable, func(packet *cache.MinPacket) error {
			return processMinPacket(writer, opts, startedAt, runs, packet)
		})
		if err != nil {
			fatalf("process trace: %v", err)
		}
		for i := range runs {
			if err := flushPartialWindows(writer, opts, startedAt, &runs[i]); err != nil {
				fatalf("flush partial windows: %v", err)
			}
		}
	}
	writer.Flush()
	if err := writer.Error(); err != nil {
		fatalf("flush csv: %v", err)
	}
	if err := outputFile.Close(); err != nil {
		fatalf("close csv: %v", err)
	}

	if err := chownOutputTreeIfSudo(opts.outputDir); err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not restore output ownership after sudo: %v\n", err)
	}

	fmt.Printf("wrote CSV: %s\n", opts.outputCSV)
	fmt.Printf("window mode: %s\n", opts.windowMode)
	fmt.Printf("trace packets read: %d\n", stats.totalPackets)
	fmt.Printf("valid simulator packets: %d\n", stats.validPackets)
	fmt.Printf("non-IPv4 packets: %d\n", stats.nonIPv4Packets)
	fmt.Printf("non-TCP/UDP packets: %d\n", stats.nonTCPUDPPackets)
	fmt.Printf("parse errors: %d\n", stats.parseErrorPackets)
}

func parseOptions() (options, error) {
	opts := options{
		outputDir:       "scripts/reports/windowed_hitrate_wide_nonanon",
		maxPackets:      10_000_000,
		progressEvery:   1_000_000,
		way:             8,
		psCapacity:      8192,
		insertionPolicy: cache.UnifiedCacheInsertionPolicyExclusive,
		windowMode:      windowModeWarm,
	}
	var rawWindows string
	var rawMPCapacities string
	var rawMPRefbits string
	var rawPSIndexTypes string
	var rawCacheTagLength string

	flag.StringVar(&opts.ruleFile, "rulefile", "", "routing rule file")
	flag.StringVar(&opts.trace, "trace", "", "pcap or text trace file")
	flag.StringVar(&opts.outputDir, "output-dir", opts.outputDir, "output directory")
	flag.StringVar(&opts.outputCSV, "output-csv", "", "output CSV path; default is timestamped under output-dir")
	flag.StringVar(&rawWindows, "windows", "10000,100000,1000000", "comma-separated packet window sizes")
	flag.Uint64Var(&opts.maxPackets, "max", opts.maxPackets, "maximum valid simulator packets to process; 0 means unlimited")
	flag.Uint64Var(&opts.progressEvery, "progress-interval", opts.progressEvery, "stderr progress interval in valid packets; 0 disables progress")
	flag.IntVar(&opts.way, "way", opts.way, "way for MP and PS caches")
	flag.StringVar(&rawMPCapacities, "mp-capacities", "2048,2048", "comma-separated MP layer capacities")
	flag.StringVar(&rawMPRefbits, "mp-refbits", "24,18", "comma-separated MP layer refbits")
	flag.IntVar(&opts.psCapacity, "ps-capacity", opts.psCapacity, "Prefix-Shared cache capacity")
	flag.StringVar(&rawPSIndexTypes, "ps-index-types", "21,2", "comma-separated Prefix-Shared cache index types; 2 is ideal")
	flag.StringVar(&rawCacheTagLength, "cache-tag-length", defaultTagLengthWay8, "UnifiedCache tag length spec")
	flag.StringVar(&opts.insertionPolicy, "cache-insertion-policy", opts.insertionPolicy, "UnifiedCache insertion policy")
	flag.StringVar(&opts.windowMode, "window-mode", opts.windowMode, "window mode: warm or cold")
	flag.Parse()

	if opts.ruleFile == "" {
		return opts, errors.New("-rulefile is required")
	}
	if opts.trace == "" {
		return opts, errors.New("-trace is required")
	}
	if opts.way <= 0 {
		return opts, errors.New("-way must be positive")
	}
	if opts.psCapacity <= 0 {
		return opts, errors.New("-ps-capacity must be positive")
	}

	var err error
	opts.windows, err = parseUintList(rawWindows)
	if err != nil {
		return opts, fmt.Errorf("invalid -windows: %w", err)
	}
	opts.mpCapacities, err = parseIntList(rawMPCapacities)
	if err != nil {
		return opts, fmt.Errorf("invalid -mp-capacities: %w", err)
	}
	opts.mpRefbits, err = parseIntList(rawMPRefbits)
	if err != nil {
		return opts, fmt.Errorf("invalid -mp-refbits: %w", err)
	}
	if len(opts.mpCapacities) != len(opts.mpRefbits) {
		return opts, fmt.Errorf("-mp-capacities has %d items but -mp-refbits has %d", len(opts.mpCapacities), len(opts.mpRefbits))
	}
	if len(opts.mpCapacities) < 1 {
		return opts, errors.New("-mp-capacities must include at least one layer")
	}
	opts.psIndexTypes, err = parseNonNegativeIntList(rawPSIndexTypes)
	if err != nil {
		return opts, fmt.Errorf("invalid -ps-index-types: %w", err)
	}
	for _, indexType := range opts.psIndexTypes {
		if indexType < 0 || indexType > 24 {
			return opts, fmt.Errorf("PS cache index type must be 0..24: %d", indexType)
		}
	}
	opts.cacheTagLength, err = parseCacheTagLength(rawCacheTagLength)
	if err != nil {
		return opts, fmt.Errorf("invalid -cache-tag-length: %w", err)
	}
	if len(opts.cacheTagLength) != opts.way {
		return opts, fmt.Errorf("-cache-tag-length has %d ranges but -way is %d", len(opts.cacheTagLength), opts.way)
	}
	if _, err := cache.NormalizeUnifiedCacheInsertionPolicy(opts.insertionPolicy); err != nil {
		return opts, err
	}
	switch opts.windowMode {
	case windowModeWarm, windowModeCold:
	default:
		return opts, fmt.Errorf("-window-mode must be %q or %q: %s", windowModeWarm, windowModeCold, opts.windowMode)
	}
	return opts, nil
}

func parseUintList(raw string) ([]uint64, error) {
	parts := splitCSVish(raw)
	values := make([]uint64, 0, len(parts))
	seen := map[uint64]bool{}
	for _, part := range parts {
		value, err := strconv.ParseUint(part, 10, 64)
		if err != nil {
			return nil, err
		}
		if value == 0 {
			return nil, errors.New("values must be positive")
		}
		if !seen[value] {
			values = append(values, value)
			seen[value] = true
		}
	}
	if len(values) == 0 {
		return nil, errors.New("empty list")
	}
	sort.Slice(values, func(i, j int) bool { return values[i] < values[j] })
	return values, nil
}

func parseIntList(raw string) ([]int, error) {
	parts := splitCSVish(raw)
	values := make([]int, 0, len(parts))
	for _, part := range parts {
		value, err := strconv.Atoi(part)
		if err != nil {
			return nil, err
		}
		if value <= 0 {
			return nil, errors.New("values must be positive")
		}
		values = append(values, value)
	}
	if len(values) == 0 {
		return nil, errors.New("empty list")
	}
	return values, nil
}

func parseNonNegativeIntList(raw string) ([]int, error) {
	parts := splitCSVish(raw)
	values := make([]int, 0, len(parts))
	for _, part := range parts {
		value, err := strconv.Atoi(part)
		if err != nil {
			return nil, err
		}
		if value < 0 {
			return nil, errors.New("values must be non-negative")
		}
		values = append(values, value)
	}
	if len(values) == 0 {
		return nil, errors.New("empty list")
	}
	return values, nil
}

func splitCSVish(raw string) []string {
	parts := strings.Split(raw, ",")
	values := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			values = append(values, part)
		}
	}
	return values
}

func parseCacheTagLength(raw string) ([][2]int, error) {
	parts := splitCSVish(raw)
	result := make([][2]int, 0, len(parts))
	for _, part := range parts {
		bounds := strings.Split(part, "-")
		if len(bounds) != 2 {
			return nil, fmt.Errorf("expected min-max range: %q", part)
		}
		minValue, err := strconv.Atoi(strings.TrimSpace(bounds[0]))
		if err != nil {
			return nil, err
		}
		maxValue, err := strconv.Atoi(strings.TrimSpace(bounds[1]))
		if err != nil {
			return nil, err
		}
		if minValue < 0 || maxValue > 32 || minValue > maxValue {
			return nil, fmt.Errorf("invalid range %q", part)
		}
		result = append(result, [2]int{minValue, maxValue})
	}
	if len(result) == 0 {
		return nil, errors.New("empty tag length")
	}
	return result, nil
}

func buildConfigSpecs(opts options) ([]configSpec, error) {
	configs := make([]configSpec, 0, 1+len(opts.psIndexTypes))

	mpLayers := make([]simulator.Cache, len(opts.mpCapacities))
	mpPolicies := make([]string, max(0, len(opts.mpCapacities)-1))
	totalMPCapacity := 0
	for i := range opts.mpCapacities {
		mpLayers[i] = simulator.Cache{
			Type:    "NbitNWaySetAssociativeDstipLRUCache",
			Size:    opts.mpCapacities[i],
			Way:     opts.way,
			Refbits: opts.mpRefbits[i],
		}
		totalMPCapacity += opts.mpCapacities[i]
	}
	for i := range mpPolicies {
		mpPolicies[i] = "WriteThrough"
	}
	configs = append(configs, configSpec{
		id:             "mp-" + joinIntsDash(opts.mpRefbits) + "-" + joinIntsDash(opts.mpCapacities),
		label:          "MP /" + joinIntsPlusSlash(opts.mpRefbits) + " " + joinIntsPlus(opts.mpCapacities),
		family:         "Multi-Prefix-Cache",
		capacityConfig: joinIntsPipe(opts.mpCapacities),
		totalCapacity:  totalMPCapacity,
		refbitsConfig:  joinIntsPipe(opts.mpRefbits),
		way:            opts.way,
		definition: simulator.SimulatorDefinition{
			Type: "SimpleCacheSimulator",
			Cache: simulator.Cache{
				Type:          "MultiLayerCacheExclusive",
				CacheLayers:   mpLayers,
				CachePolicies: mpPolicies,
			},
			DebugMode: false,
		},
	})

	for _, indexType := range opts.psIndexTypes {
		indexName := fmt.Sprintf("index%d", indexType)
		if indexType == cache.CACHE_INDEX_TYPE_IDEAL {
			indexName = "ideal"
		}
		configs = append(configs, configSpec{
			id:              fmt.Sprintf("ps-%s-cap%d", indexName, opts.psCapacity),
			label:           fmt.Sprintf("PS %s %d", indexName, opts.psCapacity),
			family:          "Prefix-Shared-Cache",
			capacityConfig:  strconv.Itoa(opts.psCapacity),
			totalCapacity:   opts.psCapacity,
			way:             opts.way,
			cacheIndexType:  strconv.Itoa(indexType),
			cacheTagLength:  formatCacheTagLength(opts.cacheTagLength),
			insertionPolicy: opts.insertionPolicy,
			definition: simulator.SimulatorDefinition{
				Type: "SimpleCacheSimulator",
				Cache: simulator.Cache{
					Type:            "UnifiedCache",
					Size:            opts.psCapacity,
					Way:             opts.way,
					CacheIndexType:  indexType,
					CacheTagLength:  opts.cacheTagLength,
					InsertionPolicy: opts.insertionPolicy,
				},
				DebugMode: false,
			},
		})
	}
	return configs, nil
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

func newWindowCounters(windows []uint64) []windowCounter {
	counters := make([]windowCounter, len(windows))
	for i, window := range windows {
		counters[i] = windowCounter{size: window}
	}
	return counters
}

func buildWarmRuns(configs []configSpec, opts options, routingTable *routingtable.RoutingTablePatriciaTrie) ([]runState, error) {
	runs := make([]runState, 0, len(configs))
	for _, config := range configs {
		sim, err := simulator.BuildSimpleCacheSimulator(config.definition, opts.ruleFile, routingTable)
		if err != nil {
			return nil, fmt.Errorf("build simulator %s: %w", config.id, err)
		}
		runs = append(runs, runState{
			config:         config,
			sim:            sim,
			windowCounters: newWindowCounters(opts.windows),
		})
	}
	return runs, nil
}

func buildColdRuns(configs []configSpec, opts options, routingTable *routingtable.RoutingTablePatriciaTrie) ([]coldRunState, error) {
	runs := make([]coldRunState, 0, len(configs)*len(opts.windows))
	for _, config := range configs {
		for _, window := range opts.windows {
			sim, err := simulator.BuildSimpleCacheSimulator(config.definition, opts.ruleFile, routingTable)
			if err != nil {
				return nil, fmt.Errorf("build simulator %s window %d: %w", config.id, window, err)
			}
			runs = append(runs, coldRunState{
				config:  config,
				sim:     sim,
				counter: windowCounter{size: window},
			})
		}
	}
	return runs, nil
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

func processMinPacket(writer *csv.Writer, opts options, startedAt time.Time, runs []runState, packet *cache.MinPacket) error {
	for i := range runs {
		run := &runs[i]
		hit := run.sim.Process(packet, false)
		run.cumulativePackets++
		if hit {
			run.cumulativeHits++
		}
		for windowIndex := range run.windowCounters {
			counter := &run.windowCounters[windowIndex]
			if counter.packets == 0 {
				counter.startPacket = counter.index * counter.size
			}
			counter.packets++
			if hit {
				counter.hits++
			}
			if counter.packets == counter.size {
				if err := writeWindowRow(writer, opts, startedAt, run, counter, false); err != nil {
					return err
				}
				counter.index++
				counter.startPacket = counter.index * counter.size
				counter.packets = 0
				counter.hits = 0
			}
		}
	}
	return nil
}

func processMinPacketCold(
	writer *csv.Writer,
	opts options,
	startedAt time.Time,
	routingTable *routingtable.RoutingTablePatriciaTrie,
	runs []coldRunState,
	packet *cache.MinPacket,
) error {
	for i := range runs {
		run := &runs[i]
		counter := &run.counter
		if counter.packets == 0 {
			counter.startPacket = counter.index * counter.size
		}

		hit := run.sim.Process(packet, false)
		counter.packets++
		run.cumulativePackets++
		if hit {
			counter.hits++
			run.cumulativeHits++
		}

		if counter.packets == counter.size {
			if err := writeColdWindowRow(writer, opts, startedAt, run, false); err != nil {
				return err
			}
			counter.index++
			counter.startPacket = counter.index * counter.size
			counter.packets = 0
			counter.hits = 0

			sim, err := simulator.BuildSimpleCacheSimulator(run.config.definition, opts.ruleFile, routingTable)
			if err != nil {
				return fmt.Errorf("reset cold simulator %s window %d: %w", run.config.id, counter.size, err)
			}
			run.sim = sim
		}
	}
	return nil
}

func flushPartialWindows(writer *csv.Writer, opts options, startedAt time.Time, run *runState) error {
	for i := range run.windowCounters {
		counter := &run.windowCounters[i]
		if counter.packets == 0 {
			continue
		}
		if err := writeWindowRow(writer, opts, startedAt, run, counter, true); err != nil {
			return err
		}
	}
	return nil
}

func flushPartialColdWindow(writer *csv.Writer, opts options, startedAt time.Time, run *coldRunState) error {
	if run.counter.packets == 0 {
		return nil
	}
	return writeColdWindowRow(writer, opts, startedAt, run, true)
}

func csvHeader() []string {
	return []string{
		"generated_at",
		"trace_file_name",
		"trace_path",
		"rule_file_name",
		"rule_path",
		"config_id",
		"config_label",
		"family",
		"capacity_config",
		"total_capacity_entries",
		"refbits_config",
		"way",
		"cache_index_type",
		"cache_tag_length",
		"insertion_policy",
		"window_mode",
		"window_size",
		"window_index",
		"start_packet",
		"end_packet",
		"packets",
		"hits",
		"misses",
		"hit_rate",
		"hit_rate_pct",
		"cumulative_packets",
		"cumulative_hits",
		"cumulative_hit_rate",
		"cumulative_hit_rate_pct",
		"partial_window",
	}
}

func writeWindowRow(writer *csv.Writer, opts options, startedAt time.Time, run *runState, counter *windowCounter, partial bool) error {
	misses := counter.packets - counter.hits
	hitRate := ratio(counter.hits, counter.packets)
	cumulativeHitRate := ratio(run.cumulativeHits, run.cumulativePackets)
	row := []string{
		startedAt.Format(time.RFC3339),
		filepath.Base(opts.trace),
		opts.trace,
		filepath.Base(opts.ruleFile),
		opts.ruleFile,
		run.config.id,
		run.config.label,
		run.config.family,
		run.config.capacityConfig,
		strconv.Itoa(run.config.totalCapacity),
		run.config.refbitsConfig,
		strconv.Itoa(run.config.way),
		run.config.cacheIndexType,
		run.config.cacheTagLength,
		run.config.insertionPolicy,
		opts.windowMode,
		strconv.FormatUint(counter.size, 10),
		strconv.FormatUint(counter.index, 10),
		strconv.FormatUint(counter.startPacket, 10),
		strconv.FormatUint(counter.startPacket+counter.packets, 10),
		strconv.FormatUint(counter.packets, 10),
		strconv.FormatUint(counter.hits, 10),
		strconv.FormatUint(misses, 10),
		fmt.Sprintf("%.12f", hitRate),
		fmt.Sprintf("%.8f", hitRate*100.0),
		strconv.FormatUint(run.cumulativePackets, 10),
		strconv.FormatUint(run.cumulativeHits, 10),
		fmt.Sprintf("%.12f", cumulativeHitRate),
		fmt.Sprintf("%.8f", cumulativeHitRate*100.0),
		strconv.FormatBool(partial),
	}
	return writer.Write(row)
}

func writeColdWindowRow(writer *csv.Writer, opts options, startedAt time.Time, run *coldRunState, partial bool) error {
	counter := &run.counter
	misses := counter.packets - counter.hits
	hitRate := ratio(counter.hits, counter.packets)
	cumulativeHitRate := ratio(run.cumulativeHits, run.cumulativePackets)
	row := []string{
		startedAt.Format(time.RFC3339),
		filepath.Base(opts.trace),
		opts.trace,
		filepath.Base(opts.ruleFile),
		opts.ruleFile,
		run.config.id,
		run.config.label,
		run.config.family,
		run.config.capacityConfig,
		strconv.Itoa(run.config.totalCapacity),
		run.config.refbitsConfig,
		strconv.Itoa(run.config.way),
		run.config.cacheIndexType,
		run.config.cacheTagLength,
		run.config.insertionPolicy,
		opts.windowMode,
		strconv.FormatUint(counter.size, 10),
		strconv.FormatUint(counter.index, 10),
		strconv.FormatUint(counter.startPacket, 10),
		strconv.FormatUint(counter.startPacket+counter.packets, 10),
		strconv.FormatUint(counter.packets, 10),
		strconv.FormatUint(counter.hits, 10),
		strconv.FormatUint(misses, 10),
		fmt.Sprintf("%.12f", hitRate),
		fmt.Sprintf("%.8f", hitRate*100.0),
		strconv.FormatUint(run.cumulativePackets, 10),
		strconv.FormatUint(run.cumulativeHits, 10),
		fmt.Sprintf("%.12f", cumulativeHitRate),
		fmt.Sprintf("%.8f", cumulativeHitRate*100.0),
		strconv.FormatBool(partial),
	}
	return writer.Write(row)
}

func ratio(numerator uint64, denominator uint64) float64 {
	if denominator == 0 {
		return 0
	}
	return float64(numerator) / float64(denominator)
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

func defaultOutputCSV(opts options) string {
	traceBase := strings.TrimSuffix(filepath.Base(opts.trace), filepath.Ext(opts.trace))
	stamp := time.Now().Format("20060102T150405")
	return filepath.Join(opts.outputDir, fmt.Sprintf("windowed_hitrate_%s_%s_%s.csv", safeName(traceBase), opts.windowMode, stamp))
}

func safeName(value string) string {
	safe := strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '-' || r == '_' {
			return r
		}
		return '-'
	}, value)
	for strings.Contains(safe, "--") {
		safe = strings.ReplaceAll(safe, "--", "-")
	}
	safe = strings.Trim(safe, "-")
	if safe == "" {
		return "unknown"
	}
	return safe
}

func joinIntsDash(values []int) string {
	parts := make([]string, len(values))
	for i, value := range values {
		parts[i] = strconv.Itoa(value)
	}
	return strings.Join(parts, "-")
}

func joinIntsPipe(values []int) string {
	parts := make([]string, len(values))
	for i, value := range values {
		parts[i] = strconv.Itoa(value)
	}
	return strings.Join(parts, "|")
}

func joinIntsPlus(values []int) string {
	parts := make([]string, len(values))
	for i, value := range values {
		parts[i] = strconv.Itoa(value)
	}
	return strings.Join(parts, "+")
}

func joinIntsPlusSlash(values []int) string {
	parts := make([]string, len(values))
	for i, value := range values {
		parts[i] = strconv.Itoa(value)
	}
	return strings.Join(parts, "+/")
}

func formatCacheTagLength(values [][2]int) string {
	parts := make([]string, len(values))
	for i, value := range values {
		parts[i] = fmt.Sprintf("%d-%d", value[0], value[1])
	}
	return strings.Join(parts, ",")
}

func chownOutputTreeIfSudo(outputDir string) error {
	uidRaw := strings.TrimSpace(os.Getenv("SUDO_UID"))
	gidRaw := strings.TrimSpace(os.Getenv("SUDO_GID"))
	if uidRaw == "" || gidRaw == "" {
		return nil
	}
	uid, err := strconv.Atoi(uidRaw)
	if err != nil {
		return err
	}
	gid, err := strconv.Atoi(gidRaw)
	if err != nil {
		return err
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
