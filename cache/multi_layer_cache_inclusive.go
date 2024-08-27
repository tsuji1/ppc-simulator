package cache

import (
	"fmt"
	"test-module/routingtable"
	"test-module/ipaddress"
)

type MultiLayerCacheInclusive struct {
	CacheLayers          []Cache
	CachePolicies        []CachePolicy
	CacheReferedByLayer  []uint
	CacheReplacedByLayer []uint
	CacheHitByLayer      []uint

	CacheRefBits         []uint
	CacheNotInserted     []uint
	RoutingTable         routingtable.RoutingTablePatriciaTrie
	OnceCacheLimit       int
	Special              []uint
	DepthSum             uint64
	LongestMatchMap      [33]int
	MatchMap             [33]int
	DoInclusive          int
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

	for i:=0; i<=32; i++ {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v",c.MatchMap[i])
	}

	str += "], "
	str += "\"LongestMatchMap\": ["

	for i:=0; i<=32; i++ {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v",c.LongestMatchMap[i])
	}

	str += "], "
	str += "\"DepthSum\": "
	
	str += fmt.Sprintf("%v", c.DepthSum)

	str += ", "
	str += "\"DoInclusive\": "

		str += fmt.Sprintf("%v", c.DoInclusive)

	str += ", "
	str += "\"Special\": ["

	for i, x := range c.Special {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", x)
	}

	str += "], "
	str += "\"NotInserted\": ["

	for i, x := range c.CacheNotInserted {
		if i != 0 {
			str += ", "
		}

		str += fmt.Sprintf("%v", x)
	}

	str += "]}"

	return str
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
	if update && hit {
		for offset_i, cache := range c.CacheLayers[*hitLayerIdx+1:] {
			isCached, _ := cache.IsCachedWithFiveTuple(f, true)

			if !isCached {
				break
			}

			i := (*hitLayerIdx + 1) + offset_i
			if i != (len(c.CacheLayers)-1) && c.CachePolicies[i] == WriteBackExclusive {
				break
			}
		}
	}

	// if L1 (layerIdx == 0) cache miss at least
	if update && hit {
	if *hitLayerIdx > 1 {
		// cache upper-most layer
		if c.CachePolicies[*hitLayerIdx-1] == WriteBackExclusive {
			// invalidate under layer
			c.CacheLayers[*hitLayerIdx].InvalidateFiveTuple(f)
		}

		c.CacheFiveTuple(f)
	}}

	return hit, hitLayerIdx
}
func (c *MultiLayerCacheInclusive) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
    // Cache対象のFiveTupleリストを作成し、最初の要素は引数で受け取ったFiveTuple
    fiveTuplesToCache := []*FiveTuple{f}
    evictedFiveTuples := []*FiveTuple{} // 退避されたFiveTupleリスト
    fivetupleDstIP := ipaddress.NewIPaddress(f.DstIP) // FiveTupleのDstIPからIPアドレスを作成

    // ルーティングテーブルで目的地IPアドレスに一致するプレフィックスを検索
    prefix, prefix_item := c.RoutingTable.SearchIP(fivetupleDstIP, 32)
    prefix_size := len(prefix) - 1 // プレフィックスのサイズを取得

    // 一致したプレフィックスのサイズごとにカウントをインクリメント
    for _, p := range prefix {
        c.MatchMap[len(p)] += 1
    }
    c.LongestMatchMap[len(prefix[prefix_size])] += 1 // 最長一致したプレフィックスをカウント

    // プレフィックスに対応するルーティングテーブルの深さを累積
    c.DepthSum += prefix_item[prefix_size].(routingtable.Data).Depth

    // DstIPが指定された深さ（CacheRefBits[1]）より短いプレフィックスを持ち、かつ葉ノードならばキャッシュしない
    if c.RoutingTable.IsShorter(fivetupleDstIP, 32, int(c.CacheRefBits[1])) && c.RoutingTable.IsLeaf(fivetupleDstIP, int(c.CacheRefBits[1])) {				
        c.CacheNotInserted[0] += 1 // キャッシュに挿入されなかったカウントを増やす
    } else {
        // 子ルールに存在するIP数が閾値を超えている場合もキャッシュしない
        temp_limit := c.RoutingTable.CountIPsInChildrenRule(fivetupleDstIP, int(c.CacheRefBits[1]))
        if int(temp_limit) > c.OnceCacheLimit {
            c.CacheNotInserted[1] += 1 // キャッシュに挿入されなかったカウントを増やす
            evictedFiveTuples = c.CacheLayers[0].CacheFiveTuple(f) // 第一レイヤーキャッシュに格納し、退避されたエントリを取得
            c.CacheReplacedByLayer[0] += uint(len(evictedFiveTuples)) // 退避カウントを更新

            // 退避されたエントリが存在し、次のレイヤーにキャッシュされている場合は無効化
            if len(evictedFiveTuples) > 0 {
                hitted, _ := c.CacheLayers[1].IsCachedWithFiveTuple(evictedFiveTuples[0], false)
                if hitted {
                    c.CacheLayers[1].InvalidateFiveTuple(evictedFiveTuples[0])
                    c.Special[1] += 1 // 特殊処理カウントを更新
                }
            }
            return evictedFiveTuples // 退避されたエントリを返す
        }

        // 32ビットと24ビットのプレフィックスを同時にキャッシュする場合
        fiveTuplesToCacheL1 := c.RoutingTable.ReturnIPsInChildrenRule(fivetupleDstIP, int(c.CacheRefBits[1]))
        c.DoInclusive += 1 // インクルーシブキャッシュのカウントを更新
        c.Special[0] += uint(len(fiveTuplesToCacheL1)) // 特殊処理カウントを更新

        // 24ビットの子ルールのIPをキャッシュ
        for _, data := range fiveTuplesToCacheL1 {
            ff := *f
            ff.DstIP = ipaddress.NewIPaddress(data).Uint32()
            evictedFiveTuples = append(evictedFiveTuples, c.CacheLayers[0].CacheFiveTuple(&ff)...)
        }
        c.CacheReplacedByLayer[0] += uint(len(evictedFiveTuples)) // 退避カウントを更新

        // 退避されたエントリが次のレイヤーにキャッシュされている場合は無効化
        for _, data := range evictedFiveTuples {
            hitted, _ := c.CacheLayers[1].IsCachedWithFiveTuple(data, false)
            if hitted {
                c.CacheLayers[1].InvalidateFiveTuple(data)
                c.Special[1] += 1 // 特殊処理カウントを更新
            }
        }
    }

    // 各レイヤーキャッシュに対して処理を行う
    for i, cache := range c.CacheLayers {
        fiveTuplesToCacheNextLayer := []*FiveTuple{} // 次のレイヤーにキャッシュするエントリリスト

        // 最初のレイヤー以外のキャッシュ処理
        if i != 0 {
            for _, f := range fiveTuplesToCache {
                evictedFiveTuples = cache.CacheFiveTuple(f) // キャッシュし、退避されたエントリを取得
                c.CacheReplacedByLayer[i] += uint(len(evictedFiveTuples)) // 退避カウントを更新

                // 最後のレイヤーであれば処理をスキップ
                if i == (len(c.CacheLayers) - 1) {
                    continue
                }

                // キャッシュポリシーに基づいて次のレイヤーにキャッシュするエントリを決定
                switch c.CachePolicies[i] {
                case WriteBackExclusive, WriteBackInclusive:
                    fiveTuplesToCacheNextLayer = append(fiveTuplesToCacheNextLayer, evictedFiveTuples...)
                case WriteThrough:
                    fiveTuplesToCacheNextLayer = fiveTuplesToCache
                }
            }

            // 次のレイヤーにキャッシュするエントリを更新
            fiveTuplesToCache = fiveTuplesToCacheNextLayer
        }
    }

    return evictedFiveTuples // 退避されたエントリを返す
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
