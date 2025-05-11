package cache

import "go.mongodb.org/mongo-driver/bson"

// Cache インターフェースは、キャッシュの基本的な操作を定義します。
type Cache interface {
	// IsCached は、パケットがキャッシュに存在するかをチェックします。
	// update フラグが true の場合、アクセス時間を更新します。
	// キャッシュヒットの場合は true とキャッシュ内の位置を返します。
	IsCached(p *Packet, update bool) (bool, *int)

	// IsCachedWithFiveTuple は、FiveTuple がキャッシュに存在するかをチェックします。
	// update フラグが true の場合、アクセス時間を更新します。
	// キャッシュヒットの場合は true とキャッシュ内の位置を返します。
	IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int)

	// CacheFiveTuple は、FiveTuple をキャッシュに追加します。
	// キャッシュに追加された FiveTuple のスライスを返します。
	CacheFiveTuple(f *FiveTuple) []*FiveTuple

	// InvalidateFiveTuple は、FiveTuple をキャッシュから無効にします。
	InvalidateFiveTuple(f *FiveTuple)

	// Clear は、キャッシュをクリアします。
	Clear()

	// StatString は、キャッシュの統計情報を文字列で返します。
	StatString() string

	// Description は、キャッシュの説明を返します。
	Description() string

	// ParameterString は、キャッシュのパラメータを文字列で返します。
	ParameterString() string

	Parameter() Parameter

	Stat() interface{}
}

// AccessCache は、キャッシュにパケットをアクセスさせ、キャッシュヒットしたかどうかを返します。
// update フラグは true に設定されています。
func AccessCache(c Cache, p *Packet) bool {
	hit, _ := c.IsCached(p, true)
	return hit
}

// Parameter インターフェース
type Parameter interface {
	GetParameterType() string
	GetParameterString() map[string]interface{}
	GetBson() bson.M
}

// FullAssociativeParameter 構造体
type FullAssociativeParameter struct {
	Type string
	Size uint
}

// NbitFullAssociativeParameter 構造体
type NbitFullAssociativeParameter struct {
	Type    string
	Size    uint
	Refbits uint8
}

// SetAssociativeParameter 構造体
type SetAssociativeParameter struct {
	Type string
	Size uint
	Way  uint
}

// NbitSetAssociativeParameter 構造体
type NbitSetAssociativeParameter struct {
	Type    string
	Size    int
	Way     int
	Refbits int
}

type MultiCacheParameter struct {
	Type          string
	CacheLayers   []Parameter
	CachePolicies []CachePolicy
}
type InclusiveCacheParameter struct {
	Type          string
	CacheLayers   []Parameter
	CachePolicies []CachePolicy
	OnceCacheLimit int
}

// FullAssociativeParameter の GetParameterString 実装
func (p FullAssociativeParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type": p.Type,
		"Size": p.Size,
	}
}

// NbitFullAssociativeParameter の GetParameterString 実装
func (p NbitFullAssociativeParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type":    p.Type,
		"Size":    p.Size,
		"Refbits": p.Refbits,
	}
}

// SetAssociativeParameter の GetParameterString 実装
func (p SetAssociativeParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type": p.Type,
		"Size": p.Size,
		"Way":  p.Way,
	}
}

// NbitSetAssociativeParameter の GetParameterString 実装
func (p NbitSetAssociativeParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type":    p.Type,
		"Size":    p.Size,
		"Way":     p.Way,
		"Refbits": p.Refbits,
	}
}

// MultiCacheParameter の GetParameterString 実装
func (p MultiCacheParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type":          p.Type,
		"CacheLayers":   p.CacheLayers,
		"CachePolicies": p.CachePolicies,
	}
}

// MultiCacheParameter の GetParameterString 実装
func (p InclusiveCacheParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type":          p.Type,
		"CacheLayers":   p.CacheLayers,
		"CachePolicies": p.CachePolicies,
		"OnceCacheLimit": p.OnceCacheLimit,
	}
}
// FullAssociativeParameter の GetBson 実装
func (p FullAssociativeParameter) GetBson() bson.M {
	return bson.M{
		"type": p.Type,
		"size": p.Size,
	}
}

// NbitFullAssociativeParameter の GetBson 実装
func (p NbitFullAssociativeParameter) GetBson() bson.M {
	return bson.M{
		"type":    p.Type,
		"size":    p.Size,
		"refbits": p.Refbits,
	}
}

// SetAssociativeParameter の GetBson 実装
func (p SetAssociativeParameter) GetBson() bson.M {
	return bson.M{
		"type": p.Type,
		"size": p.Size,
		"way":  p.Way,
	}
}

// NbitSetAssociativeParameter の GetBson 実装
func (p NbitSetAssociativeParameter) GetBson() bson.M {
	return bson.M{
		"type":    p.Type,
		"size":    p.Size,
		"way":     p.Way,
		"refbits": p.Refbits,
	}
}

// MultiCacheParameter の GetBson 実装
func (p MultiCacheParameter) GetBson() bson.M {
	cacheLayers := make([]bson.M, len(p.CacheLayers))
	for i, layer := range p.CacheLayers {
		if param, ok := layer.(Parameter); ok {
			cacheLayers[i] = param.GetBson()
		}
	}
	return bson.M{
		"type":          p.GetParameterType(),
		"cachelayers":   cacheLayers,
		"cachepolicies": p.CachePolicies,
	}
}

func (p *MultiCacheParameter) GetParameterType() string {
	name := GetMultiLayerParameterTypeName(p.Type, p.CacheLayers)
	return name
}

// MultiCacheParameter の GetBson 実装
func (p InclusiveCacheParameter) GetBson() bson.M {
	cacheLayers := make([]bson.M, len(p.CacheLayers))
	for i, layer := range p.CacheLayers {
		if param, ok := layer.(Parameter); ok {
			cacheLayers[i] = param.GetBson()
		}
	}
	return bson.M{
		"type":          p.GetParameterType(),
		"cachelayers":   cacheLayers,
		"cachepolicies": p.CachePolicies,
		"oncecachelimit": p.OnceCacheLimit, 
	}
}

func (p *InclusiveCacheParameter) GetParameterType() string {
	name := GetMultiLayerParameterTypeName(p.Type, p.CacheLayers)
	return name
}


func (p *NbitFullAssociativeParameter) GetParameterType() string {
	return p.Type
}
func (p *SetAssociativeParameter) GetParameterType() string {
	return p.Type
}

func GetMultiLayerParameterTypeName(typeMultiCache string, cacheLayers []Parameter) string {
	parameterName := typeMultiCache + "["
	lenCache := len(cacheLayers)
	for i, layer := range cacheLayers {
		parameterName = parameterName + layer.GetParameterType()
		if i != lenCache-1 {
			parameterName = parameterName + ", "
		}
	}
	parameterName = parameterName + "]"
	return parameterName
}
func (p *FullAssociativeParameter) GetParameterType() string {
	return p.Type
}
func (p *NbitSetAssociativeParameter) GetParameterType() string {
	return p.Type
}

type StatDetail interface{}
