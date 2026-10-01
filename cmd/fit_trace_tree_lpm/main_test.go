package main

import (
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestAdaptiveTransformPreservesSharedPrefixesWithoutClassConstraint(t *testing.T) {
	transform := &adaptiveTransform{
		method: "test",
		depth:  24,
		flips:  make([]byte, 1<<24),
	}
	// The root rotation deliberately crosses historical class boundaries.
	transform.flips[1] = 1
	transform.flips[2] = 1
	transform.flips[6] = 1
	transform.flips[20] = 1
	transform.flips[41] = 1

	pairs := [][2]uint32{
		{0x0a010203, 0x0a0102ff},
		{0x80abcdef, 0x80abc001},
		{0xc0a80101, 0xc0a8ffff},
	}
	for _, pair := range pairs {
		before := commonPrefixLength(pair[0], pair[1])
		after := commonPrefixLength(transform.Apply(pair[0]), transform.Apply(pair[1]))
		if before != after {
			t.Fatalf("shared prefix changed: before /%d after /%d", before, after)
		}
	}

	mapped := transform.Apply(0x0a000001)
	if mapped>>31 != 1 {
		t.Fatalf("root rotation should be allowed to cross a class boundary: %08x -> %08x", uint32(0x0a000001), mapped)
	}
}

func TestCompareDistribution(t *testing.T) {
	var target, equal, different [histogramBins]uint64
	target[16], target[24] = 25, 75
	equal[16], equal[24] = 50, 150
	different[8] = 200
	if got := compareDistribution(equal, target).totalVariation; got != 0 {
		t.Fatalf("equal normalized distributions: TV=%f", got)
	}
	if got := compareDistribution(different, target).totalVariation; got < 0.999999 {
		t.Fatalf("disjoint distributions should have TV=1: %f", got)
	}
}

func TestRulePrefixParsing(t *testing.T) {
	network, length, err := parseRulePrefix([]string{"192.0.2.129", "24", "next-hop"})
	if err != nil {
		t.Fatal(err)
	}
	if length != 24 || network != 0xc0000200 {
		t.Fatalf("got %08x/%d", network, length)
	}
	network, length, err = parseRulePrefix([]string{"198.51.100.9/20", "next-hop"})
	if err != nil {
		t.Fatal(err)
	}
	if length != 20 || network != 0xc6336000 {
		t.Fatalf("got %08x/%d", network, length)
	}
}

func TestMatchPrefixReturnsSelectedRoutingEntry(t *testing.T) {
	matcher := &lpmMatcher{by24: make([]uint8, 1<<24)}
	matcher.by24[0xc00002] = 24
	matcher.by24[0xc63364] = 16
	matcher.longer[25] = map[uint32]struct{}{0xc0000280: {}}
	matcher.longLengths = []int{25}

	tests := []struct {
		ip      uint32
		network uint32
		length  int
	}{
		{ip: 0xc0000281, network: 0xc0000280, length: 25},
		{ip: 0xc0000201, network: 0xc0000200, length: 24},
		{ip: 0xc6336401, network: 0xc6330000, length: 16},
	}
	for _, test := range tests {
		got := matcher.MatchPrefix(test.ip)
		if got.network != test.network || got.length != test.length {
			t.Fatalf("MatchPrefix(%08x)=%08x/%d want %08x/%d", test.ip, got.network, got.length, test.network, test.length)
		}
		if matcher.Match(test.ip) != test.length {
			t.Fatalf("Match compatibility failed for %08x", test.ip)
		}
	}
}

func TestHitSignatureCountsDistinctMatchedPrefixes(t *testing.T) {
	matcher := &lpmMatcher{by24: make([]uint8, 1<<24)}
	mapped := []uint32{0x0a010101, 0x0a0101fe, 0x0a010201, 0x0a020101}
	for _, ip := range mapped {
		matcher.by24[ip>>8] = 24
	}
	signature := hitSignatureForRange(mapped, 0, 3, matcher)
	if signature[24-16] != 2 {
		t.Fatalf("h24=%d want 2", signature[24-16])
	}
	if signature[16-16] != 0 {
		t.Fatalf("h16=%d want 0", signature[16-16])
	}
}

func TestHitDistributionTV(t *testing.T) {
	groups := make([]trafficGroup, 10)
	for decile := range groups {
		groups[decile].decile = decile
		groups[decile].packets = uint64(decile + 1)
		groups[decile].signature[0] = 1
	}
	equal := distributionForGroups(groups)
	if score := hitDistributionTV(equal, equal, groups, groups); score != 0 {
		t.Fatalf("equal hit distributions: score=%f", score)
	}
	differentGroups := append([]trafficGroup(nil), groups...)
	for index := range differentGroups {
		differentGroups[index].signature[0] = 0
	}
	different := distributionForGroups(differentGroups)
	if score := hitDistributionTV(equal, different, groups, differentGroups); score <= 0 {
		t.Fatalf("different hit distributions should have positive score: %f", score)
	}
}

func TestLoadTargetHistogramFromComparisonCSV(t *testing.T) {
	path := filepath.Join(t.TempDir(), "distribution.csv")
	var rows strings.Builder
	rows.WriteString("method,lpm_prefix_length,count,target_count\n")
	for prefixLength := 0; prefixLength < histogramBins; prefixLength++ {
		rows.WriteString("baseline-anonymized,")
		rows.WriteString(strconv.Itoa(prefixLength))
		rows.WriteString(",999,")
		rows.WriteString(strconv.Itoa(prefixLength + 1))
		rows.WriteByte('\n')
	}
	// Existing comparison files repeat the same target histogram for every method.
	for prefixLength := 0; prefixLength < histogramBins; prefixLength++ {
		rows.WriteString("adaptive-lpm-direct,")
		rows.WriteString(strconv.Itoa(prefixLength))
		rows.WriteString(",123,")
		rows.WriteString(strconv.Itoa(prefixLength + 1))
		rows.WriteByte('\n')
	}
	if err := os.WriteFile(path, []byte(rows.String()), 0o644); err != nil {
		t.Fatal(err)
	}
	histogram, err := loadTargetHistogram(path)
	if err != nil {
		t.Fatal(err)
	}
	for prefixLength, count := range histogram {
		if want := uint64(prefixLength + 1); count != want {
			t.Fatalf("/%d count=%d want=%d", prefixLength, count, want)
		}
	}
}

func TestBuildAllActiveCandidateRanges(t *testing.T) {
	sample := []uint32{0x10000000, 0x20000000, 0x50000000, 0x90000000}
	tree := make([]uint32, 1<<4)
	for node := range tree {
		tree[node] = uint32(node)
	}
	candidates := buildAllActiveCandidateRanges(sample, tree, 3)
	// /0: 1 prefix; /1: 2 prefixes; /2: 3 represented prefixes.
	if len(candidates) != 6 {
		t.Fatalf("candidate count=%d want=6", len(candidates))
	}
	var covered [3]int
	for _, candidate := range candidates {
		covered[candidate.depth] += candidate.end - candidate.start
	}
	for depth, count := range covered {
		if count != len(sample) {
			t.Fatalf("depth %d covers %d samples want %d", depth, count, len(sample))
		}
	}
}

func TestFullTraceGreedyWeightedIsExactAndMonotonic(t *testing.T) {
	destinations := []uint32{0x10000001, 0x50000002, 0x90000003, 0xd0000004}
	weights := []uint64{7, 2, 5, 1}
	matcher := &lpmMatcher{by24: make([]uint8, 1<<24)}
	lengthByTopTwo := []uint8{8, 16, 24, 12}
	for _, ip := range destinations {
		for topTwo, length := range lengthByTopTwo {
			mapped := (ip & 0x3fffffff) | (uint32(topTwo) << 30)
			matcher.by24[mapped>>8] = length
		}
	}

	tree := make([]uint32, 1<<3)
	for index, ip := range destinations {
		leaf := 4 + int(ip>>30)
		tree[leaf] += uint32(weights[index])
	}
	buildAggregateTree(tree, 4)
	candidates := buildAllActiveCandidateRanges(destinations, tree, 2)
	orderGreedyCandidateRanges(candidates, "top-down")
	transform := &adaptiveTransform{method: "test", depth: 2, flips: make([]byte, 1<<2)}
	var target [histogramBins]uint64
	target[24] = 15

	var before [histogramBins]uint64
	for index, ip := range destinations {
		before[matcher.Match(ip)] += weights[index]
	}
	refineAdaptiveLPMWeighted(transform, candidates, destinations, weights, target, matcher, 1)
	var after [histogramBins]uint64
	for index, ip := range destinations {
		mapped := transform.Apply(ip)
		if mapped&0xff != ip&0xff {
			t.Fatalf("lower eight bits changed: %08x -> %08x", ip, mapped)
		}
		after[matcher.Match(mapped)] += weights[index]
	}
	if scaledL1Numerator(after, target) > scaledL1Numerator(before, target) {
		t.Fatalf("full-trace greedy worsened TV numerator: before=%d after=%d",
			scaledL1Numerator(before, target), scaledL1Numerator(after, target))
	}
	if transform.FlipCount() == 0 {
		t.Fatal("test fixture should accept at least one improving rotation")
	}
}

func TestGreedyCandidateOrderUsesDepthThenPrefix(t *testing.T) {
	input := []candidateRange{
		{candidateNode: candidateNode{node: 6, depth: 2}},
		{candidateNode: candidateNode{node: 1, depth: 0}},
		{candidateNode: candidateNode{node: 3, depth: 1}},
		{candidateNode: candidateNode{node: 2, depth: 1}},
	}
	topDown := append([]candidateRange(nil), input...)
	orderGreedyCandidateRanges(topDown, "top-down")
	wantTop := []uint32{1, 2, 3, 6}
	for index, want := range wantTop {
		if topDown[index].node != want {
			t.Fatalf("top-down node[%d]=%d want=%d", index, topDown[index].node, want)
		}
	}
	bottomUp := append([]candidateRange(nil), input...)
	orderGreedyCandidateRanges(bottomUp, "bottom-up")
	wantBottom := []uint32{6, 2, 3, 1}
	for index, want := range wantBottom {
		if bottomUp[index].node != want {
			t.Fatalf("bottom-up node[%d]=%d want=%d", index, bottomUp[index].node, want)
		}
	}
}

func TestExactCandidateBlockMatchesBruteForce(t *testing.T) {
	sample := []uint32{0x10000001, 0x20000002, 0x90000003, 0xa0000004}
	matcher := &lpmMatcher{by24: make([]uint8, 1<<24)}
	lengthByTopTwo := []uint8{8, 16, 24, 12}
	for _, ip := range sample {
		for topTwo, length := range lengthByTopTwo {
			mapped := (ip & 0x3fffffff) | (uint32(topTwo) << 30)
			matcher.by24[mapped>>8] = length
		}
	}
	block := []candidateRange{
		{candidateNode: candidateNode{node: 1, depth: 0, mass: 4}, start: 0, end: 4},
		{candidateNode: candidateNode{node: 2, depth: 1, mass: 2}, start: 0, end: 2},
		{candidateNode: candidateNode{node: 3, depth: 1, mass: 2}, start: 2, end: 4},
	}
	var target [histogramBins]uint64
	target[8], target[24] = 1, 3
	base := &adaptiveTransform{method: "test", depth: 2, flips: make([]byte, 1<<2)}
	bestMask, stats := enumerateExactCandidateBlock(base, block, sample, target, matcher)

	bruteBest := math.Inf(1)
	for mask := uint64(0); mask < uint64(1)<<len(block); mask++ {
		trial := cloneAdaptive(base, "trial", "")
		for index, candidate := range block {
			if mask&(uint64(1)<<index) != 0 {
				trial.flips[candidate.node] ^= 1
			}
		}
		score := sampleTV(sample, trial, matcher, target)
		if score < bruteBest {
			bruteBest = score
		}
	}
	best := cloneAdaptive(base, "best", "")
	for index, candidate := range block {
		if bestMask&(uint64(1)<<index) != 0 {
			best.flips[candidate.node] ^= 1
		}
	}
	if got := sampleTV(sample, best, matcher, target); math.Abs(got-bruteBest) > 1e-15 {
		t.Fatalf("exact score=%g brute score=%g mask=%03b", got, bruteBest, bestMask)
	}
	if stats.theoreticalAssignments != 8 {
		t.Fatalf("theoretical assignments=%d want=8", stats.theoreticalAssignments)
	}
	if stats.visitedLeaves+stats.prunedAssignments != stats.theoreticalAssignments {
		t.Fatalf("accounting leaves=%d pruned=%d theoretical=%d",
			stats.visitedLeaves, stats.prunedAssignments, stats.theoreticalAssignments)
	}
}

func TestDisjointExactCandidateBlockMatchesGenericSearch(t *testing.T) {
	sample := []uint32{0x10000001, 0x20000002, 0x90000003, 0xa0000004}
	matcher := &lpmMatcher{by24: make([]uint8, 1<<24)}
	lengthByTopTwo := []uint8{8, 16, 24, 12}
	for _, ip := range sample {
		for topTwo, length := range lengthByTopTwo {
			mapped := (ip & 0x3fffffff) | (uint32(topTwo) << 30)
			matcher.by24[mapped>>8] = length
		}
	}
	block := []candidateRange{
		{candidateNode: candidateNode{node: 2, depth: 1, mass: 2}, start: 0, end: 2},
		{candidateNode: candidateNode{node: 3, depth: 1, mass: 2}, start: 2, end: 4},
	}
	if !candidateRangesDisjoint(block) {
		t.Fatal("two child-prefix ranges should be disjoint")
	}
	var target [histogramBins]uint64
	target[8], target[24] = 1, 3
	base := &adaptiveTransform{method: "test", depth: 2, flips: make([]byte, 1<<2)}
	disjointMask, disjointStats := enumerateExactDisjointCandidateBlock(base, block, sample, target, matcher)
	genericMask, genericStats := enumerateExactCandidateBlock(base, block, sample, target, matcher)

	scoreForMask := func(mask uint64) float64 {
		trial := cloneAdaptive(base, "trial", "")
		for index, candidate := range block {
			if mask&(uint64(1)<<index) != 0 {
				trial.flips[candidate.node] ^= 1
			}
		}
		return sampleTV(sample, trial, matcher, target)
	}
	if left, right := scoreForMask(disjointMask), scoreForMask(genericMask); math.Abs(left-right) > 1e-15 {
		t.Fatalf("disjoint score=%g generic score=%g", left, right)
	}
	for name, stats := range map[string]exactSearchStats{"disjoint": disjointStats, "generic": genericStats} {
		if stats.visitedLeaves+stats.prunedAssignments != stats.theoreticalAssignments {
			t.Fatalf("%s accounting leaves=%d pruned=%d theoretical=%d", name, stats.visitedLeaves, stats.prunedAssignments, stats.theoreticalAssignments)
		}
	}
}

func TestMappingRoundTrip(t *testing.T) {
	want := savedMapping{Method: "adaptive-lpm-test", Depth: 4, Flips: []byte{0, 1, 0, 1}}
	path := filepath.Join(t.TempDir(), "mapping.gob.gz")
	if err := writeMapping(path, want); err != nil {
		t.Fatal(err)
	}
	got, err := readMapping(path)
	if err != nil {
		t.Fatal(err)
	}
	if got.Method != want.Method || got.Depth != want.Depth || len(got.Flips) != len(want.Flips) {
		t.Fatalf("mapping mismatch: got=%+v want=%+v", got, want)
	}
	for index := range want.Flips {
		if got.Flips[index] != want.Flips[index] {
			t.Fatalf("flip %d=%d want=%d", index, got.Flips[index], want.Flips[index])
		}
	}
}

func commonPrefixLength(left, right uint32) int {
	value := left ^ right
	for length := 0; length < 32; length++ {
		if value&(uint32(1)<<(31-length)) != 0 {
			return length
		}
	}
	return 32
}
