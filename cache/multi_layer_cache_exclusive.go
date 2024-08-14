package cache

import (
	"fmt"
	"test-module/ipaddress"
	"test-module/routingtable"
)

// MultiLayerCacheExclusive は、複数のキャッシュ層を持ち、それぞれのキャッシュ層に独自のキャッシュポリシーを設定できるキャッシュシステムです。
type MultiLayerCacheExclusive struct {
	CacheLayers          []Cache
	CachePolicies        []CachePolicy
	CacheReferedByLayer  []uint
	CacheReplacedByLayer []uint
	CacheHitByLayer      []uint

	CacheRefBits     []uint
	CacheNotInserted []uint
	RoutingTable     routingtable.RoutingTablePatriciaTrie
	DepthSum         uint64
	LongestMatchMap  [33]int
	MatchMap         [33]int
}

// StatString は、キャッシュの統計情報をJSON形式の文字列として返します。
func (c *MultiLayerCacheExclusive) StatString() string {
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

// IsCached は、パケットがキャッシュされているかを確認し、必要に応じてキャッシュを更新します。
//
// 引数:
//
//	p: 確認するパケット。
//	update: キャッシュを更新するかどうか。
//
// 戻り値:
//
//	パケットがキャッシュされているかどうかを示すブール値と、キャッシュされている層のインデックスへのポインタ。
func (c *MultiLayerCacheExclusive) IsCached(p *Packet, update bool) (bool, *int) {
	return c.IsCachedWithFiveTuple(p.FiveTuple(), update)
}

// IsCachedWithFiveTuple は、FiveTuple で識別されたパケットがキャッシュされているかを確認し、必要に応じてキャッシュを更新します。
//
// 引数:
//
//	f: パケットを識別する FiveTuple。
//	update: キャッシュを更新するかどうか。
//
// 戻り値:
//
//	パケットがキャッシュされているかどうかを示すブール値と、キャッシュされている層のインデックスへのポインタ。

func IsLeafExecuted() bool {
	fmt.Println("IsLeafExecuted")
	return true
}
func (c *MultiLayerCacheExclusive) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hit := false
	var hitLayerIdx *int // ヒットした場合に nil ではない

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

	// 下位層の更新
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

	// 少なくともL1キャッシュミスの場合
	if update && hit {
		if *hitLayerIdx > 1 {
			// 上位層にキャッシュ
			if c.CachePolicies[*hitLayerIdx-1] == WriteBackExclusive {
				// 下位層を無効化
				c.CacheLayers[*hitLayerIdx].InvalidateFiveTuple(f)
			}
			c.CacheFiveTuple(f)
		}
	}

	return hit, hitLayerIdx
}

// CacheFiveTuple は、FiveTuple をキャッシュに挿入し、必要に応じてエントリを置換します。
//
// 引数:
//
//	f: キャッシュする FiveTuple。
//
// 戻り値:
//
//	置換された FiveTuple のスライス。
func (c *MultiLayerCacheExclusive) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	// キャッシュする FiveTuple を格納するスライス
	fiveTuplesToCache := []*FiveTuple{f}
	// 置換された FiveTuple を格納するスライス
	evictedFiveTuples := []*FiveTuple{}
	// FiveTuple の宛先 IP アドレスを IPaddress 型に変換
	fivetupleDstIP := ipaddress.NewIPaddress(f.DstIP)

	// ルーティングテーブルから宛先 IP にマッチするプレフィックスを検索
	// prefix には二進数のプレフィックス(ex."1011011")が格納される
	// prefix_item にはNext hopとDepthが格納される
	prefix, prefix_item := c.RoutingTable.SearchIP(fivetupleDstIP, 32)
	// 最長一致するプレフィックスのインデックスを取得
	prefix_size := len(prefix) - 1

	// マッチしたプレフィックスの長さに基づいて MatchMap を更新
	for _, p := range prefix {
		c.MatchMap[len(p)] += 1
	}
	// 最長一致するプレフィックスのカウントを更新
	c.LongestMatchMap[len(prefix[prefix_size])] += 1

	// プレフィックスの深さの合計を更新
	c.DepthSum += prefix_item[prefix_size].(routingtable.Data).Depth

	// キャッシュ挿入の条件をチェック
	// 最長一致したIPアドレスのプレフィックスがキャッシュ参照ビット以下である場合 + 葉ノードである場合
	// /nに挿入
	if c.RoutingTable.IsShorter(fivetupleDstIP, 32, int(c.CacheRefBits[1])) &&  c.RoutingTable.IsLeaf(fivetupleDstIP, int(c.CacheRefBits[1])) {
		// 条件を満たさない場合、キャッシュ未挿入のカウントを更新
		c.CacheNotInserted[0] += 1 //32ビットキャッシュへの挿入なし
	} else {
		// 条件を満たす場合、キャッシュ未挿入の別のカウントを更新し、キャッシュに挿入
		c.CacheNotInserted[1] += 1 // nキャッシュへの挿入なし
		evictedFiveTuples = c.CacheLayers[0].CacheFiveTuple(f) // /32キャッシュに挿入
		// 置換された FiveTuple の数をカウント
		c.CacheReplacedByLayer[0] += uint(len(evictedFiveTuples))
		return evictedFiveTuples
	}

	// 複数レイヤーのキャッシュ処理
	for i, cache := range c.CacheLayers {
		// 次のレイヤーにキャッシュする FiveTuple を格納するスライス
		fiveTuplesToCacheNextLayer := []*FiveTuple{}

		// 最初のレイヤーは既に処理済みのためスキップ
		if i != 0 {
			// 現在のレイヤーにキャッシュする
			for _, f := range fiveTuplesToCache {
				evictedFiveTuples = cache.CacheFiveTuple(f)
				c.CacheReplacedByLayer[i] += uint(len(evictedFiveTuples))

				// 最後のレイヤーであれば次のレイヤーに渡さない
				if i == (len(c.CacheLayers) - 1) {
					continue
				}

				// キャッシュポリシーに応じて次のレイヤーに渡す FiveTuple を決定
				switch c.CachePolicies[i] {
				case WriteBackExclusive, WriteBackInclusive:
					fiveTuplesToCacheNextLayer = append(fiveTuplesToCacheNextLayer, evictedFiveTuples...)
				case WriteThrough:
					fiveTuplesToCacheNextLayer = fiveTuplesToCache
				}
			}

			// 次のレイヤーに渡す FiveTuple を更新
			fiveTuplesToCache = fiveTuplesToCacheNextLayer
		}
	}

	return evictedFiveTuples
}

// InvalidateFiveTuple は、キャッシュ内の FiveTuple を無効化します。
//
// 引数:
//
//	f: 無効化する FiveTuple。
func (c *MultiLayerCacheExclusive) InvalidateFiveTuple(f *FiveTuple) {
	panic("not implemented")
}

// Clear は、すべてのキャッシュ層をクリアします。
func (c *MultiLayerCacheExclusive) Clear() {
	for _, cache := range c.CacheLayers {
		cache.Clear()
	}
}

// Description は、キャッシュ層の説明を文字列形式で返します。
func (c *MultiLayerCacheExclusive) Description() string {
	str := "MultiLayerCacheExclusive["
	for i, cacheLayer := range c.CacheLayers {
		if i != 0 {
			str += ", "
		}
		str += cacheLayer.Description()
	}
	str += "]"
	return str
}

// ParameterString は、キャッシュパラメータをJSON形式の文字列として返します。
func (c *MultiLayerCacheExclusive) ParameterString() string {
	str := "{"

	str += "\"Type\": \"MultiLayerCacheExclusive\", "
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
