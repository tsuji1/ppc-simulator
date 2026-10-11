// remap_trace_fib builds real-derived synthetic traces (#82): the packet order,
// repeat pattern and popularity of an (anonymized) trace are kept, and only the
// destination addresses are re-mapped onto addresses covered by a FIB.
//
//	remap    : write a remapped text trace and the mapping metadata
//	fidelity : compare traces under one rule file (LPM, popularity, reuse, sets)
//
// Methods:
//
//	r1-addr  : ATC type.  Every distinct destination address is mapped one-to-one
//	           to a random address inside a uniformly chosen FIB prefix.  Popularity
//	           and temporal locality are kept; prefix sharing between addresses is not.
//	r2-block : BMCache type.  Every distinct destination /24 is mapped one-to-one to
//	           a random /24 inside a uniformly chosen FIB prefix (length <= 24), and
//	           the lower 8 bits are kept, so addresses sharing a /24 still share one.
package main

import (
	"bufio"
	"compress/gzip"
	"encoding/csv"
	"flag"
	"fmt"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		fatalf("usage: remap_trace_fib remap|fidelity [flags]")
	}
	switch os.Args[1] {
	case "remap":
		runRemap(os.Args[2:])
	case "fidelity":
		runFidelity(os.Args[2:])
	default:
		fatalf("unknown subcommand %q", os.Args[1])
	}
}

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}

// ---------------------------------------------------------------- remap

func runRemap(args []string) {
	fs := flag.NewFlagSet("remap", flag.ExitOnError)
	ruleFile := fs.String("rulefile", "", "routing rule file")
	input := fs.String("input-trace", "", "input pcap or text trace")
	output := fs.String("output-trace", "", "output text trace")
	mappingOut := fs.String("mapping-out", "", "mapping CSV (.csv.gz); empty disables")
	method := fs.String("method", "r1-addr", "r1-addr or r2-block")
	maxPackets := fs.Uint64("max", 10000000, "valid TCP/UDP IPv4 packets to process")
	seed := fs.Int64("seed", 1, "random seed")
	fs.Parse(args)
	if *ruleFile == "" || *input == "" || *output == "" {
		fatalf("--rulefile, --input-trace and --output-trace are required")
	}

	rules, err := loadRules(*ruleFile)
	if err != nil {
		fatalf("load rules: %v", err)
	}

	counts := map[uint32]uint64{}
	_, err = scanTrace(*input, *maxPackets, 0, func(p tracePacket) error {
		key := p.dst
		if *method == "r2-block" {
			key = p.dst >> 8
		}
		counts[key]++
		return nil
	})
	if err != nil {
		fatalf("scan input: %v", err)
	}

	// Assign targets in descending popularity so that the mapping is
	// deterministic for a seed regardless of map iteration order.
	keys := make([]uint32, 0, len(counts))
	for key := range counts {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool {
		if counts[keys[i]] != counts[keys[j]] {
			return counts[keys[i]] > counts[keys[j]]
		}
		return keys[i] < keys[j]
	})

	rng := rand.New(rand.NewSource(*seed))
	mapping := make(map[uint32]uint32, len(keys))
	used := make(map[uint32]struct{}, len(keys))
	var pool []rulePrefix
	switch *method {
	case "r1-addr", "r2-block":
		// The default route is excluded: a remapped destination must hit a real route.
		for _, prefix := range rules.prefixes {
			if prefix.length > 0 && (*method == "r1-addr" || prefix.length <= 24) {
				pool = append(pool, prefix)
			}
		}
	default:
		fatalf("unknown method %q", *method)
	}
	for _, key := range keys {
		for attempt := 0; ; attempt++ {
			if attempt > 1000 {
				fatalf("could not find an unused target for %08x", key)
			}
			prefix := pool[rng.Intn(len(pool))]
			var target uint32
			if *method == "r1-addr" {
				target = prefix.network | (rng.Uint32() &^ prefixMask(prefix.length))
			} else {
				target = (prefix.network >> 8) | (rng.Uint32() &^ prefixMask(prefix.length) >> 8)
			}
			if _, ok := used[target]; ok {
				continue
			}
			used[target] = struct{}{}
			mapping[key] = target
			break
		}
	}

	if err := os.MkdirAll(filepath.Dir(*output), 0o755); err != nil {
		fatalf("mkdir: %v", err)
	}
	file, err := os.Create(*output)
	if err != nil {
		fatalf("create output: %v", err)
	}
	writer := bufio.NewWriterSize(file, 4*1024*1024)
	sequence := uint64(0)
	_, err = scanTrace(*input, *maxPackets, 0, func(p tracePacket) error {
		dst := mapping[p.dst]
		if *method == "r2-block" {
			dst = mapping[p.dst>>8]<<8 | (p.dst & 0xff)
		}
		row := strconv.AppendUint(nil, sequence, 10)
		row = append(row, ",64,"...)
		row = appendIPv4(row, p.src)
		row = append(row, ',')
		row = appendIPv4(row, dst)
		row = append(row, ',')
		row = append(row, p.proto...)
		row = append(row, ",0,0\n"...)
		sequence++
		_, err := writer.Write(row)
		return err
	})
	if err != nil {
		fatalf("write output: %v", err)
	}
	if err := writer.Flush(); err != nil {
		fatalf("flush: %v", err)
	}
	file.Close()

	if *mappingOut != "" {
		if err := writeMapping(*mappingOut, *method, keys, counts, mapping); err != nil {
			fatalf("write mapping: %v", err)
		}
	}
	fmt.Fprintf(os.Stderr, "method=%s seed=%d packets=%d keys=%d pool=%d\n",
		*method, *seed, sequence, len(keys), len(pool))
}

func writeMapping(path, method string, keys []uint32, counts map[uint32]uint64, mapping map[uint32]uint32) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	gz := gzip.NewWriter(file)
	w := csv.NewWriter(gz)
	if method == "r2-block" {
		w.Write([]string{"input_block24", "output_block24", "packets"})
	} else {
		w.Write([]string{"input_dst", "output_dst", "packets"})
	}
	for _, key := range keys {
		in, out := key, mapping[key]
		if method == "r2-block" {
			in, out = in<<8, out<<8
		}
		w.Write([]string{string(appendIPv4(nil, in)), string(appendIPv4(nil, out)), strconv.FormatUint(counts[key], 10)})
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return err
	}
	return gz.Close()
}

// ---------------------------------------------------------------- fidelity

type fidelityResult struct {
	label          string
	packets        uint64
	lpmHist        [33]uint64
	uniqueDst      int
	unique24       int
	uniquePrefixes int
	top100Share    float64
	top1000Share   float64
	reuseBuckets   []uint64 // cold, then <= each bound, then > last bound
	setStats       map[string]setStat
	medianReuse    float64
}

type setStat struct {
	maxOverMean float64
	cov         float64
	keysMean    float64
	keysMax     int
}

var reuseBounds = []int{64, 256, 1024, 2048, 4096, 8192, 16384, 32768}

func runFidelity(args []string) {
	fs := flag.NewFlagSet("fidelity", flag.ExitOnError)
	ruleFile := fs.String("rulefile", "", "routing rule file")
	traces := fs.String("traces", "", "comma-separated label=path list; the first is the reference")
	maxPackets := fs.Uint64("max", 10000000, "valid TCP/UDP IPv4 packets per trace")
	outputDir := fs.String("output-dir", "", "output directory")
	fs.Parse(args)
	if *ruleFile == "" || *traces == "" || *outputDir == "" {
		fatalf("--rulefile, --traces and --output-dir are required")
	}
	rules, err := loadRules(*ruleFile)
	if err != nil {
		fatalf("load rules: %v", err)
	}
	if err := os.MkdirAll(*outputDir, 0o755); err != nil {
		fatalf("mkdir: %v", err)
	}

	var results []fidelityResult
	for _, item := range strings.Split(*traces, ",") {
		label, path, ok := strings.Cut(item, "=")
		if !ok {
			fatalf("bad trace spec %q", item)
		}
		fmt.Fprintf(os.Stderr, "fidelity: %s\n", label)
		results = append(results, measure(label, path, rules, *maxPackets))
	}
	if err := writeFidelity(*outputDir, results); err != nil {
		fatalf("write: %v", err)
	}
}

func measure(label, path string, rules *ruleSet, maxPackets uint64) fidelityResult {
	res := fidelityResult{label: label, setStats: map[string]setStat{}}
	dsts := map[uint32]struct{}{}
	blocks := map[uint32]struct{}{}
	prefixCounts := map[uint64]uint64{}
	lastSeen := map[uint64]int{}
	n := int(maxPackets)
	fenwick := make([]int32, n+2)
	add := func(i int, v int32) {
		for i++; i < len(fenwick); i += i & -i {
			fenwick[i] += v
		}
	}
	sum := func(i int) int32 { // prefix sum of [0, i]
		var s int32
		for i++; i > 0; i -= i & -i {
			s += fenwick[i]
		}
		return s
	}
	res.reuseBuckets = make([]uint64, len(reuseBounds)+2)
	var reuseSamples []int32

	// Set index from the destination address, 256 sets (2048 entries, 8 way).
	setDefs := map[string]uint{"set24": 8, "set20": 12, "set18": 14}
	setPackets := map[string][]uint64{}
	setKeys := map[string][]map[uint32]struct{}{}
	for name := range setDefs {
		setPackets[name] = make([]uint64, 256)
		keys := make([]map[uint32]struct{}, 256)
		for i := range keys {
			keys[i] = map[uint32]struct{}{}
		}
		setKeys[name] = keys
	}

	t := 0
	_, err := scanTrace(path, maxPackets, 0, func(p tracePacket) error {
		match := rules.matchPrefix(p.dst)
		res.lpmHist[match.length]++
		dsts[p.dst] = struct{}{}
		blocks[p.dst>>8] = struct{}{}
		key := uint64(match.network)<<6 | uint64(match.length)
		prefixCounts[key]++
		if last, ok := lastSeen[key]; ok {
			distance := int(sum(t-1) - sum(last))
			reuseSamples = append(reuseSamples, int32(distance))
			bucket := len(reuseBounds) + 1
			for i, bound := range reuseBounds {
				if distance < bound {
					bucket = i + 1
					break
				}
			}
			res.reuseBuckets[bucket]++
			add(last, -1)
		} else {
			res.reuseBuckets[0]++
		}
		add(t, 1)
		lastSeen[key] = t
		for name, shift := range setDefs {
			index := (p.dst >> shift) & 0xff
			setPackets[name][index]++
			setKeys[name][index][p.dst>>shift] = struct{}{}
		}
		t++
		return nil
	})
	if err != nil {
		fatalf("scan %s: %v", path, err)
	}
	res.packets = uint64(t)
	res.uniqueDst = len(dsts)
	res.unique24 = len(blocks)
	res.uniquePrefixes = len(prefixCounts)

	counts := make([]uint64, 0, len(prefixCounts))
	for _, c := range prefixCounts {
		counts = append(counts, c)
	}
	sort.Slice(counts, func(i, j int) bool { return counts[i] > counts[j] })
	var top100, top1000 uint64
	for i, c := range counts {
		if i < 100 {
			top100 += c
		}
		if i < 1000 {
			top1000 += c
		}
	}
	res.top100Share = float64(top100) / float64(t)
	res.top1000Share = float64(top1000) / float64(t)
	if len(reuseSamples) > 0 {
		sort.Slice(reuseSamples, func(i, j int) bool { return reuseSamples[i] < reuseSamples[j] })
		res.medianReuse = float64(reuseSamples[len(reuseSamples)/2])
	}

	for name := range setDefs {
		var total, maxV float64
		for _, v := range setPackets[name] {
			total += float64(v)
			maxV = math.Max(maxV, float64(v))
		}
		mean := total / 256
		var variance float64
		for _, v := range setPackets[name] {
			variance += (float64(v) - mean) * (float64(v) - mean)
		}
		var keysTotal, keysMax int
		for _, keys := range setKeys[name] {
			keysTotal += len(keys)
			if len(keys) > keysMax {
				keysMax = len(keys)
			}
		}
		res.setStats[name] = setStat{
			maxOverMean: maxV / mean,
			cov:         math.Sqrt(variance/256) / mean,
			keysMean:    float64(keysTotal) / 256,
			keysMax:     keysMax,
		}
	}
	return res
}

func writeFidelity(dir string, results []fidelityResult) error {
	ref := results[0]
	summary, err := os.Create(filepath.Join(dir, "fidelity_summary.csv"))
	if err != nil {
		return err
	}
	defer summary.Close()
	w := csv.NewWriter(summary)
	header := []string{"trace", "packets", "lpm_tv_vs_ref", "lpm_default_pct", "lpm_mean_len",
		"unique_dst", "unique_24", "unique_lpm_prefix", "top100_share", "top1000_share",
		"reuse_median", "reuse_tv_vs_ref"}
	for _, bound := range reuseBounds {
		header = append(header, fmt.Sprintf("reuse_lt_%d", bound))
	}
	for _, name := range []string{"set24", "set20", "set18"} {
		header = append(header, name+"_max_over_mean", name+"_cov", name+"_keys_mean", name+"_keys_max")
	}
	w.Write(header)
	for _, r := range results {
		var mean float64
		for length, c := range r.lpmHist {
			mean += float64(length) * float64(c)
		}
		mean /= float64(r.packets)
		row := []string{r.label, strconv.FormatUint(r.packets, 10),
			ftoa(tv(r.lpmHist[:], ref.lpmHist[:])),
			ftoa(100 * float64(r.lpmHist[0]) / float64(r.packets)),
			ftoa(mean),
			strconv.Itoa(r.uniqueDst), strconv.Itoa(r.unique24), strconv.Itoa(r.uniquePrefixes),
			ftoa(r.top100Share), ftoa(r.top1000Share),
			ftoa(r.medianReuse), ftoa(tv(r.reuseBuckets, ref.reuseBuckets)),
		}
		var cumulative uint64
		for i := range reuseBounds {
			cumulative += r.reuseBuckets[i+1]
			row = append(row, ftoa(float64(cumulative)/float64(r.packets)))
		}
		for _, name := range []string{"set24", "set20", "set18"} {
			s := r.setStats[name]
			row = append(row, ftoa(s.maxOverMean), ftoa(s.cov), ftoa(s.keysMean), strconv.Itoa(s.keysMax))
		}
		w.Write(row)
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return err
	}

	lpm, err := os.Create(filepath.Join(dir, "lpm_distribution.csv"))
	if err != nil {
		return err
	}
	defer lpm.Close()
	lw := csv.NewWriter(lpm)
	header = []string{"prefix_length"}
	for _, r := range results {
		header = append(header, r.label)
	}
	lw.Write(header)
	for length := 0; length <= 32; length++ {
		row := []string{strconv.Itoa(length)}
		for _, r := range results {
			row = append(row, strconv.FormatUint(r.lpmHist[length], 10))
		}
		lw.Write(row)
	}
	lw.Flush()
	return lw.Error()
}

func tv(a, b []uint64) float64 {
	var sa, sb float64
	for i := range a {
		sa += float64(a[i])
		sb += float64(b[i])
	}
	var d float64
	for i := range a {
		d += math.Abs(float64(a[i])/sa - float64(b[i])/sb)
	}
	return d / 2
}

func ftoa(v float64) string { return strconv.FormatFloat(v, 'f', 6, 64) }
