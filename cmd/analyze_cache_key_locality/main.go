// analyze_cache_key_locality は、trace を MP と LTPC の cache entry の単位（key）に直し、
// key ごとの種類数・run 長・再利用距離（LRU の stack distance）を出す。
// MP と LTPC の hit rate の差がどの性質から来るかを、trace の間で比べるために使う（#117）。
//
// key の定義（windowed_hitrate の MP /24+/18 と LTPC ideal に合わせる）:
//   - leaf 長 L: 宛先を含む /L block の中に、より長い prefix がない最小の L（windowed_hitrate の leafIndex）
//   - LTPC: (L, 宛先の上位 L bit)
//   - MP: L ≤ 18 なら /18 層の (宛先の上位 18 bit)、L ≤ 24 なら /24 層の (上位 24 bit)、L > 24 は cache しない
//
// hit rate の近似は、key ごとの全連想 LRU（LTPC は 4096 entry、MP は層ごとに 2048 entry）で、
// 再利用距離が容量未満なら hit とする。
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

	"test-module/ipaddress"
	"test-module/routingtable"
)

type packetReader interface {
	ZeroCopyReadPacketData() ([]byte, gopacket.CaptureInfo, error)
	LinkType() layers.LinkType
}

// stream は 1 種類の key の列について、種類数・run 長・再利用距離を数える。
type stream struct {
	name      string
	capacity  int
	last      map[uint64]int // key → 最後に参照した位置（stream 内の通し番号）
	marks     fenwick        // 各 key の最後の参照位置に 1 を立てる
	n         int
	prevKey   uint64
	runs      uint64
	runLen    uint64
	maxRun    uint64
	distances []int32 // 再利用距離（初回参照は -1）
}

func newStream(name string, capacity int, maxPackets int) *stream {
	return &stream{name: name, capacity: capacity, last: map[uint64]int{}, marks: newFenwick(maxPackets)}
}

func (s *stream) add(key uint64) {
	if s.n == 0 || key != s.prevKey {
		s.runs++
		s.runLen = 1
	} else {
		s.runLen++
	}
	if s.runLen > s.maxRun {
		s.maxRun = s.runLen
	}
	s.prevKey = key

	d := int32(-1)
	if p, ok := s.last[key]; ok {
		// p と今の間に参照された異なる key の数
		d = int32(s.marks.sum(s.n-1) - s.marks.sum(p))
		s.marks.add(p, -1)
	}
	s.distances = append(s.distances, d)
	s.marks.add(s.n, 1)
	s.last[key] = s.n
	s.n++
}

func (s *stream) hits() uint64 {
	var h uint64
	for _, d := range s.distances {
		if d >= 0 && int(d) < s.capacity {
			h++
		}
	}
	return h
}

// percentile は再利用距離の分位点。初回参照は無限大として扱い、-1 を返す。
func (s *stream) percentile(q float64) int32 {
	if len(s.distances) == 0 {
		return 0
	}
	sorted := make([]int32, len(s.distances))
	copy(sorted, s.distances)
	sort.Slice(sorted, func(i, j int) bool {
		a, b := sorted[i], sorted[j]
		if a < 0 {
			return false
		}
		if b < 0 {
			return true
		}
		return a < b
	})
	return sorted[int(q*float64(len(sorted)-1))]
}

type fenwick []int32

func newFenwick(n int) fenwick { return make(fenwick, n+1) }

func (f fenwick) add(i int, v int32) {
	for i++; i < len(f); i += i & -i {
		f[i] += v
	}
}

// sum は位置 0..i の和（i < 0 なら 0）。
func (f fenwick) sum(i int) int32 {
	var s int32
	for i++; i > 0; i -= i & -i {
		s += f[i]
	}
	return s
}

func main() {
	ruleFile := flag.String("rulefile", "", "routing rule file")
	trace := flag.String("trace", "", "pcap、pcapng、または simulator の text trace")
	label := flag.String("label", "", "出力に書く条件名")
	maxPackets := flag.Int("max", 10_000_000, "読む TCP/UDP パケット数の上限")
	ltpcCapacity := flag.Int("ltpc-capacity", 4096, "LTPC の entry 数")
	mpCapacity := flag.Int("mp-layer-capacity", 2048, "MP の 1 層あたりの entry 数")
	output := flag.String("output", "", "出力 CSV（metric,value）")
	flag.Parse()
	if *ruleFile == "" || *trace == "" || *output == "" {
		fmt.Fprintln(os.Stderr, "-rulefile、-trace、-output は必須")
		os.Exit(2)
	}

	rt, err := loadRoutingTable(*ruleFile)
	if err != nil {
		fatalf("rule file: %v", err)
	}

	dst := newStream("dst", 0, *maxPackets)
	lpm := newStream("lpm", 0, *maxPackets)
	ltpc := newStream("ltpc", *ltpcCapacity, *maxPackets)
	mp18 := newStream("mp18", *mpCapacity, *maxPackets)
	mp24 := newStream("mp24", *mpCapacity, *maxPackets)
	mpAll := newStream("mp", 0, *maxPackets) // 層を区別しない MP key の列（run 長用）

	var packets, matchedSum, leafSum, uncacheable uint64
	var leafBuckets [4]uint64 // ≤16、17-18、19-24、>24
	ltpcToMP := map[uint64]map[uint64]struct{}{}
	ltpcPackets := map[uint64]uint64{}

	handle := func(d uint32) {
		ip := ipaddress.NewIPaddress(d)
		matched, _ := rt.SearchLongestIP(ip, 32)
		leaf := leafIndex(ip, rt)
		packets++
		matchedSum += uint64(len(matched))
		leafSum += uint64(leaf)

		dst.add(uint64(d))
		lpm.add(uint64(len(matched))<<32 | uint64(maskTop(d, len(matched))))
		ltpcKey := uint64(leaf)<<32 | uint64(maskTop(d, leaf))
		ltpc.add(ltpcKey)

		var mpKey uint64
		switch {
		case leaf <= 18:
			leafBuckets[boolIndex(leaf <= 16, 0, 1)]++
			mpKey = 18<<32 | uint64(maskTop(d, 18))
			mp18.add(mpKey)
		case leaf <= 24:
			leafBuckets[2]++
			mpKey = 24<<32 | uint64(maskTop(d, 24))
			mp24.add(mpKey)
		default:
			leafBuckets[3]++
			uncacheable++
			mpKey = 32<<32 | uint64(d)
		}
		mpAll.add(mpKey)
		set, ok := ltpcToMP[ltpcKey]
		if !ok {
			set = map[uint64]struct{}{}
			ltpcToMP[ltpcKey] = set
		}
		set[mpKey] = struct{}{}
		ltpcPackets[ltpcKey]++
	}

	if err := readTrace(*trace, *maxPackets, handle); err != nil {
		fatalf("trace: %v", err)
	}
	if packets == 0 {
		fatalf("TCP/UDP パケットがない")
	}

	// 1 つの LTPC entry が覆う MP entry の数（パケット数で重み付けした平均も出す）
	var mpKeysSum, mpKeysWeighted uint64
	for key, set := range ltpcToMP {
		mpKeysSum += uint64(len(set))
		mpKeysWeighted += uint64(len(set)) * ltpcPackets[key]
	}

	p := float64(packets)
	rows := [][2]string{
		{"label", *label},
		{"trace", *trace},
		{"rule", *ruleFile},
		{"packets", u(packets)},
		{"distinct_dst", u(uint64(len(dst.last)))},
		{"dst_run_avg", f(p / float64(dst.runs))},
		{"dst_run_max", u(dst.maxRun)},
		{"matched_len_avg", f(float64(matchedSum) / p)},
		{"leaf_len_avg", f(float64(leafSum) / p)},
		{"leaf_le16_share", f(float64(leafBuckets[0]) / p)},
		{"leaf_17_18_share", f(float64(leafBuckets[1]) / p)},
		{"leaf_19_24_share", f(float64(leafBuckets[2]) / p)},
		{"leaf_gt24_share", f(float64(leafBuckets[3]) / p)},
		{"distinct_lpm_prefixes", u(uint64(len(lpm.last)))},
		{"distinct_ltpc_keys", u(uint64(len(ltpc.last)))},
		{"distinct_mp18_keys", u(uint64(len(mp18.last)))},
		{"distinct_mp24_keys", u(uint64(len(mp24.last)))},
		{"mp_keys_per_ltpc_key", f(float64(mpKeysSum) / float64(len(ltpcToMP)))},
		{"mp_keys_per_ltpc_key_pkt_weighted", f(float64(mpKeysWeighted) / p)},
		{"ltpc_run_avg", f(p / float64(ltpc.runs))},
		{"mp_run_avg", f(p / float64(mpAll.runs))},
		{"ltpc_lru_hit", f(float64(ltpc.hits()) / p)},
		{"mp_lru_hit", f(float64(mp18.hits()+mp24.hits()) / p)},
		{"mp_uncacheable_share", f(float64(uncacheable) / p)},
		{"ltpc_cold_miss", f(float64(len(ltpc.last)) / p)},
		{"mp_cold_miss", f(float64(len(mp18.last)+len(mp24.last)) / p)},
	}
	for _, s := range []*stream{dst, ltpc, mp18, mp24} {
		for _, q := range []float64{0.5, 0.9, 0.99} {
			rows = append(rows, [2]string{fmt.Sprintf("%s_reuse_p%d", s.name, int(q*100)), strconv.Itoa(int(s.percentile(q)))})
		}
	}
	if err := writeCSV(*output, rows); err != nil {
		fatalf("output: %v", err)
	}
}

func maskTop(d uint32, length int) uint32 {
	if length <= 0 {
		return 0
	}
	if length >= 32 {
		return d
	}
	return d &^ (^uint32(0) >> length)
}

func boolIndex(cond bool, a, b int) int {
	if cond {
		return a
	}
	return b
}

// leafIndex は windowed_hitrate と同じ定義。
func leafIndex(ip ipaddress.IPaddress, rt *routingtable.RoutingTablePatriciaTrie) int {
	for i := 0; i < 33; i++ {
		if rt.IsLeaf(ip, i) {
			return i
		}
	}
	return 0
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

// readTrace は TCP/UDP パケットの宛先を順に handle に渡す。
func readTrace(path string, maxPackets int, handle func(uint32)) error {
	n := 0
	if isTextTrace(path) {
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		defer file.Close()
		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for scanner.Scan() && n < maxPackets {
			line := strings.TrimSpace(scanner.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			d, ok := textDst(line)
			if !ok {
				continue
			}
			handle(d)
			n++
		}
		return scanner.Err()
	}

	reader, closer, err := openCapture(path)
	if err != nil {
		return err
	}
	defer closer.Close()
	linkType := reader.LinkType()
	for n < maxPackets {
		data, _, err := reader.ZeroCopyReadPacketData()
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}
		packet := gopacket.NewPacket(data, linkType, gopacket.DecodeOptions{NoCopy: true})
		ipLayer, ok := packet.Layer(layers.LayerTypeIPv4).(*layers.IPv4)
		if !ok || len(ipLayer.DstIP.To4()) != 4 {
			continue
		}
		if ipLayer.Protocol != layers.IPProtocolTCP && ipLayer.Protocol != layers.IPProtocolUDP {
			continue
		}
		handle(binary.BigEndian.Uint32(ipLayer.DstIP.To4()))
		n++
	}
	return nil
}

// textDst は simulator の text trace（7 列または 8 列）の 1 行から、TCP/UDP の宛先を取り出す。
func textDst(line string) (uint32, bool) {
	var record []string
	if strings.Contains(line, ",") {
		r := csv.NewReader(strings.NewReader(line))
		r.FieldsPerRecord = -1
		var err error
		if record, err = r.Read(); err != nil {
			return 0, false
		}
	} else {
		record = strings.Fields(line)
	}
	var dstStr, proto string
	switch len(record) {
	case 8:
		dstStr, proto = record[3], record[5]
	case 7:
		dstStr, proto = record[3], record[4]
	default:
		return 0, false
	}
	switch strings.ToLower(strings.TrimSpace(proto)) {
	case "tcp", "6", "udp", "17":
	default:
		return 0, false
	}
	ip := net.ParseIP(dstStr).To4()
	if ip == nil {
		return 0, false
	}
	return binary.BigEndian.Uint32(ip), true
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

func writeCSV(path string, rows [][2]string) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()
	w := csv.NewWriter(file)
	w.Write([]string{"metric", "value"})
	for _, r := range rows {
		w.Write([]string{r[0], r[1]})
	}
	w.Flush()
	return w.Error()
}

func u(v uint64) string  { return strconv.FormatUint(v, 10) }
func f(v float64) string { return strconv.FormatFloat(v, 'f', 6, 64) }

func fatalf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
