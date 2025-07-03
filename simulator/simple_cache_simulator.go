package simulator

import (
	"fmt"
	"os"
	"test-module/cache"
	"test-module/memorytrace"
	"test-module/routingtable"
)

// SimpleCacheSimulator は、キャッシュシミュレータの実装です。
// このシミュレータは、キャッシュのヒット率や統計情報を収集します。
type SimpleCacheSimulator struct {
	cache.Cache
	Stat          CacheSimulatorStat
	SimDefinition SimulatorDefinition
	Tracer        *memorytrace.Tracer
}

// CacheInitInfo はキャッシュ構築時の追加情報を保持します。
// 上位キャッシュやデバッグモードなどの情報が含まれます。
type CacheInitInfo struct {
	RoutingTable *routingtable.RoutingTablePatriciaTrie
	DebugMode    bool
	ParentCache  cache.Cache // 必要に応じて上位キャッシュなども追加可能
	CacheIndex   int         // ParentCache内で自分が何番目か（親がいる場合のみ有効）
}

func NewAddtionalInfoBuildCache(routingTable *routingtable.RoutingTablePatriciaTrie, debugMode bool, parentCache cache.Cache) CacheInitInfo {
	return CacheInitInfo{
		RoutingTable: routingTable,
		DebugMode:    debugMode,
		ParentCache:  parentCache,
	}
}

// Process は、パケットを処理し、キャッシュのヒット率を更新します。
// パケットがキャッシュにヒットしたかどうかを返します。
func (sim *SimpleCacheSimulator) Process(p interface{}) bool {
	if sim.Tracer != nil {
		sim.Tracer.IncrementCycleCounter()
	} else {
		memorytrace.IncrementCycleCounter()
	}
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
func buildCache(definitionCache Cache, additionalInfo CacheInitInfo) (cache.Cache, error) {
	// キャッシュタイプを取得
	cache_type := definitionCache.Type

	var c cache.Cache

	// CacheInitInfo から必要な情報を取得
	routingTable := additionalInfo.RoutingTable
	debugMode := additionalInfo.DebugMode

	// キャッシュタイプに応じてキャッシュを生成
	switch cache_type {
	case "CacheWithLookAhead":
		innerCache, err := buildCache(*definitionCache.InnerCache, additionalInfo)
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
	case "NbitFullAssociativeDstipLRUCache":
		size := definitionCache.Size
		refbits := definitionCache.Refbits

		c = cache.NewFullAssociativeDstipNbitLRUCache(uint(refbits), uint(size), routingTable, debugMode)
	case "NbitNWaySetAssociativeDstipLRUCache":
		size := definitionCache.Size
		way := definitionCache.Way
		refbits := definitionCache.Refbits
		parentCache := additionalInfo.ParentCache
		indexInParentCache := additionalInfo.CacheIndex

		c = cache.NewNWaySetAssociativeDstipNbitLRUCache(uint(refbits), uint(size), uint(way), routingTable, debugMode, parentCache, indexInParentCache)
	case "MultiLayerCacheExclusive":
		cacheLayersPS := definitionCache.CacheLayers
		cachePoliciesPS := definitionCache.CachePolicies
		cacheLayersLen := len(cacheLayersPS)
		cachePoliciesLen := len(cachePoliciesPS)
		cacheRefbits := make([]uint, cacheLayersLen)

		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr := cachePoliciesPS[i]
			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		c = &cache.MultiLayerCacheExclusive{
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
			CacheInserted:        make([]uint, cacheLayersLen),
			CacheRefBits:         cacheRefbits,
			RoutingTable:         *routingTable,
		}

		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			additionalInfo.CacheIndex = i
			additionalInfo.ParentCache = c
			cacheLayer, err := buildCache(cacheLayersPS[i], additionalInfo)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
			refbit := cacheLayersPS[i].Refbits
			cacheRefbits[i] = uint(refbit)
		}

		c.(*cache.MultiLayerCacheExclusive).CacheLayers = cacheLayers

	case "MultiLayerCacheInclusive":
		cacheLayersPS := definitionCache.CacheLayers
		cachePoliciesPS := definitionCache.CachePolicies
		cacheLayersLen := len(cacheLayersPS)
		cachePoliciesLen := len(cachePoliciesPS)

		cacheRefbits := make([]uint, cacheLayersLen)

		if cachePoliciesLen != (cacheLayersLen - 1) {
			return c, fmt.Errorf("`CachePolicies` (%d items) must have `CacheLayers` length - 1 (%d) items", cachePoliciesLen, cacheLayersLen-1)
		}

		// 先に MultiLayerCacheInclusive インスタンスを作成
		cachePolicies := make([]cache.CachePolicy, cachePoliciesLen)
		for i := 0; i < cachePoliciesLen; i++ {
			cachePolicyStr := cachePoliciesPS[i]
			cachePolicies[i] = cache.StringToCachePolicy(cachePolicyStr)
		}

		c = &cache.MultiLayerCacheInclusive{
			CachePolicies:        cachePolicies,
			CacheReferedByLayer:  make([]uint, cacheLayersLen),
			CacheReplacedByLayer: make([]uint, cacheLayersLen),
			CacheHitByLayer:      make([]uint, cacheLayersLen),
			CacheInserted:        make([]uint, cacheLayersLen),
			OnceCacheLimit:       definitionCache.OnceCacheLimit,
			Invalidate:           make([]uint, cacheLayersLen),
			CacheRefBits:         cacheRefbits,
			RoutingTable:         *routingTable,
		}

		// 次に各レイヤーのキャッシュを作成
		cacheLayers := make([]cache.Cache, cacheLayersLen)
		for i := 0; i < cacheLayersLen; i++ {
			additionalInfo.CacheIndex = i
			additionalInfo.ParentCache = c
			cacheLayer, err := buildCache(cacheLayersPS[i], additionalInfo)
			if err != nil {
				return c, err
			}
			cacheLayers[i] = cacheLayer
			refbit := cacheLayersPS[i].Refbits
			cacheRefbits[i] = uint(refbit)
		}

		// 作成したキャッシュレイヤーを設定
		c.(*cache.MultiLayerCacheInclusive).CacheLayers = cacheLayers
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

	// ルーティングテーブルを初期化
	r := routingtable.NewRoutingTablePatriciaTrie()

	if rulefile != "" {
		fp, err := os.Open(rulefile)
		if err != nil {
			panic(err)
		}
		defer fp.Close()
		r.ReadRule(fp)
	}

	// CacheInitInfo を生成
	additionalInfo := CacheInitInfo{
		RoutingTable: r,
		DebugMode:    simulatorDefinition.DebugMode,
		ParentCache:  nil, // 上位キャッシュがない場合は nil
		CacheIndex:   -1,  // 上位キャッシュがない場合は -1
	}

	// キャッシュを構築
	cache, err := buildCache(simulatorDefinition.Cache, additionalInfo)
	if err != nil {
		return nil, err
	}

	// シミュレータを初期化
	sim := &SimpleCacheSimulator{
		Cache: cache,
		Stat: NewCacheSimulatorStat(
			cache.Description(),
			cache.Parameter(),
		),
		SimDefinition: simulatorDefinition,
		Tracer:        memorytrace.NewTracer(),
	}

	return sim, nil
}
