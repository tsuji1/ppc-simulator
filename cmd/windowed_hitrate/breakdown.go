package main

// ミスの内訳と set の偏りの解析（-breakdown-json、#124）。
//
// VPLC（UnifiedCache）の entry（長さと network）を key にして、同じ packet 列で次を数える。
//   - 挿入されない packet（exclusive で leaf にならない）: どの cache でも必ずミスする
//   - 初回参照: その key を初めて見た packet
//   - 同じ entry 数の fully associative LRU のミス（初回参照と挿入されない packet を含む）
// cache 側のミスからこれを引いたものが、set への割り当てによるミス（衝突と、同じ entry が複数の set に入る重複）になる。
//
// 各 PS の構成（index の付け方）については、-breakdown-window packet ごとに、使われた key を set に割り当てて数え、
// 次の値を window で平均する。
//   - dup: 使われた (set, key) の数 / key の数。短いプレフィクスが複数の set に入ると 1 を超える
//   - dispersion: set ごとの entry 数の分散 / 平均。一様な hash（Poisson）なら 1、偏るほど大きい
//   - overflow: way を超えて入りきらない entry の割合（Σ max(0, n − way) / Σ n）
//   - max_over_mean: 最も多い set の entry 数 / 平均

import (
	"container/list"
	"encoding/json"
	"fmt"
	"os"

	"test-module/cache"
)

// faLRU は key の fully associative LRU。
type faLRU struct {
	capacity int
	order    *list.List
	items    map[uint64]*list.Element
}

func newFALRU(capacity int) *faLRU {
	return &faLRU{capacity: capacity, order: list.New(), items: make(map[uint64]*list.Element, capacity)}
}

// access は hit なら true。ミスなら key を入れ、あふれたら最も古い key を追い出す。
func (c *faLRU) access(key uint64) bool {
	if e, ok := c.items[key]; ok {
		c.order.MoveToFront(e)
		return true
	}
	c.items[key] = c.order.PushFront(key)
	if c.order.Len() > c.capacity {
		old := c.order.Back()
		c.order.Remove(old)
		delete(c.items, old.Value.(uint64))
	}
	return false
}

func entryKey(length int8, network uint32) uint64 {
	return uint64(uint8(length))<<32 | uint64(network)
}

type setLoadObserver struct {
	configID       string
	cacheIndexType int
	unified        *cache.UnifiedCache
	sets           int
	way            int
	pairs          map[uint64]struct{} // window の中の (set, key)
	windows        uint64
	sumDup         float64
	sumDispersion  float64
	sumOverflow    float64
	sumMaxOverMean float64
}

type breakdownState struct {
	path      string
	window    uint64
	capacity  int
	way       int
	keySource *cache.UnifiedCache
	fa        *faLRU
	seen      map[uint64]struct{}
	winKeys   map[uint64]struct{}
	winPkts   uint64
	packets   uint64
	rejected  uint64
	firstRefs uint64
	faMisses  uint64
	observers []*setLoadObserver
}

// newBreakdown は warm の PS の構成から解析の状態を作る。PS の構成が無いときはエラー。
func newBreakdown(opts options, runs []runState) (*breakdownState, error) {
	b := &breakdownState{
		path: opts.breakdownJSON, window: opts.breakdownWindow, capacity: opts.psCapacity, way: opts.way,
		fa: newFALRU(opts.psCapacity), seen: make(map[uint64]struct{}), winKeys: make(map[uint64]struct{}),
	}
	for i := range runs {
		uc, ok := runs[i].sim.Cache.(*cache.UnifiedCache)
		if !ok {
			continue
		}
		if b.keySource == nil {
			b.keySource = uc
		}
		indexType, err := parseIntList(runs[i].config.cacheIndexType)
		if err != nil || len(indexType) != 1 {
			return nil, fmt.Errorf("cache index type of %s: %q", runs[i].config.id, runs[i].config.cacheIndexType)
		}
		b.observers = append(b.observers, &setLoadObserver{
			configID: runs[i].config.id, cacheIndexType: indexType[0], unified: uc,
			sets: uc.SetCount(), way: runs[i].config.way, pairs: make(map[uint64]struct{}),
		})
	}
	if b.keySource == nil {
		return nil, fmt.Errorf("-breakdown-json には PS（UnifiedCache）の構成が要る")
	}
	return b, nil
}

func (b *breakdownState) observe(packet *cache.MinPacket) {
	b.packets++
	f := packet.FiveTuple()
	length, network, ok := b.keySource.EntryKey(f)
	if !ok {
		b.rejected++
		b.faMisses++
	} else {
		key := entryKey(length, network)
		if _, seen := b.seen[key]; !seen {
			b.seen[key] = struct{}{}
			b.firstRefs++
		}
		if !b.fa.access(key) {
			b.faMisses++
		}
		b.winKeys[key] = struct{}{}
		for _, o := range b.observers {
			set := o.unified.PlacementSet(f, length)
			o.pairs[uint64(set)<<37|key] = struct{}{}
		}
	}
	b.winPkts++
	if b.winPkts == b.window {
		b.closeWindow()
	}
}

func (b *breakdownState) closeWindow() {
	if len(b.winKeys) > 0 {
		for _, o := range b.observers {
			o.close(len(b.winKeys))
		}
	}
	b.winKeys = make(map[uint64]struct{})
	b.winPkts = 0
}

func (o *setLoadObserver) close(keys int) {
	counts := make([]int, o.sets)
	for pair := range o.pairs {
		counts[pair>>37]++
	}
	n := float64(len(o.pairs))
	mean := n / float64(o.sets)
	var sq, over float64
	most := 0
	for _, c := range counts {
		d := float64(c) - mean
		sq += d * d
		if c > o.way {
			over += float64(c - o.way)
		}
		if c > most {
			most = c
		}
	}
	o.windows++
	o.sumDup += n / float64(keys)
	o.sumDispersion += (sq / float64(o.sets)) / mean
	o.sumOverflow += over / n
	o.sumMaxOverMean += float64(most) / mean
	o.pairs = make(map[uint64]struct{})
}

type breakdownObserverJSON struct {
	ConfigID       string  `json:"config_id"`
	CacheIndexType int     `json:"cache_index_type"`
	Sets           int     `json:"sets"`
	Windows        uint64  `json:"windows"`
	Dup            float64 `json:"dup"`
	Dispersion     float64 `json:"dispersion"`
	Overflow       float64 `json:"overflow"`
	MaxOverMean    float64 `json:"max_over_mean"`
}

type breakdownJSON struct {
	Trace           string                  `json:"trace_path"`
	Rule            string                  `json:"rule_path"`
	Capacity        int                     `json:"capacity"`
	Way             int                     `json:"way"`
	Window          uint64                  `json:"window"`
	Packets         uint64                  `json:"packets"`
	Rejected        uint64                  `json:"rejected"`
	FirstReferences uint64                  `json:"first_references"`
	DistinctKeys    int                     `json:"distinct_keys"`
	FAMisses        uint64                  `json:"fa_lru_misses"`
	Observers       []breakdownObserverJSON `json:"observers"`
}

// write は最後の途中の window を捨てて（packet 数が window に満たないため）JSON を書く。
func (b *breakdownState) write(opts options) error {
	out := breakdownJSON{
		Trace: opts.trace, Rule: opts.ruleFile, Capacity: b.capacity, Way: b.way, Window: b.window,
		Packets: b.packets, Rejected: b.rejected, FirstReferences: b.firstRefs, DistinctKeys: len(b.seen),
		FAMisses: b.faMisses,
	}
	for _, o := range b.observers {
		w := float64(o.windows)
		if o.windows == 0 {
			w = 1
		}
		out.Observers = append(out.Observers, breakdownObserverJSON{
			ConfigID: o.configID, CacheIndexType: o.cacheIndexType, Sets: o.sets, Windows: o.windows,
			Dup: o.sumDup / w, Dispersion: o.sumDispersion / w, Overflow: o.sumOverflow / w, MaxOverMean: o.sumMaxOverMean / w,
		})
	}
	data, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(b.path, data, 0o644)
}
