package cache

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
}

// FullAssociativeParameter 構造体
type FullAssociativeParameter struct {
	Type string
	Size uint
}

func (p *FullAssociativeParameter) GetParameterType() string {
	return p.Type
}

// NbitFullAssociativeParameter 構造体
type NbitFullAssociativeParameter struct {
	Type    string
	Size    uint
	Refbits uint8
}

func (p *NbitFullAssociativeParameter) GetParameterType() string {
	return p.Type
}

// SetAssociativeParameter 構造体
type SetAssociativeParameter struct {
	Type string
	Size uint
	Way  uint
}

func (p *SetAssociativeParameter) GetParameterType() string {
	return p.Type
}

// NbitSetAssociativeParameter 構造体
type NbitSetAssociativeParameter struct {
	Type    string
	Size    uint
	Way     uint
	Refbits uint8
}

func (p *NbitSetAssociativeParameter) GetParameterType() string {
	return p.Type
}

type MultiCacheParameter struct {
	Type          string
	CacheLayers   []Parameter
	CachePolicies []CachePolicy
}

func (p *MultiCacheParameter) GetParameterType() string {
	return p.Type
}

type StatDetail interface{}
