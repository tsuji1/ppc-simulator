package main

// FIB-only selector construction. No packet destinations, observed hit counts,
// or per-packet leaf annotations are inputs to these functions. The binary trie
// preserves route boundaries even when next hops happen to be equal, matching
// the production IsLeaf definition rather than merging same-next-hop routes.
import (
	"bufio"
	"encoding/binary"
	"fmt"
	"math"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type fibNode struct{ child [2]int32 }
type fibShape struct{ nodes []fibNode }
type fibRegionTable struct {
	g       int
	method  string
	lengths []uint8 // software form: absolute length; packed form stores length-9
}

func newFIBShape() *fibShape { return &fibShape{nodes: make([]fibNode, 1)} }
func (f *fibShape) insert(dst uint32, length int) {
	n := int32(0)
	for depth := 0; depth < length; depth++ {
		bit := (dst >> (31 - depth)) & 1
		if f.nodes[n].child[bit] == 0 {
			f.nodes[n].child[bit] = int32(len(f.nodes))
			f.nodes = append(f.nodes, fibNode{})
		}
		n = f.nodes[n].child[bit]
	}
}
func readFIBShape(path string) (*fibShape, error) {
	in, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer in.Close()
	f := newFIBShape()
	s := bufio.NewScanner(in)
	line := 0
	for s.Scan() {
		line++
		parts := strings.Fields(s.Text())
		if len(parts) == 0 || strings.HasPrefix(parts[0], "#") {
			continue
		}
		if len(parts) < 3 {
			return nil, fmt.Errorf("invalid rule at line %d", line)
		}
		ip := net.ParseIP(parts[0]).To4()
		n, err := strconv.Atoi(parts[1])
		if ip == nil || err != nil || n < 0 || n > 32 {
			return nil, fmt.Errorf("invalid prefix at line %d", line)
		}
		f.insert(binary.BigEndian.Uint32(ip), n)
	}
	return f, s.Err()
}

// safeLength is also used to validate this structural enumeration against the
// production IsLeaf routine in tests. An absent child is a safe implicit region.
func (f *fibShape) safeLength(dst uint32) int {
	n := int32(0)
	for depth := 0; depth < 32; depth++ {
		if f.nodes[n].child == [2]int32{} {
			return depth
		}
		n = f.nodes[n].child[(dst>>(31-depth))&1]
		if n == 0 {
			return depth + 1
		}
	}
	return 32
}

func (f *fibShape) regionHist(g int) [][25]uint64 {
	hist := make([][25]uint64, 1<<g)
	var emit func(uint32, int)
	emit = func(prefix uint32, length int) {
		// Model the cache's /9 lower clamp explicitly. Broad safe regions
		// represent several stored /9 prefixes, never a variable-size entry.
		if length < 9 {
			emit(prefix, length+1)
			emit(prefix|(uint32(1)<<(31-length)), length+1)
			return
		}
		if length > 24 {
			return
		}
		first := int(prefix >> (32 - g))
		count := 1
		if length < g {
			count = 1 << (g - length)
		}
		for r := first; r < first+count; r++ {
			hist[r][length]++
		}
	}
	var walk func(int32, uint32, int)
	walk = func(n int32, prefix uint32, depth int) {
		if f.nodes[n].child == [2]int32{} {
			emit(prefix, depth)
			return
		}
		// Descendants beyond /24 cannot be inserted by exclusive VPLC.
		if depth == 24 {
			return
		}
		for bit, child := range f.nodes[n].child {
			p := prefix | (uint32(bit) << (31 - depth))
			if child == 0 {
				emit(p, depth+1)
			} else {
				walk(child, p, depth+1)
			}
		}
	}
	walk(0, 0, 0)
	return hist
}

func buildFIBRegionTable(hist [][25]uint64, g int, method string) *fibRegionTable {
	if len(hist) != 1<<g {
		panic("histogram size")
	}
	rt := &fibRegionTable{g: g, method: method, lengths: make([]uint8, len(hist))}
	for r, h := range hist {
		selected := 18 // fixed fallback for regions with no cacheable safe prefix
		if method == "mode" {
			var best uint64
			for n := 9; n <= 24; n++ {
				if h[n] > best {
					selected, best = n, h[n]
				}
			}
		} else {
			var weights [25]float64
			var total float64
			for n := 9; n <= 24; n++ {
				w := float64(h[n])
				switch method {
				case "count":
				case "sqrt":
					w *= math.Exp2(float64(32-max(n, g)) / 2)
				case "address":
					w *= math.Exp2(float64(32 - max(n, g)))
				default:
					panic("unknown FIB method")
				}
				weights[n], total = w, total+w
			}
			if total > 0 {
				var cumulative float64
				for n := 9; n <= 24; n++ {
					cumulative += weights[n]
					if cumulative >= total/2 {
						selected = n
						break
					}
				}
			}
		}
		rt.lengths[r] = uint8(selected)
	}
	return rt
}
func (rt *fibRegionTable) lookup(dst uint32) int { return int(rt.lengths[dst>>(32-rt.g)]) }
func (rt *fibRegionTable) name() string          { return fmt.Sprintf("fib-%s-g%d", rt.method, rt.g) }
func (rt *fibRegionTable) histString() string {
	var h [25]int
	for _, n := range rt.lengths {
		h[n]++
	}
	var parts []string
	for n := 9; n <= 24; n++ {
		if h[n] > 0 {
			parts = append(parts, fmt.Sprintf("%d:%d", n, h[n]))
		}
	}
	return strings.Join(parts, ";")
}
func (rt *fibRegionTable) writePacked(dir string) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	b := make([]byte, (len(rt.lengths)+1)/2)
	for i, n := range rt.lengths {
		b[i/2] |= (n - 9) << (4 * (i % 2))
	}
	return os.WriteFile(filepath.Join(dir, rt.name()+".packed"), b, 0600)
}
