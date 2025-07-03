package cache

import (
	"fmt"
	"test-module/ipaddress"
	"test-module/routingtable"
)

type MultiLayerCacheInclusive struct {
	CacheLayers          []Cache
	CachePolicies        []CachePolicy
	CacheReferedByLayer  []uint
	CacheReplacedByLayer []uint
	CacheHitByLayer      []uint
	CacheRefBits         []uint
	CacheInserted        []uint
	RoutingTable         routingtable.RoutingTablePatriciaTrie
	OnceCacheLimit       int
	Invalidate           []uint
	DepthSum             uint64
	LongestMatchMap      [33]int
	MatchMap             [33]int
	DoInclusive          int
	DebugMode            bool
}

func (c *MultiLayerCacheInclusive) StatString() string {
	str := "{"

	str += "\"Refered\": ["

	for i, x := range c.CacheReferedByLayer {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", x)
	}

	str += "], "
	str += "\"Replaced\": ["

	for i, x := range c.CacheReplacedByLayer {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", x)
	}

	str += "], "
	str += "\"Hit\": ["

	for i, x := range c.CacheHitByLayer {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", x)
	}

	str += "], "
	str += "\"MatchMap\": ["

	for i := 0; i <= 32; i++ {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", c.MatchMap[i])
	}

	str += "], "
	str += "\"LongestMatchMap\": ["

	for i := 0; i <= 32; i++ {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", c.LongestMatchMap[i])
	}

	str += "], "
	str += "\"DepthSum\": "

	str += fmt.Sprintf("%v", c.DepthSum)

	str += ", "
	str += "\"DoInclusive\": "

	str += fmt.Sprintf("%v", c.DoInclusive)

	str += "], "
	str += "\"Inserted\": ["

	for i, x := range c.CacheInserted {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", x)
	}

	str += "]}"

	return str
}

type MultiLayerCacheInclusiveStat struct {
	Refered         []uint
	Replaced        []uint
	Hit             []uint
	MatchMap        []uint
	LongestMatchMap []uint
	DepthSum        uint
	DOInclusive     uint
	Inserted        []uint
}

// Stat は、キャッシュの統計情報を構造体として返します。
func (c *MultiLayerCacheInclusive) Stat() interface{} {
	// MatchMap と LongestMatchMap を生成
	matchMap := make([]uint, 33)
	longestMatchMap := make([]uint, 33)
	for i := 0; i <= 32; i++ {
		matchMap[i] = uint(c.MatchMap[i])
		longestMatchMap[i] = uint(c.LongestMatchMap[i])
	}

	// 構造体を作成して返す
	return MultiLayerCacheInclusiveStat{
		Refered:         c.CacheReferedByLayer,
		Replaced:        c.CacheReplacedByLayer,
		Hit:             c.CacheHitByLayer,
		MatchMap:        matchMap,
		LongestMatchMap: longestMatchMap,
		DepthSum:        uint(c.DepthSum),
		Inserted:        c.CacheInserted,
		DOInclusive:     uint(c.DoInclusive),
	}
}
func (c *MultiLayerCacheInclusive) IsCached(p *Packet, update bool) (bool, *int) {
	return c.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

func (c *MultiLayerCacheInclusive) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hit := false
	var hitLayerIdx *int // not nil if hit

	for i, cache := range c.CacheLayers {
		if update {
			c.CacheReferedByLayer[i] += 1
		}

		if hitLayer, _ := cache.IsCachedWithFiveTuple(f, update); hitLayer {
			if update {
				c.CacheHitByLayer[i] += 1
			}
			hit = true
			hitLayerIdx = &i

			break
		}
	}

	// Update under layer
	// 何もしていないよね
	// if update && hit {
	// 	for offset_i, cache := range c.CacheLayers[*hitLayerIdx+1:] {
	// 		isCached, _ := cache.IsCachedWithFiveTuple(f, true)

	// 		if !isCached {
	// 			break
	// 		}

	// 		i := (*hitLayerIdx + 1) + offset_i
	// 		if i != (len(c.CacheLayers)-1) && c.CachePolicies[i] == WriteBackExclusive {
	// 			break
	// 		}
	// 	}
	// }

	// // if L1 (layerIdx == 0) cache miss at least
	// if update && hit {
	// 	if *hitLayerIdx > 1 {
	// 		// cache upper-most layer
	// 		if c.CachePolicies[*hitLayerIdx-1] == WriteBackExclusive {
	// 			// invalidate under layer
	// 			c.CacheLayers[*hitLayerIdx].InvalidateFiveTuple(f)
	// 		}

	// 		c.CacheFiveTuple(f)
	// 	}
	// }

	return hit, hitLayerIdx
}
func (c *MultiLayerCacheInclusive) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	// Cache対象のFiveTupleリストを作成し、最初の要素は引数で受け取ったFiveTuple
	evictedFiveTuples := []*FiveTuple{}
	fivetupleDstIP := ipaddress.NewIPaddress(f.DstIP)

	// ルーティングテーブルで目的地IPアドレスに一致するプレフィックスを検索
	prefix, _ := c.RoutingTable.SearchIP(fivetupleDstIP, 32)
	prefix_size := len(prefix) - 1

	for _, p := range prefix {
		c.MatchMap[len(p)] += 1
	}

	c.LongestMatchMap[len(prefix[prefix_size])] += 1

	c.DepthSum += uint64(c.RoutingTable.GetDepth(f.DstIP))

	for k := len(c.CacheLayers) - 1; k > -1; k-- {
		cache := c.CacheLayers[k]
		if isLeaf(f, &c.RoutingTable, int(c.CacheRefBits[k])) {
			// 葉ノードならばキャッシュする
			evictedFiveTuples = cache.CacheFiveTuple(f)

			// 追い出されたエントリが下位キャッシュにキャッシュされている場合は無効化
			lowerCaches := c.CacheLayers[k+1:]
			for indexOfLowerCache, lowerCache := range lowerCaches {
				for _, f := range evictedFiveTuples {
					hitted, _ := lowerCache.IsCachedWithFiveTuple(f, false)
					if hitted {
						lowerCache.InvalidateFiveTuple(f)
						// 下位キャッシュのインデックスは k+1+indexOfLowerCache
						c.Invalidate[k+1+indexOfLowerCache] += 1
					}
				}
			}

			break
		} else {
			targetRefbit := c.CacheRefBits[k]
			upperCacheRefbits := c.CacheRefBits[:k]
			if len(upperCacheRefbits) == 0 {
				continue
			}

			dstIP := ipaddress.NewIPaddress(f.DstIP)
			temp_limit, matchingPrefix := c.RoutingTable.CountMatchingSubtreeRules(dstIP, targetRefbit, upperCacheRefbits, c.OnceCacheLimit)
			// cachePrefix := dstIP.MaskedBitString(len(matchingPrefix))

			if int(temp_limit) > c.OnceCacheLimit {
				continue
			}

			evictedFiveTuples = cache.CacheFiveTuple(f)

			lowerCaches := c.CacheLayers[k+1:]
			for _, f := range evictedFiveTuples {
				for indexOfLowerCache, lowerCache := range lowerCaches {
					hitted, _ := lowerCache.IsCachedWithFiveTuple(f, false)
					if hitted {
						lowerCache.InvalidateFiveTuple(f)
						c.Invalidate[k+1+indexOfLowerCache] += 1
					}
				}
			}

			fiveTuplesForUpperCaches := c.RoutingTable.GroupChildPrefixesByRefBits(matchingPrefix, targetRefbit, upperCacheRefbits)
			c.DoInclusive += 1
			tmpList := make([][]string, len(fiveTuplesForUpperCaches))

			for i, prefixs := range fiveTuplesForUpperCaches {
				tmpList[i] = make([]string, len(prefixs))
				for j, prefix := range prefixs {
					tmpList[i][j] = ipaddress.NewIPaddress(prefix).String()
				}
			}

			for i, prefixs := range fiveTuplesForUpperCaches {
				tempEvictedFiveTuples := []*FiveTuple{}
				cacheIdx := i
				if cacheIdx >= len(c.CacheLayers) {
					panic("cacheIdx > len(c.CacheLayers) is not expected")
				}
				for _, prefix := range prefixs {
					ff := *f
					ff.DstIP = ipaddress.NewIPaddress(prefix).Uint32()
					tempEvictedFiveTuples = append(tempEvictedFiveTuples, c.CacheLayers[cacheIdx].CacheFiveTuple(&ff)...)
				}

				lowerCaches := c.CacheLayers[cacheIdx+1:]
				for _, evictedTuple := range tempEvictedFiveTuples {
					for indexOfLowerCache, lowerCache := range lowerCaches {
						hitted, _ := lowerCache.IsCachedWithFiveTuple(evictedTuple, false)
						if hitted {
							lowerCache.InvalidateFiveTuple(evictedTuple)
							c.Invalidate[cacheIdx+indexOfLowerCache] += 1
						}
					}
				}

				// // 追い出されたエントリが下位キャッシュにキャッシュされている場合は無効化
				// for indexOfLowerCache, lowerCache := range lowerCaches {
				// 	for _, evictedTuple := range tempEvictedFiveTuples {
				// 		hitted, _ := lowerCache.IsCachedWithFiveTuple(evictedTuple, false)
				// 		if hitted {
				// 			lowerCache.InvalidateFiveTuple(evictedTuple)
				// 			c.Invalidate[cacheIdx+1+indexOfLowerCache] += 1
				// 		}
				// 	}
				// }

				evictedFiveTuples = append(evictedFiveTuples, tempEvictedFiveTuples...)
			}
			break
		}
	}

	return evictedFiveTuples
}

func (c *MultiLayerCacheInclusive) InvalidateFiveTuple(f *FiveTuple) {
	panic("not implemented")
}

func (c *MultiLayerCacheInclusive) Clear() {
	for _, cache := range c.CacheLayers {
		cache.Clear()
	}
}

func (c *MultiLayerCacheInclusive) Description() string {
	str := "MultiLayerCacheInclusive"
	return str
}

func (c *MultiLayerCacheInclusive) ParameterString() string {
	// [{Size: 2, CachePolicy: Hoge}, {}]
	str := "{"

	str += "\"Type\": \"MultiLayerCacheInclusive\", "
	str += "\"CacheLayers\": ["

	for i, cacheLayer := range c.CacheLayers {
		if i != 0 {
			str += ", "
		}

		str += cacheLayer.ParameterString()
	}

	str += "], "
	str += "\"CachePolicies\": ["

	for i, cachePolicy := range c.CachePolicies {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("\"%s\"", cachePolicy.String())
	}
	
	

	str += "]}"
	return str
}

// DescriptionParameter は、キャッシュ層の説明を文字列形式で返します。
func (c *MultiLayerCacheInclusive) DescriptionParameter() string {
	str := "MultiLayerCacheInclusive["
	for i, cacheLayer := range c.CacheLayers {
		if i != 0 {
			str += ", "
		}
		str += cacheLayer.Description()
	}
	str += "]"
	return str
}

// Parameter は、MultiLayerCacheExclusive のパラメータを返します。
func (c *MultiLayerCacheInclusive) Parameter() Parameter {
	// CacheLayers の Parameter を取得し、スライスに格納
	var cacheLayers []Parameter
	for _, cacheLayer := range c.CacheLayers {
		// 各 CacheLayer の Parameter() メソッドを呼び出す
		cacheLayers = append(cacheLayers, cacheLayer.Parameter())
	}

	// MultiCacheParameter 構造体を返す
	return &InclusiveCacheParameter{
		Type:           c.DescriptionParameter(), // パラメータのタイプ
		CacheLayers:    cacheLayers,              // キャッシュレイヤーのパラメータ
		CachePolicies:  c.CachePolicies,          // キャッシュポリシー
		OnceCacheLimit: c.OnceCacheLimit,         // 一度のキャッシュ制限
	}
}
