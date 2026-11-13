// Isolated exploratory replay. No production cache or default is changed.
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/csv"
	"flag"
	"fmt"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"test-module/cache"
)

type packet struct {
	dst  uint32
	leaf int8
}
type config struct {
	name, kind string
	lengths    []int
}
type replay struct {
	cfg                            config
	sets, way                      int
	tags                           []uint64 // MRU first within each set. key = prefix<<8 | length.
	reads, writes, hits, trainHits uint64
	staged                         bool
	query                          []int
	trainBucketHits                [33]uint64
	lastBucket                     int
	trainReads                     uint64
}

// Freeze the probe order using only hits in the selection prefix. The cache
// placement remains fixed; changing lookup order does not move any entries.
func (r *replay) freezeOrder() {
	r.query = append([]int(nil), r.cfg.lengths...)
	sort.Slice(r.query, func(i, j int) bool {
		a, b := r.query[i], r.query[j]
		if r.trainBucketHits[a] != r.trainBucketHits[b] {
			return r.trainBucketHits[a] > r.trainBucketHits[b]
		}
		return a < b
	})
}

func newReplay(c config, capacity, way int) *replay {
	if capacity < way || capacity%way != 0 || (capacity/way)&(capacity/way-1) != 0 {
		panic("invalid capacity/way")
	}
	return &replay{cfg: c, sets: capacity / way, way: way, tags: make([]uint64, capacity)}
}
func key(dst uint32, length int) uint64 { return uint64(dst>>(32-length))<<8 | uint64(length) }
func index(dst uint32, length, sets int, direct bool) int {
	p := dst >> (32 - length)
	if direct {
		return int(p) & (sets - 1)
	}
	var b [4]byte
	binary.BigEndian.PutUint32(b[:], p)
	return int(crc32.ChecksumIEEE(b[:])) & (sets - 1)
}
func insertLength(leaf int8) int {
	if leaf < 0 || leaf > 24 {
		return -1
	}
	return max(9, int(leaf))
}
func floorLength(length int, candidates []int) int {
	selected := candidates[0]
	for _, l := range candidates {
		if l <= length {
			selected = l
		}
	}
	return selected
}
func (r *replay) access(p packet) bool {
	// All implementable policies enumerate candidate sets using dst only.
	// The leaf length is used below ONLY on a miss to select placement.
	lengths := r.cfg.lengths
	if r.staged && len(r.query) > 0 {
		lengths = r.query
	}
	r.lastBucket = 0
	var ideal [1]int
	if r.cfg.kind == "ideal" {
		ideal[0] = 16
		if p.leaf > 16 && p.leaf < 25 {
			ideal[0] = int(p.leaf)
		}
		if p.leaf > 24 {
			ideal[0] = 24
		}
		lengths = ideal[:]
	}
	var indices [16]int
	n := 0
	bestSet, bestPos, bestLen := -1, -1, 0
	for _, l := range lengths {
		s := index(p.dst, l, r.sets, r.cfg.kind == "direct")
		duplicate := false
		for j := 0; j < n; j++ {
			if indices[j] == s {
				duplicate = true
				break
			}
		}
		if duplicate {
			continue
		}
		indices[n] = s
		n++
		for pos := 0; pos < r.way; pos++ {
			k := r.tags[s*r.way+pos]
			if k == 0 {
				break
			}
			length := int(k & 255)
			if length > bestLen && k>>8 == uint64(p.dst>>(32-length)) {
				bestSet, bestPos, bestLen = s, pos, length
			}
		}
		// Cached exclusive leaf regions cannot overlap with a different leaf
		// region, so the first matching set is sufficient for a correct answer.
		if r.staged && bestSet >= 0 {
			break
		}
	}
	r.reads += uint64(n)
	if bestSet >= 0 {
		if r.cfg.kind == "floor" {
			r.lastBucket = floorLength(bestLen, r.cfg.lengths)
		}
		base := bestSet * r.way
		k := r.tags[base+bestPos]
		copy(r.tags[base+1:base+bestPos+1], r.tags[base:base+bestPos])
		r.tags[base] = k
		return true
	}
	length := insertLength(p.leaf)
	if length < 0 {
		return false
	}
	placement := lengths[0]
	if r.cfg.kind == "floor" {
		placement = floorLength(length, r.cfg.lengths)
	}
	s := index(p.dst, placement, r.sets, r.cfg.kind == "direct")
	base := s * r.way
	copy(r.tags[base+1:base+r.way], r.tags[base:base+r.way-1])
	r.tags[base] = key(p.dst, length)
	r.writes++
	return false
}
func configurations() []config {
	var configs []config
	for l := 8; l <= 24; l++ {
		configs = append(configs, config{fmt.Sprintf("direct-%d", l), "direct", []int{l}})
	}
	configs = append(configs, config{"ideal", "ideal", nil})
	for _, lengths := range [][]int{{9, 24}, {9, 14, 24}, {9, 16, 24}, {9, 18, 24}, {9, 20, 24}, {9, 12, 16, 24}, {9, 14, 18, 24}, {9, 16, 20, 24}, {9, 16, 22, 24}, {9, 12, 16, 20, 24}, {9, 12, 14, 16, 18, 20, 22, 24}, {9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24}} {
		parts := make([]string, len(lengths))
		for i, l := range lengths {
			parts[i] = strconv.Itoa(l)
		}
		configs = append(configs, config{"floor-" + strings.Join(parts, "-"), "floor", lengths})
	}
	return configs
}
func load(opts options, dstleaf string, export string) ([]packet, error) {
	packets := make([]packet, 0, opts.maxPackets)
	if dstleaf != "" {
		f, err := os.Open(dstleaf)
		if err != nil {
			return nil, err
		}
		defer f.Close()
		reader := bufio.NewReaderSize(f, 1<<20)
		var b [5]byte
		for opts.maxPackets == 0 || uint64(len(packets)) < opts.maxPackets {
			_, err := io.ReadFull(reader, b[:])
			if err == io.EOF {
				break
			}
			if err != nil {
				return nil, err
			}
			packets = append(packets, packet{binary.LittleEndian.Uint32(b[:4]), int8(b[4])})
		}
		return packets, nil
	}
	table, err := loadRoutingTable(opts.ruleFile)
	if err != nil {
		return nil, err
	}
	_, err = processTrace(opts, table, func(p *cache.MinPacket) error { packets = append(packets, packet{p.DstIP, p.IsLeafIndex}); return nil })
	if err != nil {
		return nil, err
	}
	if export != "" {
		f, err := os.Create(export)
		if err != nil {
			return nil, err
		}
		w := bufio.NewWriterSize(f, 1<<20)
		var b [5]byte
		for _, p := range packets {
			binary.LittleEndian.PutUint32(b[:4], p.dst)
			b[4] = byte(p.leaf)
			if _, err = w.Write(b[:]); err != nil {
				f.Close()
				return nil, err
			}
		}
		if err = w.Flush(); err != nil {
			f.Close()
			return nil, err
		}
		if err = f.Close(); err != nil {
			return nil, err
		}
	}
	return packets, nil
}
func main() {
	var opts options
	flag.StringVar(&opts.trace, "trace", "", "pcap or text trace")
	flag.StringVar(&opts.ruleFile, "rulefile", "", "FIB")
	flag.Uint64Var(&opts.maxPackets, "max", 10000000, "valid TCP/UDP packets")
	dstleaf := flag.String("dstleaf", "", "reuse a recorded dstleaf input")
	export := flag.String("export", "", "private intermediate dstleaf output (do not publish)")
	label := flag.String("label", "", "public trace label")
	capacities := flag.String("capacities", "1024,8192,65536", "entry counts")
	out := flag.String("out", "", "CSV output")
	train := flag.Int("train", 1000000, "selection prefix; also report disjoint suffix")
	jobs := flag.Int("jobs", 4, "concurrent configuration replays")
	floorOnly := flag.Bool("floor-only", false, "replay only floor configurations")
	staged := flag.Bool("staged", false, "early exit at first exclusive leaf hit; train probe order on prefix")
	flag.Parse()
	if *out == "" || *jobs < 1 || *train < 0 || (*dstleaf == "" && (opts.trace == "" || opts.ruleFile == "")) {
		panic("invalid arguments")
	}
	packets, err := load(opts, *dstleaf, *export)
	if err != nil {
		panic(err)
	}
	if len(packets) <= *train {
		panic("trace must extend beyond training prefix")
	}
	type task struct {
		r        *replay
		capacity int
	}
	var tasks []task
	for _, raw := range strings.Split(*capacities, ",") {
		capacity, err := strconv.Atoi(raw)
		if err != nil {
			panic(err)
		}
		for _, c := range configurations() {
			if *floorOnly && c.kind != "floor" {
				continue
			}
			r := newReplay(c, capacity, 8)
			r.staged = *staged
			if *staged && c.kind != "floor" {
				panic("staged requires floor-only")
			}
			tasks = append(tasks, task{r, capacity})
		}
	}
	queue := make(chan task)
	var wg sync.WaitGroup
	for j := 0; j < *jobs; j++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for task := range queue {
				for i, p := range packets {
					if i == *train {
						task.r.trainReads = task.r.reads
						if task.r.staged {
							task.r.freezeOrder()
						}
					}
					if task.r.access(p) {
						task.r.hits++
						if i < *train {
							task.r.trainHits++
							task.r.trainBucketHits[task.r.lastBucket]++
						}
					}
				}
			}
		}()
	}
	for _, task := range tasks {
		queue <- task
	}
	close(queue)
	wg.Wait()
	if err := os.MkdirAll(filepath.Dir(*out), 0755); err != nil {
		panic(err)
	}
	f, err := os.Create(*out)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	w := csv.NewWriter(f)
	w.Write([]string{"trace", "config", "kind", "capacity", "way", "candidates", "packets", "train_packets", "hits", "train_hits", "suffix_hits", "reads", "writes", "train_reads", "staged", "probe_order"})
	for _, task := range tasks {
		r := task.r
		w.Write([]string{*label, r.cfg.name, r.cfg.kind, strconv.Itoa(task.capacity), "8", strconv.Itoa(max(1, len(r.cfg.lengths))), strconv.Itoa(len(packets)), strconv.Itoa(*train), fmt.Sprint(r.hits), fmt.Sprint(r.trainHits), fmt.Sprint(r.hits - r.trainHits), fmt.Sprint(r.reads), fmt.Sprint(r.writes), fmt.Sprint(r.trainReads), fmt.Sprint(r.staged), fmt.Sprint(r.query)})
	}
	w.Flush()
	if err := w.Error(); err != nil {
		panic(err)
	}
	fmt.Printf("%s packets=%d configurations=%d output=%s\n", *label, len(packets), len(tasks), *out)
}
