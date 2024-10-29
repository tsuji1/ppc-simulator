package simulator

import (
	"fmt"
	"os"
	"test-module/cache"

	"test-module/routingtable"
)

// SimpleCacheSimulator は、キャッシュシミュレータの実装です。
// このシミュレータは、キャッシュのヒット率や統計情報を収集します。
type SimpleCacheSimulator struct {
	cache.Cache
	Stat          CacheSimulatorStat
	SimDefinition SimulatorDefinition
}

// Process は、パケットを処理し、キャッシュのヒット率を更新します。
// パケットがキャッシュにヒットしたかどうかを返します。
func (sim *SimpleCacheSimulator) Process(p interface{}) bool {
	switch pkt := p.(type) {
	case *cache.Packet:
		// キャッシュを検索
		cached := cache.AccessCache(sim.Cache, pkt)

		if cached {
			// キャッシュヒットの場合
			sim.Stat.Hit += 1
			fmt.Printf("sim stat hit: %d\n", sim.Stat.Hit)
		} else {
			sim.Cache.CacheFiveTuple(pkt.FiveTuple()) //平均20nsでキャッシュに追加される。

		}

		sim.Stat.Processed += 1

		return cached

	case *cache.MinPacket:
		pac := pkt.Packet()
		// キャッシュを検索
		cached := cache.AccessCache(sim.Cache, pac)

		if cached {
			// キャッシュヒットの場合
			sim.Stat.Hit += 1
		} else {
			sim.Cache.CacheFiveTuple(pkt.FiveTuple()) //平均20nsでキャッシュに追加される。
		}

		sim.Stat.Processed += 1

		return cached

	default:
		// サポートされていない型の場合
		fmt.Println("Unsupported packet type")
		return false
	}

}

// GetStat は、シミュレータの統計情報を返します。
func (sim *SimpleCacheSimulator) GetStat() CacheSimulatorStat {
	return sim.Stat
}

func (sim *SimpleCacheSimulator) GetSimulatorResult() SimulatorResult {
	return SimulatorResult{
		Type:       sim.Stat.Type,
		Parameter:  sim.Stat.Parameter,
		Processed:  sim.Stat.Processed,
		Hit:        sim.Stat.Hit,
		HitRate:    float64(sim.Stat.Hit) / float64(sim.Stat.Processed),
		StatDetail: sim.Cache.Stat(),
	}
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
func NewCacheSimulatorStat(description string, parameter cache.Parameter) CacheSimulatorStat {
	return CacheSimulatorStat{
		Type:      description,
		Parameter: parameter,
		Processed: 0,
		Hit:       0,
	}
}

// buildCache は、キャッシュ設定に基づいて適切なキャッシュを構築します。
func buildCache(definitionCache Cache, routingTable *routingtable.RoutingTablePatriciaTrie, debugMode bool) (cache.Cache, error) {
	// キャッシュタイプを取得
	cache_type := definitionCache.Type

	var c cache.Cache

	// キャッシュタイプに応じてキャッシュを生成
	switch cache_type {
	case "CacheWithLookAhead":
		innerCache, err := buildCache(*definitionCache.InnerCache, routingTable, debugMode)
		if err != nil {
			return c, err
		}

		c = &cache.CacheWithLookAhead{
			InnerCache: innerCache,
		}
	case "FullAssociativeLRUCache":
		size := definitionCache.Size

		c = cache.NewFullAssociativeLRUCache(uint(size))
	case "FullAssociativeTreePLRUCache":
		size := definitionCache.Size
		c = cache.NewFullAssociativeTreePLRUCache(uint(size))
	case "FullAssociativeLFUCache":
		size := definitionCache.Size

		c = cache.NewFullAssociativeLFUCache(uint(size))
	case "FullAssociativeRandomCache":
		size := definitionCache.Size

		c = cache.NewFullAssociativeRandomCache(uint(size))
	case "FullAssociativeFIFOCache":
		size := definitionCache.Size

		c = cache.NewFullAssociativeFIFOCache(uint(size))
	case "NWaySetAssociativeLRUCache":
		size := definitionCache.Size

		way := definitionCache.Way
		c = cache.NewNWaySetAssociativeLRUCache(uint(size), uint(way))
	case "NWaySetAssociativeTreePLRUCache":
		size := definitionCache.Size

		way := definitionCache.Way
		c = cache.NewNWaySetAssociativeTreePLRUCache(uint(size), uint(way))
	case "NWaySetAssociativeLFUCache":
		size := definitionCache.Size

		way := definitionCache.Way
		c = cache.NewNWaySetAssociativeLFUCache(uint(size), uint(way))
	case "NWaySetAssociativeRandomCache":
		size := definitionCache.Size

		way := definitionCache.Way
		c = cache.NewNWaySetAssociativeRandomCache(uint(size), uint(way))
	case "NWaySetAssociativeFIFOCache":
		size := definitionCache.Size

		way := definitionCache.Way
		c = cache.NewNWaySetAssociativeFIFOCache(uint(size), uint(way))
	case "MultiLayerCache":
		// MultiLayerCache の設定を取得
		cacheLayersPS := definitionCache.CacheLayers
		cachePoliciesPS := definitionCache.CachePolicies
		cacheLayersLen := len(cacheLayersPS)
		cachePoliciesLen := len(cachePoliciesPS)

		// CachePoliciesの数はCacheLayersの数-1でなければならない
		// CachePoliciesはCacheLayersの間のポリシーを表す
		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			cacheLayer, err := buildCache(cacheLayersPS[i], routingTable, debugMode)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
		}

		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr := cachePoliciesPS[i]

			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		c = &cache.MultiLayerCache{
			CacheLayers:          cacheLayers,
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
		}
	case "NbitFullAssociativeDstipLRUCache":
		size := definitionCache.Size

		refbits := definitionCache.Refbits
		c = cache.NewFullAssociativeDstipNbitLRUCache(uint(refbits), uint(size), routingTable, debugMode)
	case "NbitNWaySetAssociativeDstipLRUCache":
		size := definitionCache.Size

		way := definitionCache.Way
		refbits := definitionCache.Refbits
		c = cache.NewNWaySetAssociativeDstipNbitLRUCache(uint(refbits), uint(size), uint(way), routingTable, debugMode)
	case "MultiLayerCacheExclusive":
		// MultiLayerCacheExclusive の設定を取得
		cacheLayersPS := definitionCache.CacheLayers
		cachePoliciesPS := definitionCache.CachePolicies
		cacheLayersLen := len(cacheLayersPS)
		cachePoliciesLen := len(cachePoliciesPS)

		cacheRefbits := make([]uint, cacheLayersLen)

		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		// CacheLayersの設定を取得して、キャッシュを構築
		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			cacheLayer, err := buildCache(cacheLayersPS[i], routingTable, debugMode)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
			refbit := cacheLayersPS[i].Refbits
			cacheRefbits[i] = uint(refbit)
		}

		//ポリシーを構築して
		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr := cachePoliciesPS[i]
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
	case "DebugCache":
		// MultiLayerCacheExclusive の設定を取得
		fmt.Printf("make debug cache\n")
		cacheLayersPS := definitionCache.CacheLayers
		cachePoliciesPS := definitionCache.CachePolicies
		cacheLayersLen := len(cacheLayersPS)
		cachePoliciesLen := len(cachePoliciesPS)

		cacheRefbits := make([]uint, cacheLayersLen)

		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		// CacheLayersの設定を取得して、キャッシュを構築
		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			cacheLayer, err := buildCache(cacheLayersPS[i], routingTable, debugMode)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
			refbit := cacheLayersPS[i].Refbits
			cacheRefbits[i] = uint(refbit)
		}

		//ポリシーを構築して
		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr := cachePoliciesPS[i]
			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		c = &cache.DebugCache{
			CacheLayers:          cacheLayers,
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
			CacheInserted:        make([]uint, cacheLayersLen),
			CacheRefBits:         cacheRefbits,
			RoutingTable:         *routingTable,
		}
	// case "MultiLayerCacheInclusive":
	// 	// MultiLayerCacheInclusive の設定を取得
	// 	cacheLayersPS := p.M("CacheLayers").ProxySet()
	// 	cachePoliciesPS := p.M("CachePolicies").ProxySet()
	// 	cacheLayersLen := cacheLayersPS.Len()
	// 	cachePoliciesLen := cachePoliciesPS.Len()

	// 	cacheRefbits := make([]uint, cacheLayersLen)

	// 	if cachePoliciesLen != (cacheLayersLen - 1) {
	// 		return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
	// 	}

	// 	cacheLayers := make([]cache.Cache, cacheLayersLen)
	// 	for i := 0; i < cacheLayersLen; i++ {
	// 		cacheLayer, err := buildCache(cacheLayersPS.A(i), routingTable, debugMode)
	// 		if err != nil {
	// 			return c, err
	// 		}
	// 		cacheLayers[i] = cacheLayer
	// 		refbit, _ := cacheLayersPS.A(i).M("Refbits").Int64()
	// 		cacheRefbits[i] = uint(refbit)
	// 	}

	// 	cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
	// 	for i := 0; i < cachePoliciesLen; i++ {
	// 		cachePolicyStr, err := cachePoliciesPS.A(i).String()
	// 		if err != nil {
	// 			return c, err
	// 		}

	// 		cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
	// 	}

	// 	onceCacheLimit, e := p.M("OnceCacheLimit").Int64()
	// 	if e != nil {
	// 		panic("OnceCacheLimit is not set")
	// 	}
	// 	c = &cache.MultiLayerCacheInclusive{
	// 		CacheLayers:          cacheLayers,
	// 		CachePolicies:        cachePolicies,
	// 		CacheReferedByLayer:  make([]uint, cacheLayersLen),
	// 		CacheReplacedByLayer: make([]uint, cacheLayersLen),
	// 		CacheHitByLayer:      make([]uint, cacheLayersLen),
	// 		CacheNotInserted:     make([]uint, cacheLayersLen),
	// 		Special:              make([]uint, cacheLayersLen),
	// 		CacheRefBits:         cacheRefbits,
	// 		RoutingTable:         *routingTable,
	// 		OnceCacheLimit:       int(onceCacheLimit),
	// 	}
	default:
		return nil, fmt.Errorf("unsupported cache type: %s", cache_type)
	}

	return c, nil
}

// BuildSimpleCacheSimulator は、JSON 設定に基づいてシンプルなキャッシュシミュレータを構築します。
func BuildSimpleCacheSimulator(simulatorDefinition SimulatorDefinition, rulefile string) (*SimpleCacheSimulator, error) {

	// シミュレータタイプを取得
	simType := simulatorDefinition.Type

	if simType != "SimpleCacheSimulator" {
		return nil, fmt.Errorf("unsupported simulator type: %s", simType)
	}

	r := routingtable.NewRoutingTablePatriciaTrie()

	if rulefile != "" {
		fp, err := os.Open(rulefile)
		if err != nil {
			panic(err)
		}
		defer fp.Close()
		r.ReadRule(fp)
	}
	// キャッシュを構築
	cache, err := buildCache(simulatorDefinition.Cache, r, simulatorDefinition.DebugMode)

	if err != nil {
		return nil, err
	}

	sim := &SimpleCacheSimulator{
		Cache: cache,
		Stat: NewCacheSimulatorStat(
			cache.Description(),
			cache.Parameter(),
		),
		SimDefinition: simulatorDefinition,
	}

	return sim, nil
}
