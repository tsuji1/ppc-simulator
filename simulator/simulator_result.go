package simulator

import (
	"encoding/json"

	"go.mongodb.org/mongo-driver/bson"
)

// MultiLayerCacheの構造体を定義
type SimulatorResult struct {
	Type       string      `json:"Type" bson:"type"` // jsonとbsonのタグを両方使用
	Parameter  interface{} `json:"Parameter" bson:"parameter"`
	Processed  int         `json:"Processed" bson:"processed"`
	Hit        int         `json:"Hit" bson:"hit"`
	HitRate    float64     `json:"HitRate" bson:"hitrate"`
	StatDetail interface{} `json:"StatDetail" bson:"statdetail"`
}

// ToJSON メソッド: SimulatorResult 構造体をJSONとして出力する関数
func (sr SimulatorResult) ToJSON() (string, error) {
	// JSON化の際に、インターフェース型の内容を正しく表示するため、特別に構造体を作成する
	temp := struct {
		Type       string      `json:"Type"`
		Parameter  interface{} `json:"Parameter"`
		Processed  int         `json:"Processed"`
		Hit        int         `json:"Hit"`
		HitRate    float64     `json:"HitRate"`
		StatDetail interface{} `json:"StatDetail"`
	}{
		Type:       sr.Type,
		Parameter:  sr.Parameter,
		Processed:  sr.Processed,
		Hit:        sr.Hit,
		HitRate:    sr.HitRate,
		StatDetail: sr.StatDetail,
	}

	// JSONにエンコード
	result, err := json.MarshalIndent(temp, "", "  ")
	if err != nil {
		return "", err
	}

	return string(result), nil
}

// ToBSON メソッド: SimulatorResult 構造体をBSONとして出力する関数
func (sr SimulatorResult) ToBSON() (bson.M, error) {
	// BSON化の際に、インターフェース型の内容を正しく表示するため、特別に構造体を作成する
	temp := bson.M{
		"type":       sr.Type,
		"parameter":  sr.Parameter,
		"processed":  sr.Processed,
		"hit":        sr.Hit,
		"hitrate":    sr.HitRate,
		"statdetail": sr.StatDetail,
	}

	// BSONにエンコード
	return temp, nil
}

// setParameter 関数: bson.M も引数に追加
// func setParameter(paramData bson.M) (cache.Parameter, error) {
// 	// ParameterのTypeを取得
// 	paramType, ok := paramData["type"].(string)
// 	if !ok {
// 		return nil, fmt.Errorf("parameter type is missing or invalid")
// 	}

// 	var param cache.Parameter

// 	// Typeに基づいてParameterの型を決定する
// 	switch {
// 	case strings.HasPrefix(paramType, "FullAssociative"):
// 		param = &cache.FullAssociativeParameter{}
// 	case strings.HasPrefix(paramType, "CacheWithLookAhead"):
// 		param = &cache.CacheWithLookAheadParameter{}
// 	case strings.HasPrefix(paramType, "NbitFullAssociative"):
// 		param = &cache.NbitFullAssociativeParameter{}
// 	case strings.HasPrefix(paramType, "NbitNwaySetAssociative"):
// 		param = &cache.NbitSetAssociativeParameter{}
// 	case strings.HasPrefix(paramType, "NWaySetAssociative"):
// 		param = &cache.SetAssociativeParameter{}
// 	case strings.HasPrefix(paramType, "MultiLayer"):
// 		param = &cache.MultiCacheParameter{}

// 		// MultiLayerCacheの場合、CacheLayersを再帰的に処理
// 		cacheLayersRaw, ok := paramData["cachelayers"]
// 		if !ok {
// 			return nil, fmt.Errorf("cache layers field is missing")
// 		}

// 		// cacheLayersがprimitive.A（MongoDBの配列型）かどうか確認
// 		cacheLayers, ok := cacheLayersRaw.(primitive.A)
// 		if !ok {
// 			return nil, fmt.Errorf("cache layers are of an invalid type: %T", cacheLayersRaw)
// 		}

// 		// CacheLayersを格納するスライスを作成
// 		param.(*cache.MultiCacheParameter).CacheLayers = make([]interface{}, len(cacheLayers))

// 		// CacheLayersを再帰的に処理
// 		for i, layer := range cacheLayers {
// 			layerData, ok := layer.(bson.M)
// 			if !ok {
// 				return nil, fmt.Errorf("cache layer data is missing or invalid")
// 			}

// 			// 再帰的にsetParameterを呼び出し、CacheLayerを取得
// 			layerParam, err := setParameter(layerData)
// 			if err != nil {
// 				return nil, err
// 			}

// 			// CacheLayerをスライスに格納
// 			param.(*cache.MultiCacheParameter).CacheLayers[i] = layerParam

// 		}

// 	default:
// 		return nil, fmt.Errorf("unknown parameter type: %s", paramType)
// 	}

// 	return param, nil
// }

// func (sr *SimulatorResult) UnmarshalBSON(data []byte) error {
// 	// Alias 型を使って無限再帰を避けつつ構造体をデコードする
// 	type Alias SimulatorResult
// 	aux := &struct {
// 		Parameter bson.M `bson:"parameter"` // Parameter フィールドは一時的に bson.M として受け取る
// 		*Alias
// 	}{
// 		Alias: (*Alias)(sr),
// 	}

// 	// BSONデータ全体をデコード
// 	if err := bson.Unmarshal(data, aux); err != nil {
// 		return err
// 	}

// 	// Parameter を適切な型に変換
// 	param, err := setParameter(aux.Parameter)
// 	if err != nil {
// 		return err
// 	}

// 	// デバッグ用ログ
// 	fmt.Printf("Decoded other fields: %+v\n", aux.Alias)
// 	fmt.Printf("Decoded Parameter: %+v\n", param)

// 	// デコードした Parameter を SimulatorResult にセット
// 	sr.Parameter = param

// 	return nil
// }
