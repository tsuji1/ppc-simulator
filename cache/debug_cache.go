package cache

import (
	"encoding/json"
	"fmt"
	"log"
	"test-module/ipaddress"
	"test-module/routingtable"
)

type DebugCache struct {
	CacheLayers          []Cache
	CachePolicies        []CachePolicy
	CacheReferedByLayer  []uint
	CacheReplacedByLayer []uint
	CacheHitByLayer      []uint
	CacheRefBits         []uint
	CacheInserted        []uint
	RoutingTable         routingtable.RoutingTablePatriciaTrie
	PrefixMapByLength    map[int]map[string]int
	IsLeafMapByLength    map[int]map[string]int
	MatchMap             [33]uint
	LongestMatchMap      [33]uint
	IsLeafMap            [33]uint

	IsLeafCountByDstIP map[int]map[string]int
}

// StatString は、キャッシュの統計情報をJSON形式の文字列として返します。

type DebugCacheStat struct {
	Hit                   []uint
	MatchMap              []uint
	LongestMatchMap       []uint
	UniquePrefixesCount   map[int]int
	UniqueLeafCount       map[int]int
	IsLeafMap             [33]uint
	PrefixMapByLength     map[int]map[string]int
	IsLeafMapByLength     map[int]map[string]int
	UniqueLeafPacketCount map[int]int
}

func (c *DebugCache) StatString() string {
	// Stat メソッドを呼び出して統計情報を取得
	stat := c.Stat().(DebugCacheStat)

	// 構造体をJSON形式に変換
	jsonData, err := json.MarshalIndent(stat, "", "  ")
	if err != nil {
		log.Fatalf("JSONエンコードエラー: %v", err)
	}

	// JSON形式の文字列を返す
	return string(jsonData)
}

// Stat は、キャッシュの統計情報を構造体として返します。
func (c *DebugCache) Stat() interface{} {
	// MatchMap と LongestMatchMap を生成
	matchMap := make([]uint, 33)
	longestMatchMap := make([]uint, 33)
	for i := 0; i <= 32; i++ {
		matchMap[i] = uint(c.MatchMap[i])
		longestMatchMap[i] = uint(c.LongestMatchMap[i])
	}

	uniquePrefixesCount := make(map[int]int)

	for length, prefixMap := range c.PrefixMapByLength {
		sum := 0
		uniqueCount := 0

		// 各プレフィックスの参照回数を合計し、種類をカウント
		for _, count := range prefixMap {
			sum += count  // 参照回数の合計
			uniqueCount++ // 異なるプレフィックスの種類
		}

		// プレフィックスの長さごとに合計を更新
		uniquePrefixesCount[length] = uniqueCount
	}

	uniqueLeafCount := make(map[int]int)

	for length, leafMap := range c.IsLeafMapByLength {
		sum := 0
		uniqueCount := 0

		// 各プレフィックスの参照回数を合計し、種類をカウント
		for _, count := range leafMap {
			sum += count  // 参照回数の合計
			uniqueCount++ // 異なるプレフィックスの種類

		}

		// プレフィックスの長さごとに合計を更新
		uniqueLeafCount[length] = uniqueCount
	}

	uniqueLeafPacketCount := make(map[int]int)
	for length, leafMap := range c.IsLeafCountByDstIP {
		sum := 0
		uniqueCount := 0

		// 各プレフィックスの参照回数を合計し、種類をカウント
		for _, count := range leafMap {
			sum += count  // 参照回数の合計
			uniqueCount++ // 異なるプレフィックスの種類
		}

		// プレフィックスの長さごとに合計を更新
		uniqueLeafPacketCount[length] = uniqueCount
	}

	// 構造体を作成して返す
	return DebugCacheStat{
		Hit:                   c.CacheHitByLayer,
		IsLeafMap:             c.IsLeafMap,
		MatchMap:              matchMap,
		LongestMatchMap:       longestMatchMap,
		UniquePrefixesCount:   uniquePrefixesCount,
		UniqueLeafCount:       uniqueLeafCount,
		UniqueLeafPacketCount: uniqueLeafPacketCount,
	}
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
func (c *DebugCache) IsCached(p *Packet, update bool) (bool, *int) {
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

func (c *DebugCache) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	hit := false
	var hitLayerIdx *int // ヒットした場合に nil ではない
	var prefix []string
	// var items []Item

	// ルーティングテーブルから宛先 IP にマッチするプレフィックスを検索
	// prefix には二進数のプレフィックス(ex."1011011")が格納される
	// prefix_item にはNext hopとDepthが格納される
	prefix, _ = searchIP(f, &c.RoutingTable, 32)

	// 最長一致するプレフィックスのインデックスを取得
	prefix_size := len(prefix) - 1
	// マッチしたプレフィックスの長さに基づいて MatchMap を更新
	for _, p := range prefix {
		c.MatchMap[len(p)] += 1
	}

	// 最長一致するプレフィックスのカウントを更新
	c.LongestMatchMap[len(prefix[prefix_size])] += 1

	longestPrefix := prefix[prefix_size]
	longestPrefixLength := len(longestPrefix)
	// c.PrefixMapByLengthがnilでないことを確認する
	if c.PrefixMapByLength == nil {
		c.PrefixMapByLength = make(map[int]map[string]int)
	}
	// 特定の長さのプレフィックスマップが存在しない場合は初期化する
	if c.PrefixMapByLength[longestPrefixLength] == nil {
		c.PrefixMapByLength[longestPrefixLength] = make(map[string]int)
	}

	if _, exists := c.PrefixMapByLength[longestPrefixLength]; !exists {
		c.PrefixMapByLength[longestPrefixLength] = make(map[string]int)
	}
	c.PrefixMapByLength[longestPrefixLength][longestPrefix] += 1

	if c.IsLeafMapByLength == nil {
		c.IsLeafMapByLength = make(map[int]map[string]int)
	}
	if c.IsLeafMapByLength[int(f.IsLeafIndex)] == nil {
		c.IsLeafMapByLength[int(f.IsLeafIndex)] = make(map[string]int)
	}

	if c.IsLeafCountByDstIP == nil {
		c.IsLeafCountByDstIP = make(map[int]map[string]int)
	}
	if c.IsLeafCountByDstIP[int(f.IsLeafIndex)] == nil {
		c.IsLeafCountByDstIP[int(f.IsLeafIndex)] = make(map[string]int)
	}

	c.IsLeafMap[f.IsLeafIndex] += 1
	fivetupleDstIP := ipaddress.NewIPaddress(f.DstIP)
	dstIpStr := fivetupleDstIP.MaskedBitString(int(f.IsLeafIndex))
	c.IsLeafCountByDstIP[int(f.IsLeafIndex)][fivetupleDstIP.String()] += 1
	// c.IsLeafMapByLength[longestPrefixLength][dstIpStr] = int(f.IsLeafIndex)
	c.IsLeafMapByLength[int(f.IsLeafIndex)][dstIpStr] += 1
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

	// // 下位層の更新
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

	// 少なくともL1キャッシュミスの場合
	// if update && hit {
	// 	if *hitLayerIdx > 1 {
	// 		// 上位層にキャッシュ
	// 		if c.CachePolicies[*hitLayerIdx-1] == WriteBackExclusive {
	// 			// 下位層を無効化
	// 			c.CacheLayers[*hitLayerIdx].InvalidateFiveTuple(f)
	// 		}
	// 		c.CacheFiveTuple(f)
	// 	}
	// }

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
func (c *DebugCache) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	// キャッシュする FiveTuple を格納するスライス
	fiveTuplesToCache := []*FiveTuple{f}
	// 置換された FiveTuple を格納するスライス
	evictedFiveTuples := []*FiveTuple{}
	// FiveTuple の宛先 IP アドレスを IPaddress 型に変換
	// fivetupleDstIP := ipaddress.NewIPaddress(f.DstIP)

	// プレフィックスの深さの合計を更新
	// c.DepthSum += prefix_item[prefix_size].(routingtable.Data).Depth

	// キャッシュ挿入の条件をチェック
	// 最長一致したIPアドレスのプレフィックスがキャッシュ参照ビット以下である場合 + 葉ノードである場合
	// /nに挿入

	hitLayer := 0
	//最終的にはレイヤ0であるのでk=0は確認していない。
	for k := len(c.CacheLayers) - 1; k > -2; k-- {
		if k == -1 {
			return make([]*FiveTuple, 0)
		}
		if isLeaf(f, &c.RoutingTable, int(c.CacheRefBits[k])) {
			// 条件を満たさない場合、キャッシュ未挿入のカウントを更新
			hitLayer = k

			break
		}

	}
	c.CacheInserted[hitLayer] += 1
	// 	// 条件を満たす場合、キャッシュ未挿入の別のカウントを更新し、キャッシュに挿入
	// c.CacheNotInserted[1] += 1                             // nキャッシュへの挿入なし
	// evictedFiveTuples = c.CacheLayers[0].CacheFiveTuple(f) // /32キャッシュに挿入
	// // 置換された FiveTuple の数をカウント
	// c.CacheReplacedByLayer[0] += uint(len(evictedFiveTuples))
	// return evictedFiveTuples

	// 複数レイヤーのキャッシュ処理
	for i, cache := range c.CacheLayers {
		if i == hitLayer {
			for _, f := range fiveTuplesToCache {
				evictedFiveTuples = cache.CacheFiveTuple(f)
				c.CacheReplacedByLayer[i] += uint(len(evictedFiveTuples))
			}
		} else {
			continue
		}

		// // 次のレイヤーにキャッシュする FiveTuple を格納するスライス
		// fiveTuplesToCacheNextLayer := []*FiveTuple{}

		// // 最初のレイヤーは既に処理済みのためスキップ
		// if i != 0 {
		// 	// 現在のレイヤーにキャッシュする
		// 	for _, f := range fiveTuplesToCache {
		// 		evictedFiveTuples = cache.CacheFiveTuple(f)
		// 		c.CacheReplacedByLayer[i] += uint(len(evictedFiveTuples))

		// 		// 最後のレイヤーであれば次のレイヤーに渡さない
		// 		if i == (len(c.CacheLayers) - 1) {
		// 			continue
		// 		}

		// 		// キャッシュポリシーに応じて次のレイヤーに渡す FiveTuple を決定
		// 		switch c.CachePolicies[i] {
		// 		case WriteBackExclusive, WriteBackInclusive:
		// 			fiveTuplesToCacheNextLayer = append(fiveTuplesToCacheNextLayer, evictedFiveTuples...)
		// 		case WriteThrough:
		// 			fiveTuplesToCacheNextLayer = fiveTuplesToCache
		// 		}
		// 	}

		// 	// 次のレイヤーに渡す FiveTuple を更新
		// 	fiveTuplesToCache = fiveTuplesToCacheNextLayer
		// }
	}

	return evictedFiveTuples
}

// InvalidateFiveTuple は、キャッシュ内の FiveTuple を無効化します。
//
// 引数:
//
//	f: 無効化する FiveTuple。
func (c *DebugCache) InvalidateFiveTuple(f *FiveTuple) {
	panic("not implemented")
}

// Clear は、すべてのキャッシュ層をクリアします。
func (c *DebugCache) Clear() {
	for _, cache := range c.CacheLayers {
		cache.Clear()
	}
}

// DescriptionParameter は、キャッシュ層の説明を文字列形式で返します。
func (c *DebugCache) DescriptionParameter() string {
	str := "DebugCache["
	for i, cacheLayer := range c.CacheLayers {
		if i != 0 {
			str += ", "
		}
		str += cacheLayer.Description()
	}
	str += "]"
	return str
}

func (c *DebugCache) Description() string {
	str := "DebugCache"
	return str
}

// ParameterString は、キャッシュパラメータをJSON形式の文字列として返します。
func (c *DebugCache) ParameterString() string {
	str := "{"

	str += "\"Type\": \"DebugCache\", "
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

// Parameter は、DebugCache のパラメータを返します。
func (c *DebugCache) Parameter() Parameter {
	// CacheLayers の Parameter を取得し、スライスに格納
	var cacheLayers []Parameter
	for _, cacheLayer := range c.CacheLayers {
		// 各 CacheLayer の Parameter() メソッドを呼び出す
		cacheLayers = append(cacheLayers, cacheLayer.Parameter())
	}

	// MultiCacheParameter 構造体を返す
	return &MultiCacheParameter{
		Type:          c.DescriptionParameter(), // パラメータのタイプ
		CacheLayers:   cacheLayers,              // キャッシュレイヤーのパラメータ
		CachePolicies: c.CachePolicies,          // キャッシュポリシー
	}
}
