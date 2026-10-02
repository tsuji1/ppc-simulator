package main

import (
	"bufio"
	"compress/gzip"
	"container/heap"
	"encoding/binary"
	"encoding/csv"
	"encoding/gob"
	"errors"
	"flag"
	"fmt"
	"hash/crc32"
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

const (
	histogramBins    = 33
	defaultFitDepth  = 24
	defaultMax       = 10_000_000
	defaultSample    = 100_000
	defaultBeamWidth = 8
)

type options struct {
	ruleFile             string
	targetTrace          string
	targetDistribution   string
	initialMapping       string
	inputTrace           string
	outputDir            string
	outputTrace          string
	maxPackets           uint64
	fitDepth             int
	sampleSize           int
	beamWidth            int
	hillCandidates       int
	hillPasses           int
	candidateOrder       string
	allActiveCandidates  bool
	exactBlockCandidates int
	exactRounds          int
	selectedCandidates   int
	progressInterval     uint64
	fullTraceGreedy      bool
	subtreeHitFit        bool
	lpmEpsilon           float64
	setLoadWeight        float64
	setCount             int
	setWay               int
	setIndexDepth        int
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

type lpmMatcher struct {
	by24        []uint8
	deeperBy24  []byte
	longer      [histogramBins]map[uint32]struct{}
	longLengths []int
}

// lpmMatch identifies the routing-table entry selected by longest-prefix
// matching.  Keeping the network as well as the length lets analyses
// distinguish many prefixes at the same level from one hot prefix.
type lpmMatch struct {
	network uint32
	length  int
}

type transform interface {
	Apply(uint32) uint32
	FlipCount() int
	Description() string
	Mapping() savedMapping
}

type identityTransform struct{}

func (identityTransform) Apply(ip uint32) uint32 { return ip }
func (identityTransform) FlipCount() int         { return 0 }
func (identityTransform) Description() string    { return "no destination-tree rotation" }
func (identityTransform) Mapping() savedMapping  { return savedMapping{Method: "baseline-anonymized"} }

type globalXORTransform struct {
	depth int
	mask  uint32
}

func (t globalXORTransform) Apply(ip uint32) uint32 { return ip ^ t.mask }
func (t globalXORTransform) FlipCount() int         { return bits.OnesCount32(t.mask) }
func (t globalXORTransform) Description() string {
	return fmt.Sprintf("one shared XOR decision per depth, upper /%d", t.depth)
}
func (t globalXORTransform) Mapping() savedMapping {
	return savedMapping{Method: "global-lpm-xor", Depth: t.depth, Mask: t.mask}
}

type adaptiveTransform struct {
	method string
	depth  int
	flips  []byte
	detail string
}

func (t *adaptiveTransform) Apply(ip uint32) uint32 {
	result := ip
	node := uint32(1)
	for depth := 0; depth < t.depth; depth++ {
		inputBit := (ip >> (31 - depth)) & 1
		if int(node) < len(t.flips) && t.flips[node] != 0 {
			result ^= uint32(1) << (31 - depth)
		}
		node = node*2 + inputBit
	}
	return result
}
func (t *adaptiveTransform) FlipCount() int {
	count := 0
	for _, value := range t.flips {
		if value != 0 {
			count++
		}
	}
	return count
}
func (t *adaptiveTransform) Description() string { return t.detail }
func (t *adaptiveTransform) Mapping() savedMapping {
	return savedMapping{Method: t.method, Depth: t.depth, Flips: t.flips}
}

type methodResult struct {
	name      string
	transform transform
	hist      [histogramBins]uint64
	metrics   distributionMetrics
	sampleTV  float64
	best      bool
	exact     exactSearchStats
	subtree   *subtreeHitFitStats
}

type subtreeHitFitStats struct {
	beforeScore    float64
	afterScore     float64
	setLoadBefore  float64
	setLoadAfter   float64
	combinedBefore float64
	combinedAfter  float64
	seedTV         float64
	finalTV        float64
	tvLimit        float64
	upperAccepted  int
	lowerAccepted  int
}

type hitSignature [9]uint16

// setLoadSignature summarizes the cache pressure created by one traffic /16.
// The fields are: unique cache keys, active sets, maximum keys in one set,
// keys beyond associativity, overloaded sets, and non-cacheable destinations.
type setLoadSignature [6]uint32

type trafficGroup struct {
	start     int
	end       int
	packets   uint64
	decile    int
	signature hitSignature
	setLoad   setLoadSignature
}

type hitDistribution [10][9]map[int]uint64
type setLoadDistribution [10][6]map[int]uint64

type exactSearchStats struct {
	rounds                 int
	improvedRounds         int
	disjointRounds         int
	blockCandidates        int
	theoreticalAssignments uint64
	visitedLeaves          uint64
	prunedSubtrees         uint64
	prunedAssignments      uint64
	baseNumerator          uint64
	bestNumerator          uint64
	elapsed                time.Duration
}

type distributionMetrics struct {
	total              uint64
	totalVariation     float64
	jensenShannon      float64
	meanPrefixLength   float64
	targetMeanPrefix   float64
	meanPrefixDelta    float64
	maxBinAbsoluteDiff float64
}

type savedMapping struct {
	Method string
	Depth  int
	Mask   uint32
	Flips  []byte
}

type candidateNode struct {
	node  uint32
	depth int
	mass  uint32
}

type candidateRange struct {
	candidateNode
	start int
	end   int
}

type candidateMinHeap []candidateNode

func (h candidateMinHeap) Len() int { return len(h) }
func (h candidateMinHeap) Less(i, j int) bool {
	if h[i].mass != h[j].mass {
		return h[i].mass < h[j].mass
	}
	return h[i].node > h[j].node
}
func (h candidateMinHeap) Swap(i, j int)   { h[i], h[j] = h[j], h[i] }
func (h *candidateMinHeap) Push(value any) { *h = append(*h, value.(candidateNode)) }
func (h *candidateMinHeap) Pop() any {
	old := *h
	value := old[len(old)-1]
	*h = old[:len(old)-1]
	return value
}

type rankedExactCandidate struct {
	candidate      candidateRange
	trialNumerator uint64
	changedPackets int
}

type exactCandidateWorstHeap []rankedExactCandidate

func (h exactCandidateWorstHeap) Len() int { return len(h) }
func (h exactCandidateWorstHeap) Less(i, j int) bool {
	// container/heap keeps the element considered "smallest" at index zero.
	// Put the worst retained candidate there so a better candidate can replace it.
	return exactCandidateBetter(h[j], h[i])
}
func (h exactCandidateWorstHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *exactCandidateWorstHeap) Push(value any) {
	*h = append(*h, value.(rankedExactCandidate))
}
func (h *exactCandidateWorstHeap) Pop() any {
	old := *h
	value := old[len(old)-1]
	*h = old[:len(old)-1]
	return value
}

func main() {
	opts, err := parseOptions()
	if err != nil {
		fatalf("%v", err)
	}
	if err := os.MkdirAll(opts.outputDir, 0o755); err != nil {
		fatalf("create output directory: %v", err)
	}
	if opts.outputTrace == "" {
		opts.outputTrace = filepath.Join(opts.outputDir, "best_transformed_trace.txt")
	}
	if err := os.MkdirAll(filepath.Dir(opts.outputTrace), 0o755); err != nil {
		fatalf("create transformed trace directory: %v", err)
	}

	started := time.Now()
	fmt.Fprintf(os.Stderr, "loading rule table and /%d fitting tree\n", opts.fitDepth)
	matcher, ruleTree, ruleCount, err := loadRules(opts.ruleFile, opts.fitDepth)
	if err != nil {
		fatalf("load rules: %v", err)
	}
	fmt.Fprintf(os.Stderr, "loaded %d routing prefixes\n", ruleCount)

	var targetHist [histogramBins]uint64
	var targetStats scanStats
	var targetDestinationCounts map[uint32]uint64
	if opts.subtreeHitFit {
		targetDestinationCounts = make(map[uint32]uint64)
	}
	if opts.targetDistribution != "" {
		fmt.Fprintln(os.Stderr, "loading fixed target LPM distribution")
		targetHist, err = loadTargetHistogram(opts.targetDistribution)
		if err != nil {
			fatalf("load target distribution: %v", err)
		}
		targetStats.validPackets = histogramTotal(targetHist)
	} else {
		fmt.Fprintln(os.Stderr, "scanning non-anonymized target trace")
		targetStats, err = scanTrace(opts.targetTrace, opts.maxPackets, opts.progressInterval, func(packet tracePacket) error {
			targetHist[matcher.Match(packet.dst)]++
			if targetDestinationCounts != nil {
				targetDestinationCounts[packet.dst]++
			}
			return nil
		})
		if err != nil {
			fatalf("scan target trace: %v", err)
		}
	}

	treeSize := 1 << (opts.fitDepth + 1)
	leafBase := 1 << opts.fitDepth
	traceTree := make([]uint32, treeSize)
	reservoir := newReservoir(opts.sampleSize)
	var destinationCounts map[uint32]uint64
	if opts.fullTraceGreedy || opts.subtreeHitFit {
		destinationCounts = make(map[uint32]uint64)
	}
	var baselineHist [histogramBins]uint64
	fmt.Fprintln(os.Stderr, "scanning anonymized input trace for fitting")
	inputStats, err := scanTrace(opts.inputTrace, opts.maxPackets, opts.progressInterval, func(packet tracePacket) error {
		baselineHist[matcher.Match(packet.dst)]++
		leaf := leafBase + int(packet.dst>>(32-opts.fitDepth))
		traceTree[leaf]++
		reservoir.Add(packet.dst)
		if destinationCounts != nil {
			destinationCounts[packet.dst]++
		}
		return nil
	})
	if err != nil {
		fatalf("scan input trace: %v", err)
	}
	buildAggregateTree(traceTree, leafBase)
	sortedSample := append([]uint32(nil), reservoir.values...)
	sort.Slice(sortedSample, func(i, j int) bool { return sortedSample[i] < sortedSample[j] })

	var methods []methodResult
	if opts.fullTraceGreedy {
		fmt.Fprintf(os.Stderr, "fitting exact full-trace %s greedy rotations\n", opts.candidateOrder)
		uniqueDestinations, weights := sortedWeightedDestinations(destinationCounts)
		candidates := buildAllActiveCandidateRanges(uniqueDestinations, traceTree, opts.fitDepth)
		orderGreedyCandidateRanges(candidates, opts.candidateOrder)
		opts.selectedCandidates = len(candidates)
		greedy := &adaptiveTransform{
			method: "greedy-full-" + opts.candidateOrder,
			depth:  opts.fitDepth,
			flips:  make([]byte, 1<<opts.fitDepth),
			detail: fmt.Sprintf("identity initialization plus exact full-trace %s greedy prefix-local rotations", opts.candidateOrder),
		}
		greedyStarted := time.Now()
		refineAdaptiveLPMWeighted(greedy, candidates, uniqueDestinations, weights, targetHist, matcher, opts.hillPasses)
		fmt.Fprintf(os.Stderr, "exact full-trace greedy elapsed: %s; unique destinations: %d; candidates: %d\n",
			time.Since(greedyStarted).Round(time.Millisecond), len(uniqueDestinations), len(candidates))
		methods = []methodResult{
			{name: "baseline-anonymized", transform: identityTransform{}, hist: baselineHist},
			{name: greedy.method, transform: greedy},
		}
	} else {
		fmt.Fprintln(os.Stderr, "fitting global LPM-directed XOR")
		global := fitGlobalXOR(sortedSample, targetHist, matcher, opts.fitDepth, opts.beamWidth)

		fmt.Fprintln(os.Stderr, "fitting prefix-adaptive packet-density rotations")
		packetAdaptive := fitAdaptive("adaptive-packet", traceTree, ruleTree, opts.fitDepth,
			"prefix-local rotations aligning packet mass with routing-entry subtree mass")

		var candidates []candidateRange
		if opts.allActiveCandidates {
			candidates = buildAllActiveCandidateRanges(sortedSample, traceTree, opts.fitDepth)
		} else {
			selected := selectHillCandidates(traceTree, opts.fitDepth, opts.hillCandidates)
			candidates = buildCandidateRanges(sortedSample, selected)
		}
		orderCandidateRanges(candidates, opts.candidateOrder)
		opts.selectedCandidates = len(candidates)
		fmt.Fprintf(os.Stderr, "selected %d LPM candidates (budget %d, all-active %t, order %s)\n",
			len(candidates), opts.hillCandidates, opts.allActiveCandidates, opts.candidateOrder)
		fmt.Fprintln(os.Stderr, "fitting direct LPM rotations from the identity mapping")
		directStarted := time.Now()
		directLPM := &adaptiveTransform{
			method: "adaptive-lpm-direct",
			depth:  opts.fitDepth,
			flips:  make([]byte, 1<<opts.fitDepth),
			detail: "identity initialization plus prefix-local rotations selected only by target LPM error",
		}
		refineAdaptiveLPM(directLPM, candidates, sortedSample, targetHist, matcher, opts.hillPasses)
		fmt.Fprintf(os.Stderr, "direct LPM refinement elapsed: %s\n", time.Since(directStarted).Round(time.Millisecond))

		fmt.Fprintln(os.Stderr, "refining packet-density rotations against target LPM distribution")
		packetStarted := time.Now()
		packetSeedLPM := cloneAdaptive(packetAdaptive, "adaptive-lpm-packet-seed",
			"packet-density initialization plus prefix-local rotations selected by target LPM error")
		refineAdaptiveLPM(packetSeedLPM, candidates, sortedSample, targetHist, matcher, opts.hillPasses)
		fmt.Fprintf(os.Stderr, "packet-seed LPM refinement elapsed: %s\n", time.Since(packetStarted).Round(time.Millisecond))

		var subtreeHit *adaptiveTransform
		var subtreeStats subtreeHitFitStats
		if opts.subtreeHitFit {
			fmt.Fprintf(os.Stderr, "fitting traffic-decile /16 hit-node and set-load distributions (LPM epsilon %.6f, set-load weight %.3f)\n",
				opts.lpmEpsilon, opts.setLoadWeight)
			subtreeHit = cloneAdaptive(directLPM, "adaptive-lpm-subtree-hit",
				fmt.Sprintf("LPM seed plus upper-/16 then intra-/16 hit-node/set-load fitting with epsilon %.6f and set-load weight %.3f",
					opts.lpmEpsilon, opts.setLoadWeight))
			uniqueDestinations, weights := sortedWeightedDestinations(destinationCounts)
			subtreeCandidates := buildCandidateRanges(uniqueDestinations,
				selectHillCandidates(traceTree, opts.fitDepth, opts.hillCandidates))
			orderCandidateRanges(subtreeCandidates, opts.candidateOrder)
			targetDestinations, targetWeights := sortedWeightedDestinations(targetDestinationCounts)
			subtreeStats = refineSubtreeHitDistribution(subtreeHit, subtreeCandidates,
				uniqueDestinations, weights, targetDestinations, targetWeights, targetHist, matcher,
				ruleTree, opts.fitDepth, opts.setCount, opts.setWay, opts.setIndexDepth,
				opts.setLoadWeight, opts.lpmEpsilon, opts.hillPasses)
			fmt.Fprintf(os.Stderr, "subtree-hit score %.8f -> %.8f; set-load %.8f -> %.8f; combined %.8f -> %.8f; TV %.8f -> %.8f; accepted upper/lower %d/%d\n",
				subtreeStats.beforeScore, subtreeStats.afterScore,
				subtreeStats.setLoadBefore, subtreeStats.setLoadAfter,
				subtreeStats.combinedBefore, subtreeStats.combinedAfter,
				subtreeStats.seedTV, subtreeStats.finalTV,
				subtreeStats.upperAccepted, subtreeStats.lowerAccepted)
		}

		var suppliedSeed *adaptiveTransform
		if opts.initialMapping != "" {
			saved, readErr := readMapping(opts.initialMapping)
			if readErr != nil {
				fatalf("read initial mapping: %v", readErr)
			}
			if saved.Depth != opts.fitDepth || len(saved.Flips) != 1<<opts.fitDepth {
				fatalf("initial mapping must be an adaptive /%d mapping: depth=%d flips=%d", opts.fitDepth, saved.Depth, len(saved.Flips))
			}
			flips := append([]byte(nil), saved.Flips...)
			suppliedSeed = &adaptiveTransform{
				method: "adaptive-lpm-supplied-seed",
				depth:  saved.Depth,
				flips:  flips,
				detail: "saved adaptive mapping supplied as an additional exact-search seed",
			}
			fmt.Fprintf(os.Stderr, "loaded initial mapping: %s\n", opts.initialMapping)
		}

		var exactLPM *adaptiveTransform
		var exactStats exactSearchStats
		if opts.exactBlockCandidates > 0 && opts.exactRounds > 0 {
			exactSource := directLPM
			exactSourceName := "direct"
			if sampleTV(sortedSample, packetSeedLPM, matcher, targetHist) < sampleTV(sortedSample, directLPM, matcher, targetHist) {
				exactSource = packetSeedLPM
				exactSourceName = "packet-seed"
			}
			if suppliedSeed != nil && sampleTV(sortedSample, suppliedSeed, matcher, targetHist) < sampleTV(sortedSample, exactSource, matcher, targetHist) {
				exactSource = suppliedSeed
				exactSourceName = "supplied-seed"
			}
			exactLPM = cloneAdaptive(exactSource, "adaptive-lpm-exact-block-from-"+exactSourceName,
				fmt.Sprintf("%s greedy initialization plus exact branch-and-bound enumeration in blocks of %d variables", exactSourceName, opts.exactBlockCandidates))
			fmt.Fprintf(os.Stderr, "running exact block search from %s (%d variables, %d rounds)\n",
				exactSourceName, opts.exactBlockCandidates, opts.exactRounds)
			exactStats = refineAdaptiveLPMExactBlocks(exactLPM, candidates, sortedSample, targetHist, matcher,
				opts.exactBlockCandidates, opts.exactRounds)
			fmt.Fprintf(os.Stderr, "exact block search elapsed: %s, leaves %d, pruned assignments %d\n",
				exactStats.elapsed.Round(time.Millisecond), exactStats.visitedLeaves, exactStats.prunedAssignments)
		}

		fmt.Fprintln(os.Stderr, "fitting prefix-adaptive unique-/24 structure rotations")
		convertTreeToUnique(traceTree, leafBase)
		uniqueAdaptive := fitAdaptive("adaptive-unique", traceTree, ruleTree, opts.fitDepth,
			"prefix-local rotations aligning occupied /24 structure with routing-entry subtree mass")

		methods = []methodResult{
			{name: "baseline-anonymized", transform: identityTransform{}, hist: baselineHist},
			{name: "global-lpm-xor", transform: global},
			{name: "adaptive-packet", transform: packetAdaptive},
			{name: "adaptive-unique", transform: uniqueAdaptive},
			{name: "adaptive-lpm-direct", transform: directLPM},
			{name: "adaptive-lpm-packet-seed", transform: packetSeedLPM},
		}
		if suppliedSeed != nil {
			methods = append(methods, methodResult{name: suppliedSeed.method, transform: suppliedSeed})
		}
		if exactLPM != nil {
			methods = append(methods, methodResult{name: exactLPM.method, transform: exactLPM, exact: exactStats})
		}
		if subtreeHit != nil {
			stats := subtreeStats
			methods = append(methods, methodResult{name: subtreeHit.method, transform: subtreeHit, subtree: &stats})
		}
	}
	for index := range methods {
		methods[index].sampleTV = sampleTV(sortedSample, methods[index].transform, matcher, targetHist)
	}

	// Release the two dense fitting trees before the full comparison pass.
	traceTree = nil
	ruleTree = nil

	fmt.Fprintln(os.Stderr, "evaluating fitted rotations on the full anonymized sample")
	_, err = scanTrace(opts.inputTrace, opts.maxPackets, opts.progressInterval, func(packet tracePacket) error {
		for index := 1; index < len(methods); index++ {
			mapped := methods[index].transform.Apply(packet.dst)
			methods[index].hist[matcher.Match(mapped)]++
		}
		return nil
	})
	if err != nil {
		fatalf("evaluate transformed trace: %v", err)
	}

	bestIndex := 1
	for index := range methods {
		methods[index].metrics = compareDistribution(methods[index].hist, targetHist)
		if opts.subtreeHitFit && methods[index].subtree != nil {
			bestIndex = index
		} else if !opts.subtreeHitFit && index > 1 && methods[index].metrics.totalVariation < methods[bestIndex].metrics.totalVariation {
			bestIndex = index
		}
	}
	methods[bestIndex].best = true

	fmt.Fprintf(os.Stderr, "writing best transformed trace (%s)\n", methods[bestIndex].name)
	if err := writeTransformedTrace(opts, methods[bestIndex].transform); err != nil {
		fatalf("write transformed trace: %v", err)
	}
	if opts.subtreeHitFit {
		for _, method := range methods {
			if method.name != "adaptive-lpm-direct" {
				continue
			}
			seedOptions := opts
			seedOptions.outputTrace = filepath.Join(opts.outputDir, "lpm_seed_trace.txt")
			fmt.Fprintln(os.Stderr, "writing pre-subtree LPM seed trace")
			if err := writeTransformedTrace(seedOptions, method.transform); err != nil {
				fatalf("write LPM seed trace: %v", err)
			}
			break
		}
	}
	if err := writeMapping(filepath.Join(opts.outputDir, "best_mapping.gob.gz"), methods[bestIndex].transform.Mapping()); err != nil {
		fatalf("write mapping: %v", err)
	}
	if err := writeReports(opts, methods, targetHist, targetStats, inputStats, ruleCount, started, time.Now()); err != nil {
		fatalf("write reports: %v", err)
	}

	fmt.Printf("best method: %s\n", methods[bestIndex].name)
	fmt.Printf("target TV: %.8f (baseline %.8f)\n", methods[bestIndex].metrics.totalVariation, methods[0].metrics.totalVariation)
	fmt.Printf("wrote transformed trace: %s\n", opts.outputTrace)
	fmt.Printf("wrote report: %s\n", filepath.Join(opts.outputDir, "REPORT.md"))
}

func parseOptions() (options, error) {
	opts := options{
		maxPackets:       defaultMax,
		fitDepth:         defaultFitDepth,
		sampleSize:       defaultSample,
		beamWidth:        defaultBeamWidth,
		hillCandidates:   15_360,
		hillPasses:       2,
		candidateOrder:   "mass",
		progressInterval: 1_000_000,
		setCount:         1024,
		setWay:           8,
		setIndexDepth:    18,
	}
	flag.StringVar(&opts.ruleFile, "rulefile", "", "real routing rule file")
	flag.StringVar(&opts.targetTrace, "target-trace", "", "non-anonymized target trace")
	flag.StringVar(&opts.targetDistribution, "target-distribution", "", "CSV containing lpm_prefix_length and target_count (or count)")
	flag.StringVar(&opts.initialMapping, "initial-mapping", "", "optional saved adaptive mapping used as an additional exact-search seed")
	flag.StringVar(&opts.inputTrace, "input-trace", "", "anonymized trace to rotate")
	flag.StringVar(&opts.outputDir, "output-dir", "", "CSV/Markdown/mapping output directory")
	flag.StringVar(&opts.outputTrace, "output-trace", "", "best transformed simulator text trace")
	flag.Uint64Var(&opts.maxPackets, "max", opts.maxPackets, "maximum valid TCP/UDP IPv4 packets per trace; 0 reads all")
	flag.IntVar(&opts.fitDepth, "fit-depth", opts.fitDepth, "maximum rotated prefix depth")
	flag.IntVar(&opts.sampleSize, "sample-size", opts.sampleSize, "deterministic reservoir size for optimization")
	flag.IntVar(&opts.beamWidth, "beam-width", opts.beamWidth, "beam width for global XOR fitting")
	flag.IntVar(&opts.hillCandidates, "hill-candidates", opts.hillCandidates, "prefix nodes considered by direct LPM refinement")
	flag.IntVar(&opts.hillPasses, "hill-passes", opts.hillPasses, "direct LPM refinement passes")
	flag.StringVar(&opts.candidateOrder, "candidate-order", opts.candidateOrder, "candidate traversal order: mass, top-down, or bottom-up")
	flag.BoolVar(&opts.allActiveCandidates, "all-active-candidates", false, "consider every prefix node represented in the optimization sample")
	flag.IntVar(&opts.exactBlockCandidates, "exact-block-candidates", 0, "exactly enumerate assignments for this many selected rotation variables; 0 disables")
	flag.IntVar(&opts.exactRounds, "exact-rounds", 1, "number of exact block-coordinate rounds")
	flag.Uint64Var(&opts.progressInterval, "progress-interval", opts.progressInterval, "progress interval in valid packets; 0 disables")
	flag.BoolVar(&opts.fullTraceGreedy, "full-trace-greedy", false, "run only exact frequency-weighted greedy rotations over every active prefix node")
	flag.BoolVar(&opts.subtreeHitFit, "subtree-hit-fit", false, "fit traffic-decile /16 hit-prefix distributions after LPM fitting")
	flag.Float64Var(&opts.lpmEpsilon, "lpm-epsilon", 0, "maximum sample TV increase above the LPM seed during subtree-hit fitting")
	flag.Float64Var(&opts.setLoadWeight, "set-load-weight", 0, "weight of per-/16 cache set-load distance in subtree fitting; 0 disables")
	flag.IntVar(&opts.setCount, "set-count", opts.setCount, "cache set count used by set-load fitting")
	flag.IntVar(&opts.setWay, "set-way", opts.setWay, "cache associativity used to define overloaded sets")
	flag.IntVar(&opts.setIndexDepth, "set-index-depth", opts.setIndexDepth, "destination prefix length hashed to a cache set")
	flag.Parse()

	if opts.ruleFile == "" || opts.inputTrace == "" || opts.outputDir == "" {
		return opts, errors.New("--rulefile, --input-trace, and --output-dir are required")
	}
	if (opts.targetTrace == "") == (opts.targetDistribution == "") {
		return opts, errors.New("exactly one of --target-trace and --target-distribution is required")
	}
	if opts.fitDepth < 4 || opts.fitDepth > 24 {
		return opts, errors.New("--fit-depth must be in 4..24")
	}
	if opts.sampleSize <= 0 || opts.beamWidth <= 0 || opts.hillCandidates < 0 || opts.hillPasses < 0 {
		return opts, errors.New("sample size and beam width must be positive; hill settings must be non-negative")
	}
	if opts.exactBlockCandidates < 0 || opts.exactBlockCandidates > 30 || opts.exactRounds < 0 {
		return opts, errors.New("--exact-block-candidates must be 0..30 and --exact-rounds must be non-negative")
	}
	if opts.candidateOrder != "mass" && opts.candidateOrder != "top-down" && opts.candidateOrder != "bottom-up" {
		return opts, errors.New("--candidate-order must be mass, top-down, or bottom-up")
	}
	if opts.fullTraceGreedy && opts.candidateOrder == "mass" {
		return opts, errors.New("--full-trace-greedy requires --candidate-order top-down or bottom-up")
	}
	if opts.subtreeHitFit && opts.targetTrace == "" {
		return opts, errors.New("--subtree-hit-fit requires --target-trace so target /16 hit-node distributions can be measured")
	}
	if opts.lpmEpsilon < 0 || opts.lpmEpsilon > 1 {
		return opts, errors.New("--lpm-epsilon must be in 0..1")
	}
	if opts.setLoadWeight < 0 {
		return opts, errors.New("--set-load-weight must be non-negative")
	}
	if opts.setLoadWeight > 0 && !opts.subtreeHitFit {
		return opts, errors.New("--set-load-weight requires --subtree-hit-fit")
	}
	if opts.setLoadWeight > 0 && opts.fitDepth != 24 {
		return opts, errors.New("--set-load-weight currently requires --fit-depth 24")
	}
	if opts.setCount <= 0 || opts.setWay <= 0 || opts.setIndexDepth < 1 || opts.setIndexDepth > 24 {
		return opts, errors.New("set count/way must be positive and set index depth must be in 1..24")
	}
	return opts, nil
}

func loadTargetHistogram(path string) ([histogramBins]uint64, error) {
	var histogram [histogramBins]uint64
	file, err := os.Open(path)
	if err != nil {
		return histogram, err
	}
	defer file.Close()

	reader := csv.NewReader(file)
	header, err := reader.Read()
	if err != nil {
		return histogram, fmt.Errorf("read CSV header: %w", err)
	}
	column := func(name string) int {
		for index, value := range header {
			if strings.TrimSpace(value) == name {
				return index
			}
		}
		return -1
	}
	prefixColumn := column("lpm_prefix_length")
	countColumn := column("target_count")
	if countColumn < 0 {
		countColumn = column("count")
	}
	if prefixColumn < 0 || countColumn < 0 {
		return histogram, errors.New("CSV needs lpm_prefix_length and target_count (or count) columns")
	}

	seen := [histogramBins]bool{}
	for rowNumber := 2; ; rowNumber++ {
		row, readErr := reader.Read()
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return histogram, fmt.Errorf("read CSV row %d: %w", rowNumber, readErr)
		}
		if prefixColumn >= len(row) || countColumn >= len(row) {
			return histogram, fmt.Errorf("CSV row %d is missing required columns", rowNumber)
		}
		prefixLength, parseErr := strconv.Atoi(strings.TrimSpace(row[prefixColumn]))
		if parseErr != nil || prefixLength < 0 || prefixLength >= histogramBins {
			return histogram, fmt.Errorf("CSV row %d has invalid LPM prefix length %q", rowNumber, row[prefixColumn])
		}
		count, parseErr := strconv.ParseUint(strings.TrimSpace(row[countColumn]), 10, 64)
		if parseErr != nil {
			return histogram, fmt.Errorf("CSV row %d has invalid count %q: %w", rowNumber, row[countColumn], parseErr)
		}
		if seen[prefixLength] && histogram[prefixLength] != count {
			return histogram, fmt.Errorf("conflicting duplicate count for /%d: %d and %d", prefixLength, histogram[prefixLength], count)
		}
		histogram[prefixLength] = count
		seen[prefixLength] = true
	}
	for prefixLength, found := range seen {
		if !found {
			return histogram, fmt.Errorf("target distribution is missing /%d", prefixLength)
		}
	}
	if histogramTotal(histogram) == 0 {
		return histogram, errors.New("target distribution contains zero packets")
	}
	return histogram, nil
}

func loadRules(path string, fitDepth int) (*lpmMatcher, []uint32, int, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, 0, err
	}
	defer file.Close()

	matcher := &lpmMatcher{
		by24:       make([]uint8, 1<<24),
		deeperBy24: make([]byte, 1<<24),
	}
	var short [25][]uint32
	ruleTree := make([]uint32, 1<<(fitDepth+1))
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	count := 0
	for scanner.Scan() {
		line := strings.TrimSpace(strings.SplitN(scanner.Text(), "#", 2)[0])
		if line == "" {
			continue
		}
		fields := strings.Fields(line)
		network, prefixLength, err := parseRulePrefix(fields)
		if err != nil {
			return nil, nil, 0, fmt.Errorf("rule line %d: %w", count+1, err)
		}
		count++
		if prefixLength <= 24 {
			short[prefixLength] = append(short[prefixLength], network)
		} else {
			matcher.deeperBy24[network>>8] = 1
			if matcher.longer[prefixLength] == nil {
				matcher.longer[prefixLength] = make(map[uint32]struct{})
			}
			matcher.longer[prefixLength][network] = struct{}{}
		}

		effectiveDepth := prefixLength
		if effectiveDepth > fitDepth {
			effectiveDepth = fitDepth
		}
		prefix := uint32(0)
		if effectiveDepth > 0 {
			prefix = network >> (32 - effectiveDepth)
		}
		node := (1 << effectiveDepth) + int(prefix)
		ruleTree[node]++
	}
	if err := scanner.Err(); err != nil {
		return nil, nil, 0, err
	}

	for prefixLength := 0; prefixLength <= 24; prefixLength++ {
		span := 1 << (24 - prefixLength)
		for _, network := range short[prefixLength] {
			start := int(network >> 8)
			for offset := 0; offset < span; offset++ {
				matcher.by24[start+offset] = uint8(prefixLength)
			}
		}
	}
	for prefixLength := 32; prefixLength >= 25; prefixLength-- {
		if len(matcher.longer[prefixLength]) > 0 {
			matcher.longLengths = append(matcher.longLengths, prefixLength)
		}
	}
	buildAggregateTree(ruleTree, 1<<fitDepth)
	return matcher, ruleTree, count, nil
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

func (matcher *lpmMatcher) Match(ip uint32) int {
	return matcher.MatchPrefix(ip).length
}

func (matcher *lpmMatcher) MatchPrefix(ip uint32) lpmMatch {
	for _, prefixLength := range matcher.longLengths {
		if _, ok := matcher.longer[prefixLength][ip&prefixMask(prefixLength)]; ok {
			return lpmMatch{network: ip & prefixMask(prefixLength), length: prefixLength}
		}
	}
	prefixLength := int(matcher.by24[ip>>8])
	return lpmMatch{network: ip & prefixMask(prefixLength), length: prefixLength}
}

func buildAggregateTree(tree []uint32, leafBase int) {
	for node := leafBase - 1; node >= 1; node-- {
		tree[node] += tree[node*2] + tree[node*2+1]
	}
}

func convertTreeToUnique(tree []uint32, leafBase int) {
	for node := leafBase; node < leafBase*2; node++ {
		if tree[node] != 0 {
			tree[node] = 1
		}
	}
	for node := leafBase - 1; node >= 1; node-- {
		tree[node] = tree[node*2] + tree[node*2+1]
	}
}

func fitAdaptive(method string, traceTree, ruleTree []uint32, depth int, detail string) *adaptiveTransform {
	result := &adaptiveTransform{method: method, depth: depth, flips: make([]byte, 1<<depth), detail: detail}
	var walk func(traceNode, ruleNode uint32, currentDepth int)
	walk = func(traceNode, ruleNode uint32, currentDepth int) {
		if currentDepth >= depth || traceTree[traceNode] == 0 {
			return
		}
		traceLeft := traceTree[traceNode*2]
		traceRight := traceTree[traceNode*2+1]
		ruleLeft := ruleTree[ruleNode*2]
		ruleRight := ruleTree[ruleNode*2+1]
		flip := false
		if traceLeft+traceRight > 0 && ruleLeft+ruleRight > 0 {
			traceLeftRatio := float64(traceLeft) / float64(traceLeft+traceRight)
			ruleLeftRatio := float64(ruleLeft) / float64(ruleLeft+ruleRight)
			straight := math.Abs(traceLeftRatio - ruleLeftRatio)
			crossed := math.Abs((1.0 - traceLeftRatio) - ruleLeftRatio)
			flip = crossed+1e-15 < straight
		}
		if flip {
			result.flips[traceNode] = 1
			walk(traceNode*2, ruleNode*2+1, currentDepth+1)
			walk(traceNode*2+1, ruleNode*2, currentDepth+1)
		} else {
			walk(traceNode*2, ruleNode*2, currentDepth+1)
			walk(traceNode*2+1, ruleNode*2+1, currentDepth+1)
		}
	}
	walk(1, 1, 0)
	return result
}

func cloneAdaptive(source *adaptiveTransform, method, detail string) *adaptiveTransform {
	flips := make([]byte, len(source.flips))
	copy(flips, source.flips)
	return &adaptiveTransform{method: method, depth: source.depth, flips: flips, detail: detail}
}

func fitGlobalXOR(sample []uint32, target [histogramBins]uint64, matcher *lpmMatcher, depth, width int) globalXORTransform {
	type beamItem struct {
		mask  uint32
		score float64
	}
	beam := []beamItem{{mask: 0, score: histogramTV(histogramForSample(sample, identityTransform{}, matcher), target)}}
	for bitDepth := 0; bitDepth < depth; bitDepth++ {
		bitMask := uint32(1) << (31 - bitDepth)
		candidates := make([]beamItem, 0, len(beam)*2)
		seen := make(map[uint32]bool, len(beam)*2)
		for _, item := range beam {
			for _, mask := range []uint32{item.mask, item.mask ^ bitMask} {
				if seen[mask] {
					continue
				}
				seen[mask] = true
				candidate := globalXORTransform{depth: depth, mask: mask}
				score := histogramTV(histogramForSample(sample, candidate, matcher), target)
				candidates = append(candidates, beamItem{mask: mask, score: score})
			}
		}
		sort.Slice(candidates, func(i, j int) bool {
			if candidates[i].score != candidates[j].score {
				return candidates[i].score < candidates[j].score
			}
			return candidates[i].mask < candidates[j].mask
		})
		if len(candidates) > width {
			candidates = candidates[:width]
		}
		beam = candidates
	}
	return globalXORTransform{depth: depth, mask: beam[0].mask}
}

func selectHillCandidates(tree []uint32, depth, budget int) []candidateNode {
	if budget <= 0 {
		return nil
	}
	result := make([]candidateNode, 0, budget)
	baseQuota := budget / depth
	remainder := budget % depth
	for currentDepth := 0; currentDepth < depth; currentDepth++ {
		quota := baseQuota
		if currentDepth < remainder {
			quota++
		}
		if quota == 0 {
			continue
		}
		h := &candidateMinHeap{}
		heap.Init(h)
		start := 1 << currentDepth
		end := 1 << (currentDepth + 1)
		for rawNode := start; rawNode < end; rawNode++ {
			node := uint32(rawNode)
			mass := tree[node]
			if mass == 0 {
				continue
			}
			value := candidateNode{node: node, depth: currentDepth, mass: mass}
			if h.Len() < quota {
				heap.Push(h, value)
			} else if mass > (*h)[0].mass || (mass == (*h)[0].mass && node < (*h)[0].node) {
				heap.Pop(h)
				heap.Push(h, value)
			}
		}
		for h.Len() > 0 {
			result = append(result, heap.Pop(h).(candidateNode))
		}
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].mass != result[j].mass {
			return result[i].mass > result[j].mass
		}
		if result[i].depth != result[j].depth {
			return result[i].depth < result[j].depth
		}
		return result[i].node < result[j].node
	})
	return result
}

func buildCandidateRanges(sample []uint32, candidates []candidateNode) []candidateRange {
	result := make([]candidateRange, 0, len(candidates))
	for _, candidate := range candidates {
		start, end := samplePrefixRange(sample, candidate.node, candidate.depth)
		if start == end {
			continue
		}
		result = append(result, candidateRange{candidateNode: candidate, start: start, end: end})
	}
	return result
}

func buildAllActiveCandidateRanges(sample []uint32, tree []uint32, depth int) []candidateRange {
	if len(sample) == 0 {
		return nil
	}
	result := make([]candidateRange, 0, len(sample)*2)
	for currentDepth := 0; currentDepth < depth; currentDepth++ {
		start := 0
		for start < len(sample) {
			prefix := samplePrefix(sample[start], currentDepth)
			end := start + 1
			for end < len(sample) && samplePrefix(sample[end], currentDepth) == prefix {
				end++
			}
			node := uint32(1<<currentDepth) + prefix
			result = append(result, candidateRange{
				candidateNode: candidateNode{node: node, depth: currentDepth, mass: tree[node]},
				start:         start,
				end:           end,
			})
			start = end
		}
	}
	return result
}

func samplePrefix(ip uint32, depth int) uint32 {
	if depth == 0 {
		return 0
	}
	return ip >> (32 - depth)
}

func samplePrefixRange(sample []uint32, node uint32, depth int) (int, int) {
	if depth == 0 {
		return 0, len(sample)
	}
	prefix := node - uint32(1<<depth)
	start := sort.Search(len(sample), func(index int) bool {
		return samplePrefix(sample[index], depth) >= prefix
	})
	end := sort.Search(len(sample), func(index int) bool {
		return samplePrefix(sample[index], depth) > prefix
	})
	return start, end
}

func orderCandidateNodes(candidates []candidateNode, order string) {
	sort.Slice(candidates, func(i, j int) bool {
		left, right := candidates[i], candidates[j]
		switch order {
		case "top-down":
			if left.depth != right.depth {
				return left.depth < right.depth
			}
		case "bottom-up":
			if left.depth != right.depth {
				return left.depth > right.depth
			}
		default:
			if left.mass != right.mass {
				return left.mass > right.mass
			}
		}
		if left.mass != right.mass {
			return left.mass > right.mass
		}
		if left.depth != right.depth {
			return left.depth < right.depth
		}
		return left.node < right.node
	})
}

func orderCandidateRanges(candidates []candidateRange, order string) {
	sort.Slice(candidates, func(i, j int) bool {
		left, right := candidates[i].candidateNode, candidates[j].candidateNode
		switch order {
		case "top-down":
			if left.depth != right.depth {
				return left.depth < right.depth
			}
		case "bottom-up":
			if left.depth != right.depth {
				return left.depth > right.depth
			}
		default:
			if left.mass != right.mass {
				return left.mass > right.mass
			}
		}
		if left.mass != right.mass {
			return left.mass > right.mass
		}
		if left.depth != right.depth {
			return left.depth < right.depth
		}
		return left.node < right.node
	})
}

func orderGreedyCandidateRanges(candidates []candidateRange, order string) {
	sort.Slice(candidates, func(i, j int) bool {
		left, right := candidates[i].candidateNode, candidates[j].candidateNode
		if left.depth != right.depth {
			if order == "bottom-up" {
				return left.depth > right.depth
			}
			return left.depth < right.depth
		}
		return left.node < right.node
	})
}

func sortedWeightedDestinations(counts map[uint32]uint64) ([]uint32, []uint64) {
	destinations := make([]uint32, 0, len(counts))
	for destination := range counts {
		destinations = append(destinations, destination)
	}
	sort.Slice(destinations, func(i, j int) bool { return destinations[i] < destinations[j] })
	weights := make([]uint64, len(destinations))
	for index, destination := range destinations {
		weights[index] = counts[destination]
	}
	return destinations, weights
}

// refineAdaptiveLPMWeighted evaluates every packet represented by weights.
// A rotation is committed only when the exact scaled L1 numerator decreases,
// so full-trace TV is monotonically non-increasing after every decision.
func refineAdaptiveLPMWeighted(t *adaptiveTransform, candidates []candidateRange, destinations []uint32,
	weights []uint64, target [histogramBins]uint64, matcher *lpmMatcher, passes int) {
	if len(destinations) == 0 || len(candidates) == 0 || passes == 0 {
		return
	}
	if len(destinations) != len(weights) {
		panic("destination and weight lengths differ")
	}
	mapped := make([]uint32, len(destinations))
	lengths := make([]uint8, len(destinations))
	var current [histogramBins]uint64
	for index, ip := range destinations {
		mapped[index] = t.Apply(ip)
		lengths[index] = uint8(matcher.Match(mapped[index]))
		current[lengths[index]] += weights[index]
	}
	currentNumerator := scaledL1Numerator(current, target)
	for pass := 0; pass < passes; pass++ {
		improved := false
		for _, candidate := range candidates {
			trial := current
			bitMask := uint32(1) << (31 - candidate.depth)
			for index := candidate.start; index < candidate.end; index++ {
				oldLength := lengths[index]
				newLength := uint8(matcher.Match(mapped[index] ^ bitMask))
				if oldLength == newLength {
					continue
				}
				trial[oldLength] -= weights[index]
				trial[newLength] += weights[index]
			}
			trialNumerator := scaledL1Numerator(trial, target)
			if trialNumerator >= currentNumerator {
				continue
			}
			t.flips[candidate.node] ^= 1
			current = trial
			currentNumerator = trialNumerator
			for index := candidate.start; index < candidate.end; index++ {
				mapped[index] ^= bitMask
				lengths[index] = uint8(matcher.Match(mapped[index]))
			}
			improved = true
		}
		if !improved {
			break
		}
	}
}

func refineAdaptiveLPM(t *adaptiveTransform, candidates []candidateRange, sample []uint32, target [histogramBins]uint64, matcher *lpmMatcher, passes int) {
	if len(sample) == 0 || len(candidates) == 0 || passes == 0 {
		return
	}
	mapped := make([]uint32, len(sample))
	lengths := make([]uint8, len(sample))
	var current [histogramBins]uint64
	for index, ip := range sample {
		mapped[index] = t.Apply(ip)
		lengths[index] = uint8(matcher.Match(mapped[index]))
		current[lengths[index]]++
	}
	currentScore := histogramTV(current, target)
	for pass := 0; pass < passes; pass++ {
		improved := false
		for _, candidate := range candidates {
			trial := current
			bitMask := uint32(1) << (31 - candidate.depth)
			for index := candidate.start; index < candidate.end; index++ {
				oldLength := lengths[index]
				newLength := uint8(matcher.Match(mapped[index] ^ bitMask))
				trial[oldLength]--
				trial[newLength]++
			}
			trialScore := histogramTV(trial, target)
			if trialScore+1e-12 >= currentScore {
				continue
			}
			t.flips[candidate.node] ^= 1
			for index := candidate.start; index < candidate.end; index++ {
				mapped[index] ^= bitMask
				lengths[index] = uint8(matcher.Match(mapped[index]))
			}
			current = trial
			currentScore = trialScore
			improved = true
		}
		if !improved {
			break
		}
	}
}

// refineSubtreeHitDistribution performs the proposed two-stage optimization.
// Traffic /16s keep their decile (ranked by packet mass), while rotations
// change which routing subtree they encounter. The objective is the mean TV
// distance of the nine h16..h24 distributions across ten traffic deciles.
// LPM TV is a hard constraint relative to the supplied LPM-optimized seed.
func refineSubtreeHitDistribution(t *adaptiveTransform, candidates []candidateRange,
	destinations []uint32, weights []uint64, targetDestinations []uint32, targetWeights []uint64,
	targetLPM [histogramBins]uint64, matcher *lpmMatcher, ruleTree []uint32, fitDepth, setCount, setWay,
	setIndexDepth int, setLoadWeight, epsilon float64, passes int) subtreeHitFitStats {
	if len(destinations) == 0 || len(destinations) != len(weights) || len(targetDestinations) == 0 || len(targetDestinations) != len(targetWeights) {
		panic("subtree-hit fitting requires non-empty aligned destination/weight vectors")
	}

	mapped := make([]uint32, len(destinations))
	lengths := make([]uint8, len(destinations))
	var lpmHistogram [histogramBins]uint64
	for index, destination := range destinations {
		mapped[index] = t.Apply(destination)
		lengths[index] = uint8(matcher.Match(mapped[index]))
		lpmHistogram[lengths[index]] += weights[index]
	}
	groups, destinationGroup := buildTrafficGroups(destinations, weights, mapped, matcher,
		ruleTree, fitDepth, setCount, setWay, setIndexDepth, setLoadWeight > 0)
	currentDistribution := distributionForGroups(groups)
	currentSetLoad := setLoadDistributionForGroups(groups)
	targetMapped := append([]uint32(nil), targetDestinations...)
	targetGroups, _ := buildTrafficGroups(targetDestinations, targetWeights, targetMapped, matcher,
		ruleTree, fitDepth, setCount, setWay, setIndexDepth, setLoadWeight > 0)
	targetDistribution := distributionForGroups(targetGroups)
	targetSetLoad := setLoadDistributionForGroups(targetGroups)
	currentHitScore := hitDistributionTV(currentDistribution, targetDistribution, groups, targetGroups)
	currentSetLoadScore := setLoadDistributionTV(currentSetLoad, targetSetLoad, groups, targetGroups)
	currentScore := currentHitScore + setLoadWeight*currentSetLoadScore
	seedTV := histogramTV(lpmHistogram, targetLPM)
	tvLimit := seedTV + epsilon
	result := subtreeHitFitStats{
		beforeScore: currentHitScore, setLoadBefore: currentSetLoadScore,
		combinedBefore: currentScore, seedTV: seedTV, tvLimit: tvLimit,
	}

	stages := [][2]int{{0, 15}, {16, 23}}
	for stageIndex, bounds := range stages {
		for pass := 0; pass < passes; pass++ {
			improved := false
			for _, candidate := range candidates {
				if candidate.depth < bounds[0] || candidate.depth > bounds[1] || candidate.start == candidate.end {
					continue
				}
				bitMask := uint32(1) << (31 - candidate.depth)
				trialLPM := lpmHistogram
				for index := candidate.start; index < candidate.end; index++ {
					mapped[index] ^= bitMask
					newLength := uint8(matcher.Match(mapped[index]))
					trialLPM[lengths[index]] -= weights[index]
					trialLPM[newLength] += weights[index]
				}
				trialTV := histogramTV(trialLPM, targetLPM)
				if trialTV > tvLimit+1e-12 {
					for index := candidate.start; index < candidate.end; index++ {
						mapped[index] ^= bitMask
					}
					continue
				}

				firstGroup := destinationGroup[candidate.start]
				lastGroup := destinationGroup[candidate.end-1]
				trialDistribution := cloneHitDistribution(currentDistribution)
				trialSetLoad := cloneSetLoadDistribution(currentSetLoad)
				trialSignatures := make([]hitSignature, lastGroup-firstGroup+1)
				trialSetLoads := make([]setLoadSignature, lastGroup-firstGroup+1)
				for groupIndex := firstGroup; groupIndex <= lastGroup; groupIndex++ {
					group := &groups[groupIndex]
					newSignature := hitSignatureForRange(mapped, group.start, group.end, matcher)
					newSetLoad := group.setLoad
					if setLoadWeight > 0 {
						newSetLoad = setLoadSignatureForRange(mapped, group.start, group.end, matcher,
							ruleTree, fitDepth, setCount, setWay, setIndexDepth)
					}
					trialSignatures[groupIndex-firstGroup] = newSignature
					trialSetLoads[groupIndex-firstGroup] = newSetLoad
					updateHitDistribution(&trialDistribution, group.decile, group.signature, group.packets, false)
					updateHitDistribution(&trialDistribution, group.decile, newSignature, group.packets, true)
					updateSetLoadDistribution(&trialSetLoad, group.decile, group.setLoad, group.packets, false)
					updateSetLoadDistribution(&trialSetLoad, group.decile, newSetLoad, group.packets, true)
				}
				trialHitScore := hitDistributionTV(trialDistribution, targetDistribution, groups, targetGroups)
				trialSetLoadScore := setLoadDistributionTV(trialSetLoad, targetSetLoad, groups, targetGroups)
				trialScore := trialHitScore + setLoadWeight*trialSetLoadScore
				if trialScore+1e-12 >= currentScore {
					for index := candidate.start; index < candidate.end; index++ {
						mapped[index] ^= bitMask
					}
					continue
				}

				t.flips[candidate.node] ^= 1
				for index := candidate.start; index < candidate.end; index++ {
					lengths[index] = uint8(matcher.Match(mapped[index]))
				}
				for groupIndex := firstGroup; groupIndex <= lastGroup; groupIndex++ {
					groups[groupIndex].signature = trialSignatures[groupIndex-firstGroup]
					groups[groupIndex].setLoad = trialSetLoads[groupIndex-firstGroup]
				}
				lpmHistogram = trialLPM
				currentDistribution = trialDistribution
				currentSetLoad = trialSetLoad
				currentHitScore = trialHitScore
				currentSetLoadScore = trialSetLoadScore
				currentScore = trialScore
				improved = true
				if stageIndex == 0 {
					result.upperAccepted++
				} else {
					result.lowerAccepted++
				}
			}
			if !improved {
				break
			}
		}
	}
	result.afterScore = currentHitScore
	result.setLoadAfter = currentSetLoadScore
	result.combinedAfter = currentScore
	result.finalTV = histogramTV(lpmHistogram, targetLPM)
	return result
}

func buildTrafficGroups(destinations []uint32, weights []uint64, mapped []uint32, matcher *lpmMatcher,
	ruleTree []uint32, fitDepth, setCount, setWay, setIndexDepth int, includeSetLoad bool) ([]trafficGroup, []int) {
	groups := make([]trafficGroup, 0)
	destinationGroup := make([]int, len(destinations))
	for start := 0; start < len(destinations); {
		prefix16 := destinations[start] >> 16
		end := start + 1
		packets := weights[start]
		for end < len(destinations) && destinations[end]>>16 == prefix16 {
			packets += weights[end]
			end++
		}
		groupIndex := len(groups)
		for index := start; index < end; index++ {
			destinationGroup[index] = groupIndex
		}
		group := trafficGroup{start: start, end: end, packets: packets,
			signature: hitSignatureForRange(mapped, start, end, matcher)}
		if includeSetLoad {
			group.setLoad = setLoadSignatureForRange(mapped, start, end, matcher,
				ruleTree, fitDepth, setCount, setWay, setIndexDepth)
		}
		groups = append(groups, group)
		start = end
	}
	ranked := make([]int, len(groups))
	for index := range ranked {
		ranked[index] = index
	}
	sort.Slice(ranked, func(i, j int) bool {
		left, right := groups[ranked[i]], groups[ranked[j]]
		if left.packets != right.packets {
			return left.packets > right.packets
		}
		return destinations[left.start] < destinations[right.start]
	})
	for rank, groupIndex := range ranked {
		groups[groupIndex].decile = rank * 10 / len(groups)
		if groups[groupIndex].decile > 9 {
			groups[groupIndex].decile = 9
		}
	}
	return groups, destinationGroup
}

func hitSignatureForRange(mapped []uint32, start, end int, matcher *lpmMatcher) hitSignature {
	seen := make(map[uint64]struct{}, end-start)
	var signature hitSignature
	for index := start; index < end; index++ {
		match := matcher.MatchPrefix(mapped[index])
		if match.length < 16 || match.length > 24 {
			continue
		}
		key := uint64(match.length)<<32 | uint64(match.network)
		if _, exists := seen[key]; exists {
			continue
		}
		seen[key] = struct{}{}
		signature[match.length-16]++
	}
	return signature
}

func setLoadSignatureForRange(mapped []uint32, start, end int, matcher *lpmMatcher,
	ruleTree []uint32, fitDepth, setCount, setWay, setIndexDepth int) setLoadSignature {
	keysBySet := make(map[int]map[uint64]struct{})
	var signature setLoadSignature
	for index := start; index < end; index++ {
		ip := mapped[index]
		leafLength := fittedLeafLength(ip, matcher, ruleTree, fitDepth)
		if leafLength > 24 {
			signature[5]++
			continue
		}
		cacheLength := leafLength
		if cacheLength < 9 {
			cacheLength = 9
		}
		set := crcPrefixSet(ip, setIndexDepth, setCount)
		if keysBySet[set] == nil {
			keysBySet[set] = make(map[uint64]struct{})
		}
		key := uint64(cacheLength)<<32 | uint64(ip>>(32-cacheLength))
		keysBySet[set][key] = struct{}{}
	}

	signature[1] = uint32(len(keysBySet))
	for _, keys := range keysBySet {
		count := len(keys)
		signature[0] += uint32(count)
		if uint32(count) > signature[2] {
			signature[2] = uint32(count)
		}
		if count > setWay {
			signature[3] += uint32(count - setWay)
			signature[4]++
		}
	}
	return signature
}

func fittedLeafLength(ip uint32, matcher *lpmMatcher, ruleTree []uint32, fitDepth int) int {
	node := 1
	for depth := 0; depth < fitDepth; depth++ {
		if ruleTree[node*2]+ruleTree[node*2+1] == 0 {
			return depth
		}
		bit := int((ip >> (31 - depth)) & 1)
		node = node*2 + bit
	}
	if fitDepth == 24 && matcher.deeperBy24[ip>>8] != 0 {
		return 25
	}
	return fitDepth
}

func crcPrefixSet(ip uint32, prefixLength, setCount int) int {
	value := ip >> (32 - prefixLength)
	bytes := []byte{byte(value >> 24), byte(value >> 16), byte(value >> 8), byte(value)}
	return int(crc32.ChecksumIEEE(bytes) % uint32(setCount))
}

func distributionForGroups(groups []trafficGroup) hitDistribution {
	var distribution hitDistribution
	for decile := range distribution {
		for length := range distribution[decile] {
			distribution[decile][length] = make(map[int]uint64)
		}
	}
	for _, group := range groups {
		updateHitDistribution(&distribution, group.decile, group.signature, group.packets, true)
	}
	return distribution
}

func setLoadDistributionForGroups(groups []trafficGroup) setLoadDistribution {
	var distribution setLoadDistribution
	for decile := range distribution {
		for metric := range distribution[decile] {
			distribution[decile][metric] = make(map[int]uint64)
		}
	}
	for _, group := range groups {
		updateSetLoadDistribution(&distribution, group.decile, group.setLoad, group.packets, true)
	}
	return distribution
}

func updateHitDistribution(distribution *hitDistribution, decile int, signature hitSignature, weight uint64, add bool) {
	for offset, count := range signature {
		key := int(count)
		current := (*distribution)[decile][offset][key]
		if !add {
			if current <= weight {
				delete((*distribution)[decile][offset], key)
			} else {
				(*distribution)[decile][offset][key] = current - weight
			}
		} else {
			(*distribution)[decile][offset][key] = current + weight
		}
	}
}

func updateSetLoadDistribution(distribution *setLoadDistribution, decile int, signature setLoadSignature, weight uint64, add bool) {
	for metric, count := range signature {
		key := int(count)
		current := (*distribution)[decile][metric][key]
		if !add {
			if current <= weight {
				delete((*distribution)[decile][metric], key)
			} else {
				(*distribution)[decile][metric][key] = current - weight
			}
		} else {
			(*distribution)[decile][metric][key] = current + weight
		}
	}
}

func cloneHitDistribution(source hitDistribution) hitDistribution {
	var result hitDistribution
	for decile := range source {
		for length := range source[decile] {
			result[decile][length] = make(map[int]uint64, len(source[decile][length]))
			for value, count := range source[decile][length] {
				result[decile][length][value] = count
			}
		}
	}
	return result
}

func cloneSetLoadDistribution(source setLoadDistribution) setLoadDistribution {
	var result setLoadDistribution
	for decile := range source {
		for metric := range source[decile] {
			result[decile][metric] = make(map[int]uint64, len(source[decile][metric]))
			for value, count := range source[decile][metric] {
				result[decile][metric][value] = count
			}
		}
	}
	return result
}

func hitDistributionTV(actual, target hitDistribution, actualGroups, targetGroups []trafficGroup) float64 {
	var actualCounts, targetCounts [10]uint64
	for _, group := range actualGroups {
		actualCounts[group.decile] += group.packets
	}
	for _, group := range targetGroups {
		targetCounts[group.decile] += group.packets
	}
	var score float64
	comparisons := 0
	for decile := 0; decile < 10; decile++ {
		if actualCounts[decile] == 0 || targetCounts[decile] == 0 {
			continue
		}
		for offset := 0; offset < 9; offset++ {
			keys := make(map[int]struct{}, len(actual[decile][offset])+len(target[decile][offset]))
			for key := range actual[decile][offset] {
				keys[key] = struct{}{}
			}
			for key := range target[decile][offset] {
				keys[key] = struct{}{}
			}
			var distance float64
			for key := range keys {
				left := float64(actual[decile][offset][key]) / float64(actualCounts[decile])
				right := float64(target[decile][offset][key]) / float64(targetCounts[decile])
				distance += math.Abs(left - right)
			}
			score += distance * 0.5
			comparisons++
		}
	}
	if comparisons == 0 {
		return 0
	}
	return score / float64(comparisons)
}

func setLoadDistributionTV(actual, target setLoadDistribution, actualGroups, targetGroups []trafficGroup) float64 {
	var actualCounts, targetCounts [10]uint64
	for _, group := range actualGroups {
		actualCounts[group.decile] += group.packets
	}
	for _, group := range targetGroups {
		targetCounts[group.decile] += group.packets
	}
	var score float64
	comparisons := 0
	for decile := 0; decile < 10; decile++ {
		if actualCounts[decile] == 0 || targetCounts[decile] == 0 {
			continue
		}
		for metric := 0; metric < len(actual[decile]); metric++ {
			keys := make(map[int]struct{}, len(actual[decile][metric])+len(target[decile][metric]))
			for key := range actual[decile][metric] {
				keys[key] = struct{}{}
			}
			for key := range target[decile][metric] {
				keys[key] = struct{}{}
			}
			var distance float64
			for key := range keys {
				left := float64(actual[decile][metric][key]) / float64(actualCounts[decile])
				right := float64(target[decile][metric][key]) / float64(targetCounts[decile])
				distance += math.Abs(left - right)
			}
			score += distance * 0.5
			comparisons++
		}
	}
	if comparisons == 0 {
		return 0
	}
	return score / float64(comparisons)
}

func refineAdaptiveLPMExactBlocks(t *adaptiveTransform, candidates []candidateRange, sample []uint32,
	target [histogramBins]uint64, matcher *lpmMatcher, blockSize, rounds int) exactSearchStats {
	started := time.Now()
	var result exactSearchStats
	if blockSize <= 0 || rounds <= 0 || len(candidates) == 0 || len(sample) == 0 {
		return result
	}
	for round := 0; round < rounds; round++ {
		roundStarted := time.Now()
		fmt.Fprintf(os.Stderr, "exact round %d/%d: ranking candidate block\n", round+1, rounds)
		block := selectExactCandidateBlock(t, candidates, sample, target, matcher, blockSize)
		if len(block) == 0 {
			break
		}
		var bestMask uint64
		var roundStats exactSearchStats
		if candidateRangesDisjoint(block) {
			fmt.Fprintf(os.Stderr, "exact round %d/%d: enumerating %d disjoint variables\n", round+1, rounds, len(block))
			bestMask, roundStats = enumerateExactDisjointCandidateBlock(t, block, sample, target, matcher)
			roundStats.disjointRounds = 1
		} else {
			fmt.Fprintf(os.Stderr, "exact round %d/%d: enumerating %d overlapping variables\n", round+1, rounds, len(block))
			bestMask, roundStats = enumerateExactCandidateBlock(t, block, sample, target, matcher)
		}
		fmt.Fprintf(os.Stderr, "exact round %d/%d complete in %s: leaves=%d pruned=%d improved=%t\n",
			round+1, rounds, time.Since(roundStarted).Round(time.Millisecond), roundStats.visitedLeaves,
			roundStats.prunedAssignments, bestMask != 0)
		result.rounds++
		result.blockCandidates = max(result.blockCandidates, roundStats.blockCandidates)
		result.disjointRounds += roundStats.disjointRounds
		result.theoreticalAssignments += roundStats.theoreticalAssignments
		result.visitedLeaves += roundStats.visitedLeaves
		result.prunedSubtrees += roundStats.prunedSubtrees
		result.prunedAssignments += roundStats.prunedAssignments
		if result.rounds == 1 {
			result.baseNumerator = roundStats.baseNumerator
		}
		result.bestNumerator = roundStats.bestNumerator
		if bestMask == 0 {
			break
		}
		for index, candidate := range block {
			if bestMask&(uint64(1)<<index) != 0 {
				t.flips[candidate.node] ^= 1
			}
		}
		result.improvedRounds++
	}
	result.elapsed = time.Since(started)
	return result
}

func selectExactCandidateBlock(t *adaptiveTransform, candidates []candidateRange, sample []uint32,
	target [histogramBins]uint64, matcher *lpmMatcher, limit int) []candidateRange {
	mapped, lengths, current := buildAdaptiveSampleState(t, sample, matcher)
	currentNumerator := scaledL1Numerator(current, target)
	sampleTotal := uint64(len(sample))
	targetTotal := histogramTotal(target)
	h := &exactCandidateWorstHeap{}
	heap.Init(h)
	for _, candidate := range candidates {
		trial := current
		trialNumerator := currentNumerator
		changedPackets := 0
		bitMask := uint32(1) << (31 - candidate.depth)
		for index := candidate.start; index < candidate.end; index++ {
			oldLength := lengths[index]
			newLength := uint8(matcher.Match(mapped[index] ^ bitMask))
			if oldLength != newLength {
				changedPackets++
				moveHistogramPacket(&trial, oldLength, newLength, target, sampleTotal, targetTotal, &trialNumerator)
			}
		}
		ranked := rankedExactCandidate{candidate: candidate, trialNumerator: trialNumerator, changedPackets: changedPackets}
		if h.Len() < limit {
			heap.Push(h, ranked)
		} else if exactCandidateBetter(ranked, (*h)[0]) {
			heap.Pop(h)
			heap.Push(h, ranked)
		}
	}
	selected := make([]candidateRange, 0, h.Len())
	for h.Len() > 0 {
		selected = append(selected, heap.Pop(h).(rankedExactCandidate).candidate)
	}
	// High-mass variables are assigned first. In depth-first enumeration they
	// are toggled least often, reducing the total number of packet rematches.
	sort.Slice(selected, func(i, j int) bool {
		leftMass := selected[i].end - selected[i].start
		rightMass := selected[j].end - selected[j].start
		if leftMass != rightMass {
			return leftMass > rightMass
		}
		if selected[i].depth != selected[j].depth {
			return selected[i].depth < selected[j].depth
		}
		return selected[i].node < selected[j].node
	})
	return selected
}

func exactCandidateBetter(left, right rankedExactCandidate) bool {
	if left.trialNumerator != right.trialNumerator {
		return left.trialNumerator < right.trialNumerator
	}
	if left.changedPackets != right.changedPackets {
		return left.changedPackets > right.changedPackets
	}
	leftSampleMass := left.candidate.end - left.candidate.start
	rightSampleMass := right.candidate.end - right.candidate.start
	if leftSampleMass != rightSampleMass {
		return leftSampleMass > rightSampleMass
	}
	if left.candidate.mass != right.candidate.mass {
		return left.candidate.mass > right.candidate.mass
	}
	if left.candidate.depth != right.candidate.depth {
		return left.candidate.depth < right.candidate.depth
	}
	return left.candidate.node < right.candidate.node
}

func candidateRangesDisjoint(block []candidateRange) bool {
	ordered := append([]candidateRange(nil), block...)
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].start != ordered[j].start {
			return ordered[i].start < ordered[j].start
		}
		return ordered[i].end < ordered[j].end
	})
	for index := 1; index < len(ordered); index++ {
		if ordered[index].start < ordered[index-1].end {
			return false
		}
	}
	return true
}

func enumerateExactDisjointCandidateBlock(t *adaptiveTransform, block []candidateRange, sample []uint32,
	target [histogramBins]uint64, matcher *lpmMatcher) (uint64, exactSearchStats) {
	var stats exactSearchStats
	variableCount := len(block)
	if variableCount == 0 {
		return 0, stats
	}
	mapped, lengths, current := buildAdaptiveSampleState(t, sample, matcher)
	sampleTotal := uint64(len(sample))
	targetTotal := histogramTotal(target)
	stats.blockCandidates = variableCount
	stats.theoreticalAssignments = uint64(1) << variableCount
	stats.baseNumerator = scaledL1Numerator(current, target)
	stats.bestNumerator = stats.baseNumerator

	zero := make([][histogramBins]uint64, variableCount)
	one := make([][histogramBins]uint64, variableCount)
	fixed := current
	for variable, candidate := range block {
		bitMask := uint32(1) << (31 - candidate.depth)
		for index := candidate.start; index < candidate.end; index++ {
			oldLength := lengths[index]
			newLength := uint8(matcher.Match(mapped[index] ^ bitMask))
			zero[variable][oldLength]++
			one[variable][newLength]++
			fixed[oldLength]--
		}
	}

	addContribution := func(histogram *[histogramBins]uint64, contribution [histogramBins]uint64) {
		for prefixLength, count := range contribution {
			histogram[prefixLength] += count
		}
	}
	removeContribution := func(histogram *[histogramBins]uint64, contribution [histogramBins]uint64) {
		for prefixLength, count := range contribution {
			histogram[prefixLength] -= count
		}
	}
	bestMask := uint64(0)
	var visit func(depth int, assignment uint64)
	visit = func(depth int, assignment uint64) {
		lowerBound := fixedHistogramLowerBound(fixed, target, sampleTotal, targetTotal)
		if lowerBound >= stats.bestNumerator {
			stats.prunedSubtrees++
			stats.prunedAssignments += uint64(1) << (variableCount - depth)
			return
		}
		if depth == variableCount {
			stats.visitedLeaves++
			numerator := scaledL1Numerator(fixed, target)
			if numerator < stats.bestNumerator {
				stats.bestNumerator = numerator
				bestMask = assignment
			}
			return
		}
		addContribution(&fixed, zero[depth])
		visit(depth+1, assignment)
		removeContribution(&fixed, zero[depth])
		addContribution(&fixed, one[depth])
		visit(depth+1, assignment|(uint64(1)<<depth))
		removeContribution(&fixed, one[depth])
	}
	visit(0, 0)
	if stats.visitedLeaves+stats.prunedAssignments != stats.theoreticalAssignments {
		panic(fmt.Sprintf("disjoint exact search accounting mismatch: leaves=%d pruned=%d theoretical=%d",
			stats.visitedLeaves, stats.prunedAssignments, stats.theoreticalAssignments))
	}
	return bestMask, stats
}

func enumerateExactCandidateBlock(t *adaptiveTransform, block []candidateRange, sample []uint32,
	target [histogramBins]uint64, matcher *lpmMatcher) (uint64, exactSearchStats) {
	var stats exactSearchStats
	variableCount := len(block)
	if variableCount == 0 {
		return 0, stats
	}
	mapped, lengths, current := buildAdaptiveSampleState(t, sample, matcher)
	sampleTotal := uint64(len(sample))
	targetTotal := histogramTotal(target)
	currentNumerator := scaledL1Numerator(current, target)
	stats.blockCandidates = variableCount
	stats.theoreticalAssignments = uint64(1) << variableCount
	stats.baseNumerator = currentNumerator
	stats.bestNumerator = currentNumerator

	lastVariable := make([]int, len(sample))
	for index := range lastVariable {
		lastVariable[index] = -1
	}
	for variable, candidate := range block {
		for index := candidate.start; index < candidate.end; index++ {
			lastVariable[index] = variable
		}
	}
	fixedAt := make([][]int, variableCount)
	var fixed [histogramBins]uint64
	for index, variable := range lastVariable {
		if variable < 0 {
			fixed[lengths[index]]++
		} else {
			fixedAt[variable] = append(fixedAt[variable], index)
		}
	}

	bestMask := uint64(0)
	var visit func(depth int, assignment uint64)
	visit = func(depth int, assignment uint64) {
		lowerBound := fixedHistogramLowerBound(fixed, target, sampleTotal, targetTotal)
		if lowerBound >= stats.bestNumerator {
			stats.prunedSubtrees++
			covered := uint64(1) << (variableCount - depth)
			stats.prunedAssignments += covered
			return
		}
		if depth == variableCount {
			stats.visitedLeaves++
			if currentNumerator < stats.bestNumerator {
				stats.bestNumerator = currentNumerator
				bestMask = assignment
			}
			return
		}

		for _, packetIndex := range fixedAt[depth] {
			fixed[lengths[packetIndex]]++
		}
		visit(depth+1, assignment)
		for _, packetIndex := range fixedAt[depth] {
			fixed[lengths[packetIndex]]--
		}

		toggleCandidateSampleState(block[depth], mapped, lengths, &current, target, matcher,
			sampleTotal, targetTotal, &currentNumerator)
		for _, packetIndex := range fixedAt[depth] {
			fixed[lengths[packetIndex]]++
		}
		visit(depth+1, assignment|(uint64(1)<<depth))
		for _, packetIndex := range fixedAt[depth] {
			fixed[lengths[packetIndex]]--
		}
		toggleCandidateSampleState(block[depth], mapped, lengths, &current, target, matcher,
			sampleTotal, targetTotal, &currentNumerator)
	}
	visit(0, 0)
	if stats.visitedLeaves+stats.prunedAssignments != stats.theoreticalAssignments {
		panic(fmt.Sprintf("exact search accounting mismatch: leaves=%d pruned=%d theoretical=%d",
			stats.visitedLeaves, stats.prunedAssignments, stats.theoreticalAssignments))
	}
	return bestMask, stats
}

func buildAdaptiveSampleState(t *adaptiveTransform, sample []uint32, matcher *lpmMatcher) ([]uint32, []uint8, [histogramBins]uint64) {
	mapped := make([]uint32, len(sample))
	lengths := make([]uint8, len(sample))
	var histogram [histogramBins]uint64
	for index, ip := range sample {
		mapped[index] = t.Apply(ip)
		lengths[index] = uint8(matcher.Match(mapped[index]))
		histogram[lengths[index]]++
	}
	return mapped, lengths, histogram
}

func toggleCandidateSampleState(candidate candidateRange, mapped []uint32, lengths []uint8,
	histogram *[histogramBins]uint64, target [histogramBins]uint64, matcher *lpmMatcher,
	sampleTotal, targetTotal uint64, numerator *uint64) {
	bitMask := uint32(1) << (31 - candidate.depth)
	for index := candidate.start; index < candidate.end; index++ {
		mapped[index] ^= bitMask
		oldLength := lengths[index]
		newLength := uint8(matcher.Match(mapped[index]))
		if oldLength == newLength {
			continue
		}
		moveHistogramPacket(histogram, oldLength, newLength, target, sampleTotal, targetTotal, numerator)
		lengths[index] = newLength
	}
}

func scaledL1Numerator(histogram, target [histogramBins]uint64) uint64 {
	sampleTotal := histogramTotal(histogram)
	targetTotal := histogramTotal(target)
	var numerator uint64
	for prefixLength := 0; prefixLength < histogramBins; prefixLength++ {
		numerator += absUint64Difference(histogram[prefixLength]*targetTotal, target[prefixLength]*sampleTotal)
	}
	return numerator
}

func moveHistogramPacket(histogram *[histogramBins]uint64, oldLength, newLength uint8,
	target [histogramBins]uint64, sampleTotal, targetTotal uint64, numerator *uint64) {
	if oldLength == newLength {
		return
	}
	oldBefore := absUint64Difference(histogram[oldLength]*targetTotal, target[oldLength]*sampleTotal)
	newBefore := absUint64Difference(histogram[newLength]*targetTotal, target[newLength]*sampleTotal)
	histogram[oldLength]--
	histogram[newLength]++
	oldAfter := absUint64Difference(histogram[oldLength]*targetTotal, target[oldLength]*sampleTotal)
	newAfter := absUint64Difference(histogram[newLength]*targetTotal, target[newLength]*sampleTotal)
	before := oldBefore + newBefore
	after := oldAfter + newAfter
	if after >= before {
		*numerator += after - before
	} else {
		*numerator -= before - after
	}
}

func fixedHistogramLowerBound(fixed, target [histogramBins]uint64, sampleTotal, targetTotal uint64) uint64 {
	var unavoidableExcess uint64
	for prefixLength := 0; prefixLength < histogramBins; prefixLength++ {
		fixedScaled := fixed[prefixLength] * targetTotal
		targetScaled := target[prefixLength] * sampleTotal
		if fixedScaled > targetScaled {
			unavoidableExcess += fixedScaled - targetScaled
		}
	}
	return unavoidableExcess * 2
}

func absUint64Difference(left, right uint64) uint64 {
	if left >= right {
		return left - right
	}
	return right - left
}

func histogramForSample(sample []uint32, t transform, matcher *lpmMatcher) [histogramBins]uint64 {
	var histogram [histogramBins]uint64
	for _, ip := range sample {
		histogram[matcher.Match(t.Apply(ip))]++
	}
	return histogram
}

func sampleTV(sample []uint32, t transform, matcher *lpmMatcher, target [histogramBins]uint64) float64 {
	return histogramTV(histogramForSample(sample, t, matcher), target)
}

func histogramTV(actual, target [histogramBins]uint64) float64 {
	return compareDistribution(actual, target).totalVariation
}

func compareDistribution(actual, target [histogramBins]uint64) distributionMetrics {
	actualTotal := histogramTotal(actual)
	targetTotal := histogramTotal(target)
	metrics := distributionMetrics{total: actualTotal}
	if actualTotal == 0 || targetTotal == 0 {
		return metrics
	}
	for prefixLength := 0; prefixLength < histogramBins; prefixLength++ {
		p := float64(actual[prefixLength]) / float64(actualTotal)
		q := float64(target[prefixLength]) / float64(targetTotal)
		difference := math.Abs(p - q)
		metrics.totalVariation += difference * 0.5
		if difference > metrics.maxBinAbsoluteDiff {
			metrics.maxBinAbsoluteDiff = difference
		}
		mean := (p + q) * 0.5
		if p > 0 {
			metrics.jensenShannon += 0.5 * p * math.Log(p/mean)
		}
		if q > 0 {
			metrics.jensenShannon += 0.5 * q * math.Log(q/mean)
		}
		metrics.meanPrefixLength += float64(prefixLength) * p
		metrics.targetMeanPrefix += float64(prefixLength) * q
	}
	metrics.meanPrefixDelta = metrics.meanPrefixLength - metrics.targetMeanPrefix
	return metrics
}

func histogramTotal(histogram [histogramBins]uint64) uint64 {
	var total uint64
	for _, count := range histogram {
		total += count
	}
	return total
}

type reservoirSampler struct {
	values []uint32
	limit  int
	seen   uint64
	state  uint64
}

func newReservoir(limit int) *reservoirSampler {
	return &reservoirSampler{limit: limit, state: 0x9e3779b97f4a7c15}
}

func (r *reservoirSampler) Add(value uint32) {
	r.seen++
	if len(r.values) < r.limit {
		r.values = append(r.values, value)
		return
	}
	r.state ^= r.state << 13
	r.state ^= r.state >> 7
	r.state ^= r.state << 17
	index := r.state % r.seen
	if index < uint64(r.limit) {
		r.values[index] = value
	}
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

func writeTransformedTrace(opts options, t transform) error {
	file, err := os.Create(opts.outputTrace)
	if err != nil {
		return err
	}
	writer := bufio.NewWriterSize(file, 4*1024*1024)
	sequence := uint64(0)
	_, scanErr := scanTrace(opts.inputTrace, opts.maxPackets, opts.progressInterval, func(packet tracePacket) error {
		var row []byte
		row = strconv.AppendUint(row, sequence, 10)
		row = append(row, ",64,"...)
		row = appendIPv4(row, packet.src)
		row = append(row, ',')
		row = appendIPv4(row, t.Apply(packet.dst))
		row = append(row, ',')
		row = append(row, packet.proto...)
		row = append(row, ",0,0\n"...)
		sequence++
		_, err := writer.Write(row)
		return err
	})
	flushErr := writer.Flush()
	closeErr := file.Close()
	if scanErr != nil {
		return scanErr
	}
	if flushErr != nil {
		return flushErr
	}
	return closeErr
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

func writeMapping(path string, mapping savedMapping) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	gzipWriter := gzip.NewWriter(file)
	encodeErr := gob.NewEncoder(gzipWriter).Encode(mapping)
	closeGzipErr := gzipWriter.Close()
	closeFileErr := file.Close()
	if encodeErr != nil {
		return encodeErr
	}
	if closeGzipErr != nil {
		return closeGzipErr
	}
	return closeFileErr
}

func readMapping(path string) (savedMapping, error) {
	var mapping savedMapping
	file, err := os.Open(path)
	if err != nil {
		return mapping, err
	}
	defer file.Close()
	gzipReader, err := gzip.NewReader(file)
	if err != nil {
		return mapping, err
	}
	decodeErr := gob.NewDecoder(gzipReader).Decode(&mapping)
	closeErr := gzipReader.Close()
	if decodeErr != nil {
		return mapping, decodeErr
	}
	return mapping, closeErr
}

func writeReports(opts options, methods []methodResult, target [histogramBins]uint64, targetStats, inputStats scanStats, ruleCount int, started, finished time.Time) error {
	if err := writeMethodSummary(filepath.Join(opts.outputDir, "method_summary.csv"), methods); err != nil {
		return err
	}
	if err := writeDistribution(filepath.Join(opts.outputDir, "lpm_distribution_comparison.csv"), methods, target); err != nil {
		return err
	}
	return writeMarkdown(filepath.Join(opts.outputDir, "REPORT.md"), opts, methods, target, targetStats, inputStats, ruleCount, started, finished)
}

func writeMethodSummary(path string, methods []methodResult) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	if err := writer.Write([]string{"method", "best_transformed", "packets", "tv_distance", "jensen_shannon", "mean_lpm", "target_mean_lpm", "mean_lpm_delta", "max_bin_abs_diff", "sample_tv", "flip_count", "description", "subtree_hit_before", "subtree_hit_after", "set_load_before", "set_load_after", "combined_before", "combined_after", "subtree_seed_tv", "subtree_final_tv", "subtree_tv_limit", "subtree_upper_accepted", "subtree_lower_accepted", "exact_block_candidates", "exact_rounds", "exact_improved_rounds", "exact_disjoint_rounds", "exact_theoretical_assignments", "exact_visited_leaves", "exact_pruned_subtrees", "exact_pruned_assignments", "exact_elapsed"}); err != nil {
		return err
	}
	for _, method := range methods {
		m := method.metrics
		subtreeBefore, subtreeAfter, setLoadBefore, setLoadAfter, combinedBefore, combinedAfter := "", "", "", "", "", ""
		subtreeSeedTV, subtreeFinalTV, subtreeTVLimit := "", "", ""
		subtreeUpper, subtreeLower := "", ""
		if method.subtree != nil {
			subtreeBefore = fmt.Sprintf("%.12f", method.subtree.beforeScore)
			subtreeAfter = fmt.Sprintf("%.12f", method.subtree.afterScore)
			setLoadBefore = fmt.Sprintf("%.12f", method.subtree.setLoadBefore)
			setLoadAfter = fmt.Sprintf("%.12f", method.subtree.setLoadAfter)
			combinedBefore = fmt.Sprintf("%.12f", method.subtree.combinedBefore)
			combinedAfter = fmt.Sprintf("%.12f", method.subtree.combinedAfter)
			subtreeSeedTV = fmt.Sprintf("%.12f", method.subtree.seedTV)
			subtreeFinalTV = fmt.Sprintf("%.12f", method.subtree.finalTV)
			subtreeTVLimit = fmt.Sprintf("%.12f", method.subtree.tvLimit)
			subtreeUpper = strconv.Itoa(method.subtree.upperAccepted)
			subtreeLower = strconv.Itoa(method.subtree.lowerAccepted)
		}
		if err := writer.Write([]string{
			method.name, strconv.FormatBool(method.best), strconv.FormatUint(m.total, 10),
			fmt.Sprintf("%.12f", m.totalVariation), fmt.Sprintf("%.12f", m.jensenShannon),
			fmt.Sprintf("%.8f", m.meanPrefixLength), fmt.Sprintf("%.8f", m.targetMeanPrefix), fmt.Sprintf("%.8f", m.meanPrefixDelta),
			fmt.Sprintf("%.12f", m.maxBinAbsoluteDiff), fmt.Sprintf("%.12f", method.sampleTV),
			strconv.Itoa(method.transform.FlipCount()), method.transform.Description(),
			subtreeBefore, subtreeAfter, setLoadBefore, setLoadAfter, combinedBefore, combinedAfter,
			subtreeSeedTV, subtreeFinalTV, subtreeTVLimit, subtreeUpper, subtreeLower,
			strconv.Itoa(method.exact.blockCandidates), strconv.Itoa(method.exact.rounds), strconv.Itoa(method.exact.improvedRounds), strconv.Itoa(method.exact.disjointRounds),
			strconv.FormatUint(method.exact.theoreticalAssignments, 10), strconv.FormatUint(method.exact.visitedLeaves, 10),
			strconv.FormatUint(method.exact.prunedSubtrees, 10), strconv.FormatUint(method.exact.prunedAssignments, 10),
			method.exact.elapsed.Round(time.Millisecond).String(),
		}); err != nil {
			return err
		}
	}
	return writer.Error()
}

func writeDistribution(path string, methods []methodResult, target [histogramBins]uint64) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	defer writer.Flush()
	if err := writer.Write([]string{"method", "lpm_prefix_length", "count", "ratio", "target_count", "target_ratio", "ratio_delta", "abs_ratio_delta"}); err != nil {
		return err
	}
	targetTotal := histogramTotal(target)
	for _, method := range methods {
		total := histogramTotal(method.hist)
		for prefixLength := 0; prefixLength < histogramBins; prefixLength++ {
			ratio := safeRatio(method.hist[prefixLength], total)
			targetRatio := safeRatio(target[prefixLength], targetTotal)
			delta := ratio - targetRatio
			if err := writer.Write([]string{
				method.name, strconv.Itoa(prefixLength), strconv.FormatUint(method.hist[prefixLength], 10), fmt.Sprintf("%.12f", ratio),
				strconv.FormatUint(target[prefixLength], 10), fmt.Sprintf("%.12f", targetRatio), fmt.Sprintf("%.12f", delta), fmt.Sprintf("%.12f", math.Abs(delta)),
			}); err != nil {
				return err
			}
		}
	}
	return writer.Error()
}

func writeMarkdown(path string, opts options, methods []methodResult, target [histogramBins]uint64, targetStats, inputStats scanStats, ruleCount int, started, finished time.Time) error {
	best := methods[1]
	for _, method := range methods[1:] {
		if method.best {
			best = method
			break
		}
	}
	baseline := methods[0]
	targetLabel := opts.targetTrace
	targetFlag := "--target-trace"
	if opts.targetDistribution != "" {
		targetLabel = opts.targetDistribution
		targetFlag = "--target-distribution"
	}
	lines := []string{
		"# Anonymous trace tree LPM remapping",
		"",
		"## Result",
		"",
		fmt.Sprintf("- best transformed method: `%s`", best.name),
		fmt.Sprintf("- target-distribution TV distance: `%.8f` (baseline `%.8f`)", best.metrics.totalVariation, baseline.metrics.totalVariation),
		fmt.Sprintf("- relative TV reduction: `%.2f%%`", relativeReduction(baseline.metrics.totalVariation, best.metrics.totalVariation)*100),
		fmt.Sprintf("- transformed trace: `%s`", opts.outputTrace),
		"- mapping: `best_mapping.gob.gz`",
		"",
		"## Inputs",
		"",
		fmt.Sprintf("- rule: `%s` (%d prefixes)", opts.ruleFile, ruleCount),
		fmt.Sprintf("- target LPM distribution source: `%s`", targetLabel),
		fmt.Sprintf("- anonymized input: `%s`", opts.inputTrace),
		fmt.Sprintf("- supplied initial mapping: `%s`", opts.initialMapping),
		fmt.Sprintf("- valid target/input packets: `%d` / `%d`", targetStats.validPackets, inputStats.validPackets),
		fmt.Sprintf("- filter: IPv4 TCP/UDP, matching `cmd/windowed_hitrate`"),
		fmt.Sprintf("- rotation depth: `/%d`", opts.fitDepth),
		fmt.Sprintf("- optimization reservoir: `%d` packets", opts.sampleSize),
		fmt.Sprintf("- LPM hill-climb candidate budget: `%d` nodes", opts.hillCandidates),
		fmt.Sprintf("- selected LPM hill-climb candidates: `%d` nodes", opts.selectedCandidates),
		fmt.Sprintf("- all sample-active candidate nodes: `%t`", opts.allActiveCandidates),
		fmt.Sprintf("- candidate traversal order: `%s`", opts.candidateOrder),
		fmt.Sprintf("- exact full-trace greedy mode: `%t`", opts.fullTraceGreedy),
		fmt.Sprintf("- LPM hill-climb passes: `%d`", opts.hillPasses),
		fmt.Sprintf("- exact block variables / rounds: `%d` / `%d`", opts.exactBlockCandidates, opts.exactRounds),
		fmt.Sprintf("- traffic-decile /16 hit-node fitting: `%t`", opts.subtreeHitFit),
		fmt.Sprintf("- set-load weight: `%.6f`", opts.setLoadWeight),
		fmt.Sprintf("- set model: `%d` sets, `%d`-way, CRC32 over destination `/%d`", opts.setCount, opts.setWay, opts.setIndexDepth),
		fmt.Sprintf("- LPM-TV epsilon above seed: `%.6f`", opts.lpmEpsilon),
		"- rotations may cross historical class A/B/C/D boundaries; packet order and multiplicity are unchanged.",
		"",
		"## Method comparison",
		"",
		"| method | TV distance | JSD | mean LPM | delta | sample TV | flips | selected |",
		"| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
	}
	for _, method := range methods {
		lines = append(lines, fmt.Sprintf("| %s | %.8f | %.8f | %.4f | %+.4f | %.8f | %d | %t |",
			method.name, method.metrics.totalVariation, method.metrics.jensenShannon, method.metrics.meanPrefixLength,
			method.metrics.meanPrefixDelta, method.sampleTV, method.transform.FlipCount(), method.best))
	}
	for _, method := range methods {
		if method.subtree == nil {
			continue
		}
		lines = append(lines,
			"",
			"## Traffic-decile /16 hit-node fitting",
			"",
			"The objective is the mean TV distance between target and transformed distributions of `h16..h24`, evaluated separately in each packet-mass decile of active `/16`s.",
			fmt.Sprintf("- hit-distribution score: `%.8f` -> `%.8f`", method.subtree.beforeScore, method.subtree.afterScore),
			fmt.Sprintf("- set-load score: `%.8f` -> `%.8f`", method.subtree.setLoadBefore, method.subtree.setLoadAfter),
			fmt.Sprintf("- combined score: `%.8f` -> `%.8f`", method.subtree.combinedBefore, method.subtree.combinedAfter),
			fmt.Sprintf("- LPM-TV seed / final / limit: `%.8f` / `%.8f` / `%.8f`", method.subtree.seedTV, method.subtree.finalTV, method.subtree.tvLimit),
			fmt.Sprintf("- accepted upper (`/0..15`) rotations: `%d`", method.subtree.upperAccepted),
			fmt.Sprintf("- accepted lower (`/16..23`) rotations: `%d`", method.subtree.lowerAccepted),
			"- packet multiplicity determines traffic deciles and weights each `/16`; distinct matched routing prefixes determine each hit vector.",
			"- set-load vectors contain unique cache keys, active sets, peak keys per set, keys beyond associativity, overloaded sets, and non-cacheable destinations.",
		)
	}
	for _, method := range methods {
		if method.exact.rounds == 0 {
			continue
		}
		lines = append(lines,
			"",
			"## Exact block search",
			"",
			fmt.Sprintf("- method: `%s`", method.name),
			fmt.Sprintf("- exact variables per completed block: `%d`", method.exact.blockCandidates),
			fmt.Sprintf("- completed / improving rounds: `%d` / `%d`", method.exact.rounds, method.exact.improvedRounds),
			fmt.Sprintf("- disjoint-prefix fast rounds: `%d`", method.exact.disjointRounds),
			fmt.Sprintf("- assignments covered exactly: `%d`", method.exact.theoreticalAssignments),
			fmt.Sprintf("- visited leaves: `%d`", method.exact.visitedLeaves),
			fmt.Sprintf("- pruned subtrees / assignments: `%d` / `%d`", method.exact.prunedSubtrees, method.exact.prunedAssignments),
			fmt.Sprintf("- exact-search elapsed: `%s`", method.exact.elapsed.Round(time.Millisecond)),
			"- pruning uses an admissible lower bound that allows every not-yet-fixed packet to move to any LPM bin.",
			"- this proves the optimum over each selected block; selection of a block from the full candidate set remains a block-coordinate strategy.",
		)
	}
	lines = append(lines,
		"",
		"## Files",
		"",
		"- `method_summary.csv`",
		"- `lpm_distribution_comparison.csv`",
		"- `best_mapping.gob.gz`",
		"- `lpm_seed_trace.txt` when `--subtree-hit-fit` is enabled",
		"",
		"## Runtime",
		"",
		fmt.Sprintf("- started: `%s`", started.Format(time.RFC3339)),
		fmt.Sprintf("- finished: `%s`", finished.Format(time.RFC3339)),
		fmt.Sprintf("- elapsed: `%s`", finished.Sub(started).Round(time.Second)),
		"",
		"## Rerun",
		"",
		"```bash",
		"go run ./cmd/fit_trace_tree_lpm \\",
		fmt.Sprintf("  --rulefile %s \\", opts.ruleFile),
		fmt.Sprintf("  %s %s \\", targetFlag, targetLabel),
		fmt.Sprintf("  --input-trace %s \\", opts.inputTrace),
		fmt.Sprintf("  --max %d \\", opts.maxPackets),
		fmt.Sprintf("  --fit-depth %d \\", opts.fitDepth),
		fmt.Sprintf("  --sample-size %d \\", opts.sampleSize),
		fmt.Sprintf("  --hill-candidates %d \\", opts.hillCandidates),
		fmt.Sprintf("  --hill-passes %d \\", opts.hillPasses),
		fmt.Sprintf("  --candidate-order %s \\", opts.candidateOrder),
	)
	if opts.allActiveCandidates {
		lines = append(lines, "  --all-active-candidates \\")
	}
	if opts.fullTraceGreedy {
		lines = append(lines, "  --full-trace-greedy \\")
	}
	if opts.subtreeHitFit {
		lines = append(lines,
			"  --subtree-hit-fit \\",
			fmt.Sprintf("  --lpm-epsilon %.6f \\", opts.lpmEpsilon),
			fmt.Sprintf("  --set-load-weight %.6f \\", opts.setLoadWeight),
			fmt.Sprintf("  --set-count %d \\", opts.setCount),
			fmt.Sprintf("  --set-way %d \\", opts.setWay),
			fmt.Sprintf("  --set-index-depth %d \\", opts.setIndexDepth),
		)
	}
	if opts.exactBlockCandidates > 0 {
		lines = append(lines,
			fmt.Sprintf("  --exact-block-candidates %d \\", opts.exactBlockCandidates),
			fmt.Sprintf("  --exact-rounds %d \\", opts.exactRounds),
		)
	}
	if opts.initialMapping != "" {
		lines = append(lines, fmt.Sprintf("  --initial-mapping %s \\", opts.initialMapping))
	}
	lines = append(lines,
		fmt.Sprintf("  --output-trace %s \\", opts.outputTrace),
		fmt.Sprintf("  --output-dir %s", opts.outputDir),
		"```",
		"",
	)
	_ = target
	return os.WriteFile(path, []byte(strings.Join(lines, "\n")), 0o644)
}

func safeRatio(value, total uint64) float64 {
	if total == 0 {
		return 0
	}
	return float64(value) / float64(total)
}

func relativeReduction(baseline, value float64) float64 {
	if baseline == 0 {
		return 0
	}
	return (baseline - value) / baseline
}

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
