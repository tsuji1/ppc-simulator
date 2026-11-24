package cache

import "testing"

// CACHE_INDEX_TYPE_IDEAL_ENTRY は、挿入する entry の長さ（tag 9-24 なら clamp(leaf, 9, 24)）の prefix で index する。
func TestIdealEntryIndexUsesEntryLength(t *testing.T) {
	c := NewUnifiedCache(256, 8, newTestRoutingTable(t, "10.0.0.0 12 192.0.2.1\n"), CACHE_INDEX_TYPE_IDEAL_ENTRY,
		[][2]int{{9, 24}}, UnifiedCacheInsertionPolicyExclusive, false)
	tests := []struct {
		leaf int8
		want uint32 // index に使う prefix 長
	}{
		{leaf: 0, want: 9},
		{leaf: 5, want: 9},
		{leaf: 9, want: 9},
		{leaf: 12, want: 12},
		{leaf: 16, want: 16},
		{leaf: 20, want: 20},
		{leaf: 24, want: 24},
		{leaf: 30, want: 24},
	}
	for _, tt := range tests {
		f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a123456, IsLeafIndex: tt.leaf}
		got := c.setIdxForType(f, CACHE_INDEX_TYPE_IDEAL_ENTRY, false)
		want := c.hashSetIdx(f.DstIP>>(32-tt.want), false)
		if got != want {
			t.Errorf("leaf %d: set %d, want CRC(/%d) = %d", tt.leaf, got, tt.want, want)
		}
	}
}

// 9..15 の leaf の entry は、同じ leaf の中の別のアドレスでも同じ set で引ける（従来の ideal は /16 で index していた）。
func TestIdealEntryHitsAcrossShortLeaf(t *testing.T) {
	rt := "10.0.0.0 12 192.0.2.1\n"
	a := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000001, IsLeafIndex: 12} // 10.0.0.1
	b := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a0f0001, IsLeafIndex: 12} // 10.15.0.1（同じ /12、別の /16）

	entry := NewUnifiedCache(256, 8, newTestRoutingTable(t, rt), CACHE_INDEX_TYPE_IDEAL_ENTRY,
		[][2]int{{9, 24}}, UnifiedCacheInsertionPolicyExclusive, false)
	entry.CacheFiveTuple(a)
	if hit, _ := entry.IsCachedWithFiveTuple(b, true); !hit {
		t.Fatal("ideal-entry: 同じ /12 の別アドレスがミスした")
	}

	// 従来の ideal（2）は /16 で index するので、/16 の set が違えば同じ entry を引けない
	old := NewUnifiedCache(256, 8, newTestRoutingTable(t, rt), CACHE_INDEX_TYPE_IDEAL,
		[][2]int{{9, 24}}, UnifiedCacheInsertionPolicyExclusive, false)
	if old.setIdxForType(a, CACHE_INDEX_TYPE_IDEAL, false) == old.setIdxForType(b, CACHE_INDEX_TYPE_IDEAL, false) {
		t.Skip("選んだアドレスの /16 が同じ set に入る")
	}
	old.CacheFiveTuple(a)
	if hit, _ := old.IsCachedWithFiveTuple(b, true); hit {
		t.Fatal("ideal（2）: /16 の set が違うのにヒットした")
	}
}
