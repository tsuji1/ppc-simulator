package cache

import "testing"

func TestUnifiedCacheTagLengthIPv4Boundaries(t *testing.T) {
	rt := newTestRoutingTable(t, "128.0.0.0 1 192.0.2.1\n10.0.0.0 24 192.0.2.2\n10.0.0.17 32 192.0.2.3\n")
	shortA := &FiveTuple{DstIP: 0x80000001, IsLeafIndex: 1}
	shortB := &FiveTuple{DstIP: 0x80004001, IsLeafIndex: 1}
	host := &FiveTuple{DstIP: 0x0a000011, IsLeafIndex: 32}
	neighbor := &FiveTuple{DstIP: 0x0a000012, IsLeafIndex: 31}

	for _, tc := range []struct {
		name       string
		index      int
		tags       [2]int
		shortAlias bool
		hostHit    bool
	}{
		{"direct baseline", 118, [2]int{9, 24}, false, false},
		{"direct expanded", 118, [2]int{1, 32}, false, true},
		{"ideal-entry expanded", CACHE_INDEX_TYPE_IDEAL_ENTRY, [2]int{1, 32}, true, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := NewUnifiedCache(64, 8, rt, tc.index, [][2]int{tc.tags}, UnifiedCacheInsertionPolicyExclusive, false)
			c.CacheFiveTuple(shortA)
			if hit, _ := c.IsCachedWithFiveTuple(shortB, true); hit != tc.shortAlias {
				t.Fatalf("another address in /1: hit=%t, want %t", hit, tc.shortAlias)
			}

			length, network, ok := c.EntryKey(host)
			if ok != tc.hostHit || (ok && (length != 32 || network != host.DstIP)) {
				t.Fatalf("host entry key = /%d network %08x ok=%t", length, network, ok)
			}
			if hit, _ := c.IsCachedWithFiveTuple(host, true); hit {
				t.Fatal("unexpected cold host hit")
			}
			c.CacheFiveTuple(host)
			if hit, _ := c.IsCachedWithFiveTuple(host, true); hit != tc.hostHit {
				t.Fatalf("repeated host: hit=%t, want %t", hit, tc.hostHit)
			}
			if hit, _ := c.IsCachedWithFiveTuple(neighbor, true); hit {
				t.Fatal("/32 entry matched a different address")
			}
			stats := c.Stat().(UnifiedCacheStat)
			if tc.hostHit {
				set := c.PlacementSet(host, 32)
				if stats.CachelineHitCount[set][32] != 1 || stats.CachelineFirstMissCount[set][32] != 1 ||
					stats.WholeCacheFirstMissCount[32] != 1 {
					t.Fatalf("incorrect /32 hit or miss counters in set %d", set)
				}
			} else if len(stats.CachelineHitCount[0]) != 32 {
				t.Fatalf("baseline stats have %d columns, want 32", len(stats.CachelineHitCount[0]))
			}
		})
	}
}
