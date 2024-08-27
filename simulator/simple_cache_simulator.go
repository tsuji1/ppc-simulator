package simulator

import (
	"fmt"
	"os"
	"test-module/cache"

	"github.com/koron/go-dproxy"

	"test-module/routingtable"
)

// SimpleCacheSimulator は、キャッシュシミュレータの実装です。
// このシミュレータは、キャッシュのヒット率や統計情報を収集します。
type SimpleCacheSimulator struct {
	cache.Cache
	Stat CacheSimulatorStat
}

// Process は、パケットを処理し、キャッシュのヒット率を更新します。
// パケットがキャッシュにヒットしたかどうかを返します。
func (sim *SimpleCacheSimulator) Process(p *cache.Packet) bool {
	// キャッシュを検索
	cached := cache.AccessCache(sim.Cache, p)

	if cached {
		// キャッシュヒットの場合
		sim.Stat.Hit += 1
	} else {
		// キャッシュミスの場合、新しいエントリをキャッシュに追加
		// start := time.Now()
		sim.Cache.CacheFiveTuple(p.FiveTuple()) //平均20nsでキャッシュに追加される。
		// elapsed := time.Since(start)
		// if sim.Stat.Processed%1000000 == 0 {
		// 	fmt.Printf("process %d\n", sim.Stat.Processed)
		// 	fmt.Printf("cache five tuple execution time: %s\n", elapsed)
		// }
	}

	sim.Stat.Processed += 1

	return cached
}

// GetStat は、シミュレータの統計情報を返します。
func (sim *SimpleCacheSimulator) GetStat() CacheSimulatorStat {
	return sim.Stat
}

// GetStatString は、シミュレータの統計情報を文字列形式で返します。
func (sim *SimpleCacheSimulator) GetStatString() string {
	stat := sim.Stat.String()

	// 末尾の '}' を削除
	stat = stat[0 : len(stat)-1]

	statDetail := sim.Cache.StatString()

	if statDetail == "" {
		stat += ", \"StatDetail\": null}"
	} else {
		stat += ", \"StatDetail\": " + statDetail + "}"
	}

	return stat
}

// NewCacheSimulatorStat は、新しいキャッシュシミュレータ統計情報を作成します。
func NewCacheSimulatorStat(description, parameter string) CacheSimulatorStat {
	return CacheSimulatorStat{
		Type:      description,
		Parameter: parameter,
		Processed: 0,
		Hit:       0,
	}
}

// buildCache は、キャッシュ設定に基づいて適切なキャッシュを構築します。
func buildCache(p dproxy.Proxy, routingTable *routingtable.RoutingTablePatriciaTrie, debugMode bool) (cache.Cache, error) {
	// キャッシュタイプを取得
	cache_type, err := p.M("Type").String()

	if err != nil {
		return nil, err
	}

	var c cache.Cache

	// キャッシュタイプに応じてキャッシュを生成
	switch cache_type {
	case "CacheWithLookAhead":
		innerCache, err := buildCache(p.M("InnerCache"), routingTable, debugMode)
		if err != nil {
			return c, err
		}

		c = &cache.CacheWithLookAhead{
			InnerCache: innerCache,
		}
	case "FullAssociativeLRUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewFullAssociativeLRUCache(uint(size))
	case "FullAssociativeTreePLRUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewFullAssociativeTreePLRUCache(uint(size))
	case "FullAssociativeLFUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewFullAssociativeLFUCache(uint(size))
	case "FullAssociativeRandomCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewFullAssociativeRandomCache(uint(size))
	case "FullAssociativeFIFOCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewFullAssociativeFIFOCache(uint(size))
	case "NWaySetAssociativeLRUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		way, err := p.M("Way").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewNWaySetAssociativeLRUCache(uint(size), uint(way))
	case "NWaySetAssociativeTreePLRUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		way, err := p.M("Way").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewNWaySetAssociativeTreePLRUCache(uint(size), uint(way))
	case "NWaySetAssociativeLFUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		way, err := p.M("Way").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewNWaySetAssociativeLFUCache(uint(size), uint(way))
	case "NWaySetAssociativeRandomCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		way, err := p.M("Way").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewNWaySetAssociativeRandomCache(uint(size), uint(way))
	case "NWaySetAssociativeFIFOCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		way, err := p.M("Way").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewNWaySetAssociativeFIFOCache(uint(size), uint(way))
	case "MultiLayerCache":
		// MultiLayerCache の設定を取得
		cacheLayersPS := p.M("CacheLayers").ProxySet()
		cachePoliciesPS := p.M("CachePolicies").ProxySet()
		cacheLayersLen := cacheLayersPS.Len()
		cachePoliciesLen := cachePoliciesPS.Len()

		// CachePoliciesの数はCacheLayersの数-1でなければならない
		// CachePoliciesはCacheLayersの間のポリシーを表す
		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			cacheLayer, err := buildCache(cacheLayersPS.A(i), routingTable, debugMode)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
		}

		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr, err := cachePoliciesPS.A(i).String()
			if err != nil {
				return c, err
			}

			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		c = &cache.MultiLayerCache{
			CacheLayers:          cacheLayers,
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
		}
	case "FullAssociativeDstipNbitLRUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		refbits, err := p.M("Refbits").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewFullAssociativeDstipNbitLRUCache(uint(refbits), uint(size), routingTable, debugMode)
	case "NWaySetAssociativeDstipNbitLRUCache":
		size, err := p.M("Size").Int64()
		if err != nil {
			return c, err
		}

		way, err := p.M("Way").Int64()
		if err != nil {
			return c, err
		}

		refbits, err := p.M("Refbits").Int64()
		if err != nil {
			return c, err
		}

		c = cache.NewNWaySetAssociativeDstipNbitLRUCache(uint(refbits), uint(size), uint(way), routingTable, debugMode)
	case "MultiLayerCacheExclusive":
		// MultiLayerCacheExclusive の設定を取得
		cacheLayersPS := p.M("CacheLayers").ProxySet()
		cachePoliciesPS := p.M("CachePolicies").ProxySet()
		cacheLayersLen := cacheLayersPS.Len()
		cachePoliciesLen := cachePoliciesPS.Len()

		cacheRefbits := make([]uint, cacheLayersLen)

		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		// CacheLayersの設定を取得して、キャッシュを構築
		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			cacheLayer, err := buildCache(cacheLayersPS.A(i), routingTable, debugMode)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
			refbit, _ := cacheLayersPS.A(i).M("Refbits").Int64()
			cacheRefbits[i] = uint(refbit)
		}

		//ポリシーを構築して
		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr, err := cachePoliciesPS.A(i).String()
			if err != nil {
				return c, err
			}

			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		c = &cache.MultiLayerCacheExclusive{
			CacheLayers:          cacheLayers,
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
			CacheInserted:        make([]uint, cacheLayersLen),
			CacheRefBits:         cacheRefbits,
			RoutingTable:         *routingTable,
		}
	case "MultiLayerCacheInclusive":
		// MultiLayerCacheInclusive の設定を取得
		cacheLayersPS := p.M("CacheLayers").ProxySet()
		cachePoliciesPS := p.M("CachePolicies").ProxySet()
		cacheLayersLen := cacheLayersPS.Len()
		cachePoliciesLen := cachePoliciesPS.Len()

		cacheRefbits := make([]uint, cacheLayersLen)

		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			cacheLayer, err := buildCache(cacheLayersPS.A(i), routingTable, debugMode)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
			refbit, _ := cacheLayersPS.A(i).M("Refbits").Int64()
			cacheRefbits[i] = uint(refbit)
		}

		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr, err := cachePoliciesPS.A(i).String()
			if err != nil {
				return c, err
			}

			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		onceCacheLimit, e := p.M("OnceCacheLimit").Int64()
		if e != nil {
			panic("OnceCacheLimit is not set")
		}
		c = &cache.MultiLayerCacheInclusive{
			CacheLayers:          cacheLayers,
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
			CacheNotInserted:     make([]uint, cacheLayersLen),
			Special:              make([]uint, cacheLayersLen),
			CacheRefBits:         cacheRefbits,
			RoutingTable:         *routingTable,
			OnceCacheLimit:       int(onceCacheLimit),
		}
	default:
		return nil, fmt.Errorf("unsupported cache type: %s", cache_type)
	}

	return c, nil
}

// BuildSimpleCacheSimulator は、JSON 設定に基づいてシンプルなキャッシュシミュレータを構築します。
func BuildSimpleCacheSimulator(json interface{}) (*SimpleCacheSimulator, error) {
	p := dproxy.New(json)

	// シミュレータタイプを取得
	simType, err := p.M("Type").String()

	if err != nil {
		return nil, err
	}

	if simType != "SimpleCacheSimulator" {
		return nil, fmt.Errorf("unsupported simulator type: %s", simType)
	}

	// ルールファイルを開く
	rulefile, _ := p.M("Rule").String()
	fp, err := os.Open(rulefile)
	if err != nil {
		panic(err)
	}
	defer fp.Close()

	routingtable := routingtable.NewRoutingTablePatriciaTrie()
	routingtable.ReadRule(fp)

	cacheProxy := p.M("Cache")
	debugMode, err := p.M("DebugMode").Bool()
	if err != nil {
		debugMode = false
	}
	

	// キャッシュを構築
	cache, err := buildCache(cacheProxy, routingtable, debugMode)

	if err != nil {
		return nil, err
	}

	sim := &SimpleCacheSimulator{
		Cache: cache,
		Stat: NewCacheSimulatorStat(
			cache.Description(),
			cache.ParameterString(),
		),
	}

	return sim, nil
}
