package simulator

import (
	"errors"
	"fmt"
	"reflect"
	"strings"
	"test-module/cache"

	"github.com/koron/go-dproxy"
	"go.mongodb.org/mongo-driver/bson"
)

type Cache struct {
	Type           string   `json:"Type"`
	CacheLayers    []Cache  `json:"CacheLayers"`
	CachePolicies  []string `json:"CachePolicies"`
	OnceCacheLimit int      `json:"OnceCacheLimit"`
	InnerCache     *Cache
	Size           int
	Way            int
	Refbits        int `json:"Refbits"`
}

type SimulatorDefinition struct {
	Type      string `json:"Type"`
	Cache     Cache  `json:"Cache"`
	Rule      string `json:"Rule"`
	DebugMode bool   `json:"DebugMode"`
	Interval  int64  `json:"Interval"`
}

// MakeParameter

// func MakeParameterString(c Cache) (map[string]interface{}, error) {
// 	// ParameterのTypeを取得
// 	paramType := c.Type

// 	var param cache.Parameter
// 	// Typeに基づいてParameterの型を決定する
// 	switch {
// 	case strings.HasPrefix(paramType, "FullAssociative"):
// 		param = &cache.FullAssociativeParameter{
// 			Type: paramType,
// 			Size: uint(c.Size),
// 		}
// 	case strings.HasPrefix(paramType, "CacheWithLookAhead"):
// 		innercache, err := MakeParameterString(*c.InnerCache)
// 		if err != nil {
// 			return nil, err
// 		}
// 		param = &cache.CacheWithLookAheadParameter{
// 			Type:       paramType,
// 			InnerCache: innercache,
// 		}
// 	case strings.HasPrefix(paramType, "NbitFullAssociative"):
// 		param = &cache.NbitFullAssociativeParameter{
// 			Type:    paramType,
// 			Size:    uint(c.Size),
// 			Refbits: uint8(c.Refbits),
// 		}
// 	case strings.HasPrefix(paramType, "NbitNwaySetAssociative"):
// 		param = &cache.NbitSetAssociativeParameter{
// 			Type:    paramType,
// 			Size:    uint(c.Size),
// 			Way:     uint(c.Way),
// 			Refbits: uint8(c.Refbits),
// 		}
// 	case strings.HasPrefix(paramType, "NWaySetAssociative"):
// 		param = &cache.SetAssociativeParameter{
// 			Type: paramType,
// 			Size: uint(c.Size),
// 			Way:  uint(c.Way),
// 		}
// 	case strings.HasPrefix(paramType, "MultiLayer"):
// 		param = &cache.MultiCacheParameter{
// 			Type:          paramType,
// 			CacheLayers:   make([]interface{}, len(c.CacheLayers)),
// 			CachePolicies: make([]cache.CachePolicy, len(c.CachePolicies)),
// 		}

// 		// CacheLayersを再帰的に処理
// 		for i, layer := range c.CacheLayers {
// 			layerParam, err := MakeParameterString(layer)
// 			if err != nil {
// 				return nil, err
// 			}

// 			// CacheLayerをスライスに格納
// 			param.(*cache.MultiCacheParameter).CacheLayers[i] = layerParam
// 		}

// 		// CachePoliciesを格納
// 		for i, policy := range c.CachePolicies {
// 			param.(*cache.MultiCacheParameter).CachePolicies[i] = cache.StringToCachePolicy(policy)
// 		}
// 	default:
// 		return nil, fmt.Errorf("unknown parameter type: %s", paramType)
// 	}

// 	return param.GetParameterString(), nil
// }

// // GetParameter はParameterを返す
// func (s *SimulatorDefinition) GetParameterString() (map[string]interface{}, error) {
// 	param, err := MakeParameterString(s.Cache)
// 	fmt.Printf("param: %v\n", param)
// 	return param, err
// }

func MakeParameterBson(c Cache) (bson.M, error) {
	// ParameterのTypeを取得
	paramType := c.Type

	var param cache.Parameter
	// Typeに基づいてParameterの型を決定する
	switch {
	case strings.HasPrefix(paramType, "FullAssociative"):
		param = &cache.FullAssociativeParameter{
			Type: paramType,
			Size: uint(c.Size),
		}
	case strings.HasPrefix(paramType, "CacheWithLookAhead"):
		innercache, err := MakeParameterBson(*c.InnerCache)
		if err != nil {
			return nil, err
		}
		param = &cache.CacheWithLookAheadParameter{
			Type:       paramType,
			InnerCache: innercache,
		}
	case strings.HasPrefix(paramType, "NbitFullAssociative"):
		param = &cache.NbitFullAssociativeParameter{
			Type:    paramType,
			Size:    uint(c.Size),
			Refbits: uint8(c.Refbits),
		}
	case strings.HasPrefix(paramType, "NbitNWaySetAssociative"):
		param = &cache.NbitSetAssociativeParameter{
			Type:    paramType,
			Size:    uint(c.Size),
			Way:     uint(c.Way),
			Refbits: uint8(c.Refbits),
		}
	case strings.HasPrefix(paramType, "NWaySetAssociative"):
		param = &cache.SetAssociativeParameter{
			Type: paramType,
			Size: uint(c.Size),
			Way:  uint(c.Way),
		}
	case strings.HasPrefix(paramType, "MultiLayer"):
		param = &cache.MultiCacheParameter{
			Type:          paramType,
			CacheLayers:   make([]cache.Parameter, len(c.CacheLayers)),
			CachePolicies: make([]cache.CachePolicy, len(c.CachePolicies)),
		}

		// CacheLayersを再帰的に処理
		for i, layer := range c.CacheLayers {
			layerParam, err := MakeParameter(layer)
			if err != nil {
				return nil, err
			}

			// CacheLayerをスライスに格納
			param.(*cache.MultiCacheParameter).CacheLayers[i] = layerParam
		}

		// CachePoliciesを格納
		for i, policy := range c.CachePolicies {
			param.(*cache.MultiCacheParameter).CachePolicies[i] = cache.StringToCachePolicy(policy)
		}
	default:
		return nil, fmt.Errorf("unknown parameter type: %s", paramType)
	}

	return param.GetBson(), nil
}

// GetParameter はParameterを返す
func (s *SimulatorDefinition) GetParameterBson() (bson.M, error) {
	param, err := MakeParameterBson(s.Cache)
	fmt.Printf("param: %v\n", param)
	return param, err
}

func (s *SimulatorDefinition) GetParameter() (cache.Parameter, error) {
	param, err := MakeParameter(s.Cache)
	fmt.Printf("param: %v\n", param)
	return param, err
}
func MakeParameter(c Cache) (cache.Parameter, error) {
	// ParameterのTypeを取得
	paramType := c.Type

	var param cache.Parameter
	// Typeに基づいてParameterの型を決定する
	switch {
	case strings.HasPrefix(paramType, "FullAssociative"):
		param = &cache.FullAssociativeParameter{
			Type: paramType,
			Size: uint(c.Size),
		}
	case strings.HasPrefix(paramType, "CacheWithLookAhead"):
		innercache, err := MakeParameterBson(*c.InnerCache)
		if err != nil {
			return nil, err
		}
		param = &cache.CacheWithLookAheadParameter{
			Type:       paramType,
			InnerCache: innercache,
		}
	case strings.HasPrefix(paramType, "NbitFullAssociative"):
		param = &cache.NbitFullAssociativeParameter{
			Type:    paramType,
			Size:    uint(c.Size),
			Refbits: uint8(c.Refbits),
		}
	case strings.HasPrefix(paramType, "NbitNWaySetAssociative"):
		param = &cache.NbitSetAssociativeParameter{
			Type:    paramType,
			Size:    uint(c.Size),
			Way:     uint(c.Way),
			Refbits: uint8(c.Refbits),
		}
	case strings.HasPrefix(paramType, "NWaySetAssociative"):
		param = &cache.SetAssociativeParameter{
			Type: paramType,
			Size: uint(c.Size),
			Way:  uint(c.Way),
		}
	case strings.HasPrefix(paramType, "MultiLayer"):
		param = &cache.MultiCacheParameter{
			CacheLayers:   make([]cache.Parameter, len(c.CacheLayers)),
			CachePolicies: make([]cache.CachePolicy, len(c.CachePolicies)),
		}

		// CacheLayersを再帰的に処理
		for i, layer := range c.CacheLayers {
			layerParam, err := MakeParameter(layer)
			if err != nil {
				return nil, err
			}

			// CacheLayerをスライスに格納
			param.(*cache.MultiCacheParameter).CacheLayers[i] = layerParam
		}

		// CachePoliciesを格納
		for i, policy := range c.CachePolicies {
			param.(*cache.MultiCacheParameter).CachePolicies[i] = cache.StringToCachePolicy(policy)
		}
		param.(*cache.MultiCacheParameter).Type = cache.GetMultiLayerParameterTypeName(paramType, param.(*cache.MultiCacheParameter).CacheLayers)
	default:
		return nil, fmt.Errorf("unknown parameter type: %s", paramType)
	}

	return param, nil
}

// isZeroValue は、与えられた値がゼロ値かどうかを確認するヘルパー関数
func isZeroValue(v reflect.Value) bool {
	// ゼロ値と比較してゼロ値かどうかを判定
	return reflect.DeepEqual(v.Interface(), reflect.Zero(v.Type()).Interface())
}

// CacheLayerの数を確認するメソッド
func (s *SimulatorDefinition) GetCacheLayerCount() int {
	return len(s.Cache.CacheLayers)
}

// CacheLayerを追加するメソッド
func (s *SimulatorDefinition) AddCacheLayer(layer *Cache) {
	if layer == nil {
		l := Cache{
			Type:    "NbitNWaySetAssociativeDstipLRUCache",
			Size:    64,
			Way:     4,
			Refbits: 32,
		}
		s.Cache.CacheLayers = append(s.Cache.CacheLayers, l)
		s.Cache.CachePolicies = append(s.Cache.CachePolicies, "WriteThrough")
	} else {
		s.Cache.CacheLayers = append(s.Cache.CacheLayers, *layer)
	}
}

// CacheLayerを削除するメソッド（指定されたインデックスの要素を削除）
func (s *SimulatorDefinition) RemoveCacheLayer(index int) error {
	if index < 0 || index >= len(s.Cache.CacheLayers) {
		return errors.New("インデックスが範囲外です")
	}

	// 指定されたインデックスの CacheLayer を削除
	s.Cache.CacheLayers = append(s.Cache.CacheLayers[:index], s.Cache.CacheLayers[index+1:]...)
	return nil
}

// CacheLayerのRefbitsを変更するメソッド
func (s *SimulatorDefinition) SetRefbits(index int, refbits int) error {
	if index < 0 || index >= len(s.Cache.CacheLayers) {
		return errors.New("インデックスが範囲外です")
	}
	s.Cache.CacheLayers[index].Refbits = refbits
	return nil
}

// SimulatorDefinitionのディープコピーを作成するメソッド
func (s *SimulatorDefinition) DeepCopy() SimulatorDefinition {
	// 新しい SimulatorDefinition を作成
	newSimulator := *s

	// CacheLayersをディープコピー
	newSimulator.Cache.CacheLayers = make([]Cache, len(s.Cache.CacheLayers))
	copy(newSimulator.Cache.CacheLayers, s.Cache.CacheLayers)

	// CachePoliciesをコピー
	newSimulator.Cache.CachePolicies = append([]string{}, s.Cache.CachePolicies...)

	return newSimulator
}

func InitializedSimulatorDefinition(json interface{}) SimulatorDefinition {
	p := dproxy.New(json)

	// シミュレータタイプを取得
	simType, err := p.M("Type").String()
	if err != nil {
		panic(fmt.Sprintf("Simulator type is missing or invalid: %v", err))
	}

	// デフォルトのシミュレータ定義
	simDef := SimulatorDefinition{
		Type: simType,
		Cache: Cache{
			Type:           "MultiLayerCacheExclusive",
			CachePolicies:  []string{"WriteThrough"},
			OnceCacheLimit: 64,
		},
		Rule:      "rules/wide.rib.20240625.1400.unique.rule",
		DebugMode: false,
		Interval:  10000000,
	}

	// キャッシュレイヤー情報の取得
	cacheLayers, err := p.M("Cache").M("CacheLayers").Array()
	if err != nil {
		panic(fmt.Sprintf("Error retrieving cache layers: %v", err))
	}

	// キャッシュレイヤーの初期化
	simDef.Cache.CacheLayers = []Cache{}
	for _, l := range cacheLayers {
		layer := dproxy.New(l)
		size, err := layer.M("Size").Int64()
		if err != nil {
			panic(fmt.Sprintf("Cache layer size is invalid: %v", err))
		}

		refbits, err := layer.M("Refbits").Int64()
		if err != nil {
			panic(fmt.Sprintf("Cache layer refbits are invalid: %v", err))
		}

		cacheType, err := layer.M("Type").String()
		if err != nil {
			panic(fmt.Sprintf("Cache layer type is invalid: %v", err))
		}

		// キャッシュレイヤーの追加
		simDef.Cache.CacheLayers = append(simDef.Cache.CacheLayers, Cache{
			Type:    cacheType,
			Size:    int(size),
			Refbits: int(refbits),
		})
	}
	// キャッシュポリシーの取得（オプション）
	cachePolicies, err := p.M("Cache").M("CachePolicies").Array()
	if err == nil {
		// []interface{} から []string に変換
		simDef.Cache.CachePolicies = make([]string, len(cachePolicies))
		for i, policy := range cachePolicies {
			simDef.Cache.CachePolicies[i], err = dproxy.New(policy).String()
			if err != nil {
				panic(fmt.Sprintf("Cache policy is invalid: %v", err))
			}
		}
	}
	// キャッシュの制限サイズ（オプション）
	onceCacheLimit, err := p.M("Cache").M("OnceCacheLimit").Int64()
	if err == nil {
		simDef.Cache.OnceCacheLimit = int(onceCacheLimit)
	}

	// ルールファイルの取得（オプション）
	ruleFile, err := p.M("Rule").String()
	if err == nil {
		simDef.Rule = ruleFile
	}

	// デバッグモードの取得（オプション）
	debugMode, err := p.M("DebugMode").Bool()
	if err == nil {
		simDef.DebugMode = debugMode
	}

	// シミュレーション間隔の取得（オプション）
	interval, err := p.M("Interval").Int64()
	if err == nil {
		simDef.Interval = interval
	}

	return simDef
}

// 初期化関数
func NewSimulatorDefinition(cachetype string) (SimulatorDefinition, error) {
	if cachetype == "MultiLayerCacheExclusive" {
		return NewMultiLayerExclusiveCacheSimulatorDefinition(), nil
	} else if cachetype == "LRU" {
		return NewLRUSimulatorDefinition(), nil
	} else {
		return SimulatorDefinition{}, errors.New("invalid cache type")
	}
}

func NewMultiLayerExclusiveCacheSimulatorDefinition() SimulatorDefinition {
	return SimulatorDefinition{
		Type: "SimpleCacheSimulator",
		Cache: Cache{
			Type: "MultiLayerCacheExclusive",
			CacheLayers: []Cache{
				{
					Type:    "NbitNWaySetAssociativeDstipLRUCache",
					Way:     4,
					Refbits: 32,
				},
				{
					Type:    "NbitNWaySetAssociativeDstipLRUCache",
					Way:     4,
					Refbits: 16,
				},
			},
			CachePolicies: []string{"WriteThrough"},
		},
		Rule:      "rules/wide.rib.20240625.1400.unique.rule",
		DebugMode: true,
		Interval:  10000000000,
	}
}
func NewLRUSimulatorDefinition() SimulatorDefinition {
	return SimulatorDefinition{
		Type: "SimpleCacheSimulator",
		Cache: Cache{
			Type: "NWaySetAssociativeLRUCache",
			Size: 64,
			Way:  4,
		},
	}
}

// GenerateCapacityAndRefbitsPermutations は、指定された容量 (capacity) と
// refbits の範囲 (refbitsRange) のすべての組み合わせを生成する関数。
// layers は生成する組み合わせの階層数を表し、結果は [capacity, refbits] の
// ペアを要素とするスライスのリストとして返される。
func GenerateCapacityAndRefbitsPermutations(capacity []int, refbitsRange []int, layers int) [][][2]int {
	// 結果を格納するスライス。各要素は [capacity, refbits] のペアが入る。
	results := [][][2]int{}
	// 現在探索中の組み合わせを保持するスライス。サイズは layers に等しい。
	current := make([][2]int, layers)

	// 再帰的に組み合わせを探索するための関数を定義。
	// index は現在の階層を指し、prevRefbits は前の refbits の値を保持する。
	var backtrack func(int, int)
	backtrack = func(index int, prevRefbits int) {
		// 探索がすべての階層に達した場合、組み合わせを結果に追加する。
		if index == layers {
			// current のコピーを作成して結果に追加。直接追加すると current の参照が使われるため、コピーが必要。
			combination := make([][2]int, layers)
			copy(combination, current)
			if combination[0][1] == 32 {
				// refbits が 32 の場合は今のところは無効な組み合わせなので結果に追加しない。
				results = append(results, combination)
			}
			return
		}
		// capacity と refbitsRange のすべての組み合わせを試す。
		for _, cap := range capacity {
			for _, ref := range refbitsRange {
				// 最初の階層では制約がないが、2階層目以降では前の refbits より小さい値のみ許可する。
				if index == 0 || ref < prevRefbits {
					// 現在の階層に [capacity, refbits] の組み合わせを保存。
					current[index] = [2]int{cap, ref}
					// 次の階層へ再帰的に探索を続ける。prevRefbits を現在の ref に更新。
					backtrack(index+1, ref)
				}
			}
		}
	}

	// 再帰探索を開始。最初の prevRefbits の値には大きな数 (33) を渡すことで、最初の階層に制約を与えないようにする。
	backtrack(0, 33)
	return results
}

// 各CacheLayerにCapacityとRefbitsを設定して新しいSimulatorDefinitionを作成
func CreateSimulatorWithCapacityAndRefbits(base SimulatorDefinition, settings [][2]int) SimulatorDefinition {
	newSim := base.DeepCopy()
	for i, setting := range settings {
		newSim.Cache.CacheLayers[i].Size = setting[0]
		newSim.Cache.CacheLayers[i].Refbits = setting[1]
	}
	return newSim
}

// 各CacheLayerにCapacityとRefbitsを設定して新しいSimulatorDefinitionを作成
func CreateSimulatorWithCapacity(base SimulatorDefinition, capacity int) SimulatorDefinition {
	newSim := base.DeepCopy()
	newSim.Cache.Size = capacity
	return newSim
}
