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
}

// AccessCache は、キャッシュにパケットをアクセスさせ、キャッシュヒットしたかどうかを返します。
// update フラグは true に設定されています。
func AccessCache(c Cache, p *Packet) bool {
	hit, _ := c.IsCached(p, true)
	return hit
}
