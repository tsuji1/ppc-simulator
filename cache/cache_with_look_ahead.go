package cache

import (
	"fmt"

	"go.mongodb.org/mongo-driver/bson"
)

type CacheWithLookAhead struct {
	InnerCache Cache
}

type CacheWithLookAheadParameter struct {
	Type       string
	InnerCache interface{}
}

func (c *CacheWithLookAheadParameter) GetParameterString() map[string]interface{} {
	return map[string]interface{}{
		"Type":       c.Type,
		"InnerCache": c.InnerCache,
	}
}
func (c *CacheWithLookAheadParameter) GetBson() bson.M {
	// InnerCacheがParameterインターフェースを実装しているか確認
	if param, ok := c.InnerCache.(Parameter); ok {
		// ParameterとしてBSONに変換
		return bson.M{
			"Type":       c.Type,
			"InnerCache": param.GetBson(),
		}
	}

	// InnerCacheがParameterインターフェースを実装していない場合はそのまま返す
	return bson.M{
		"Type":       c.Type,
		"InnerCache": c.InnerCache,
	}
}

func (c *CacheWithLookAheadParameter) GetParameterType() string {
	return c.Type
}

func (c *CacheWithLookAhead) StatString() string {
	return ""
}

func (c *CacheWithLookAhead) Stat() interface{} {
	return struct{}{}
}

func (c *CacheWithLookAhead) IsCached(p *Packet, update bool) (bool, *int) {
	return c.InnerCache.IsCached(p, update)
}

func (c *CacheWithLookAhead) IsCachedWithFiveTuple(f *FiveTuple, update bool) (bool, *int) {
	return c.InnerCache.IsCachedWithFiveTuple(f, update)
}

func (c *CacheWithLookAhead) CacheFiveTuple(f *FiveTuple) []*FiveTuple {
	evictedFiveTuples := c.InnerCache.CacheFiveTuple(f)

	if f.Proto == IP_TCP {
		swapped := (*f).SwapSrcAndDst()

		if cached, _ := c.InnerCache.IsCachedWithFiveTuple(&swapped, false); !cached {
			replaced_by_lookahead := c.InnerCache.CacheFiveTuple(&swapped)
			evictedFiveTuples = append(evictedFiveTuples, replaced_by_lookahead...)
		}
	}

	return evictedFiveTuples
}

func (c *CacheWithLookAhead) InvalidateFiveTuple(f *FiveTuple) {
	c.InnerCache.InvalidateFiveTuple(f)
}

func (c *CacheWithLookAhead) Clear() {
	c.InnerCache.Clear()
}

func (c *CacheWithLookAhead) Description() string {
	return "CacheWithLookAhead[" + c.InnerCache.Description() + "]"
}

func (c *CacheWithLookAhead) ParameterString() string {
	return fmt.Sprintf("{\"Type\": \"%s\", \"InnerCache\": %s}", c.Description(), c.InnerCache.ParameterString())
}

// Parameter メソッドで Parameter インターフェースを実装
func (c *CacheWithLookAhead) Parameter() Parameter {
	return &CacheWithLookAheadParameter{
		Type:       "LookAhead",
		InnerCache: nil,
	}
}
