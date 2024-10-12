package simulator

import (
	"fmt"

	"test-module/cache"
)

// CacheSimulatorStat は、キャッシュシミュレータの統計情報を表します。
//
// type はキャッシュの種類
//
// parameter はキャッシュのパラメータ
//
// processed は処理されたパケット
//
// Hit はキャッシュヒット数を示します。
type CacheSimulatorStat struct {
	Type      string
	Parameter cache.Parameter
	Processed int
	Hit       int
}

// String は、CacheSimulatorStat の文字列形式を返します。
// JSON 形式で Type, Parameter, Processed, Hit, HitRate を含みます。
func (css CacheSimulatorStat) String() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"Parameter\": %s, \"Processed\": %v, \"Hit\": %v, \"HitRate\": %v}",
		css.Type, css.Parameter, css.Processed, css.Hit, float64(css.Hit)/float64(css.Processed))
}

// CacheSimulator インターフェースは、キャッシュシミュレータの基本的な機能を定義します。
// Process メソッドはパケットを処理し、キャッシュヒットしたかどうかを返します。
// GetStat メソッドは現在の統計情報を返します。
type CacheSimulator interface {
	Process(p *cache.Packet) (hit bool)
	GetStat() (stat CacheSimulatorStat)
}
