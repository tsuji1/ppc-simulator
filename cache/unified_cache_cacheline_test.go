package cache

import (
	"fmt"
	"hash/crc32"
	"os"
	"path/filepath"
	"test-module/ipaddress"
	"test-module/routingtable"
	"testing"
)

func newTestRoutingTable(t *testing.T, rules string) *routingtable.RoutingTablePatriciaTrie {
	t.Helper()

	path := filepath.Join(t.TempDir(), "rules.txt")
	if err := os.WriteFile(path, []byte(rules), 0o644); err != nil {
		t.Fatal(err)
	}
	fp, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer fp.Close()

	routingTable := routingtable.NewRoutingTablePatriciaTrie()
	routingTable.ReadRule(fp)
	return routingTable
}

func TestUnifiedCacheLineExclusiveSlash32MissDoesNotPanic(t *testing.T) {
	line := NewUnifiedCacheLine(
		1,
		nil,
		CACHE_INDEX_TYPE_PREFIX18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
		0,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x0a000001,
		IsLeafIndex: 32,
	}

	hit, entry := line.IsCachedWithFiveTuple(f, true)
	if hit {
		t.Fatal("unexpected cache hit for empty line")
	}
	if entry != nil {
		t.Fatalf("unexpected entry index for miss: %v", *entry)
	}
}

func TestUnifiedCacheLineMissUsesSelectedCacheLength(t *testing.T) {
	line := NewUnifiedCacheLine(
		1,
		nil,
		CACHE_INDEX_TYPE_PREFIX18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
		0,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x0a000001,
		IsLeafIndex: 16,
	}

	line.IsCachedWithFiveTuple(f, true)
	if line.FirstMissCount[16] != 1 {
		t.Fatalf("FirstMissCount[16] = %d, want 1", line.FirstMissCount[16])
	}
}

func TestUnifiedCacheDirectPrefixIndexUsesPrefixBitsWithoutHash(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		8,
		&routingTable,
		CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE+16,
		[][2]int{
			{9, 24},
			{9, 24},
			{9, 24},
			{9, 24},
			{9, 24},
			{9, 24},
			{9, 24},
			{9, 24},
		},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x0a000001,
		IsLeafIndex: 16,
	}
	got := cache.setIdx(f)
	want := uint((f.DstIP >> 16) & 0x3)
	if got != want {
		t.Fatalf("setIdx = %d, want %d", got, want)
	}
}

func TestUnifiedCacheDirectPrefixAdversarialTraceHasLowerHitRateThanHash(t *testing.T) {
	const (
		capacity  = uint(16)
		way       = uint(2)
		prefixLen = 16
		rounds    = 10
	)

	setCount := capacity / way
	prefixesByHashSet := make(map[uint]uint32)
	for prefix := uint32(0); prefix < 1<<prefixLen && len(prefixesByHashSet) < 4; prefix += uint32(setCount) {
		hashSet := uint(crc32.ChecksumIEEE(uint32ToBytes(prefix))) % setCount
		if _, exists := prefixesByHashSet[hashSet]; !exists {
			prefixesByHashSet[hashSet] = prefix
		}
	}
	if len(prefixesByHashSet) != 4 {
		t.Fatalf("found %d distinct hash sets, want 4", len(prefixesByHashSet))
	}

	var rules string
	trace := make([]*FiveTuple, 0, len(prefixesByHashSet))
	for _, prefix := range prefixesByHashSet {
		rules += fmt.Sprintf("%d.%d.0.0 16 192.0.2.1\n", prefix>>8, prefix&0xff)
		trace = append(trace, &FiveTuple{
			Proto:       IP_TCP,
			DstIP:       prefix<<16 | 1,
			IsLeafIndex: prefixLen,
		})
	}

	routingTable := newTestRoutingTable(t, rules)
	newCache := func(indexType int) *UnifiedCache {
		return NewUnifiedCache(
			capacity,
			way,
			routingTable,
			indexType,
			[][2]int{{prefixLen, prefixLen}},
			UnifiedCacheInsertionPolicyExclusive,
			false,
		)
	}
	hashCache := newCache(prefixLen)
	directCache := newCache(CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE + prefixLen)

	hashSets := make(map[uint]struct{})
	for _, f := range trace {
		directSet := directCache.setIdx(f)
		if directSet != 0 {
			t.Fatalf("direct set = %d, want all adversarial prefixes in set 0", directSet)
		}
		hashSets[hashCache.setIdx(f)] = struct{}{}
	}
	if len(hashSets) != len(trace) {
		t.Fatalf("hash used %d distinct sets for %d prefixes", len(hashSets), len(trace))
	}

	run := func(cache *UnifiedCache) (hits int, accesses int) {
		for range rounds {
			for _, f := range trace {
				accesses++
				if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
					hits++
					continue
				}
				cache.CacheFiveTuple(f)
			}
		}
		return hits, accesses
	}

	hashHits, accesses := run(hashCache)
	directHits, directAccesses := run(directCache)
	if directAccesses != accesses {
		t.Fatalf("direct accesses = %d, hash accesses = %d", directAccesses, accesses)
	}
	hashRate := float64(hashHits) / float64(accesses)
	directRate := float64(directHits) / float64(accesses)

	if hashHits != 36 || directHits != 0 {
		t.Fatalf(
			"unexpected hits: hash=%d/%d (%.1f%%), direct=%d/%d (%.1f%%)",
			hashHits, accesses, hashRate*100,
			directHits, accesses, directRate*100,
		)
	}
	if hashRate-directRate < 0.15 {
		t.Fatalf("hash-direct hit-rate gap = %.1f points, want at least 15 points", (hashRate-directRate)*100)
	}
	t.Logf("hash=%.1f%% direct=%.1f%% gap=%.1f points", hashRate*100, directRate*100, (hashRate-directRate)*100)
}

func TestUnifiedCacheSlash16HashBeatsSlash16Lower8DirectAt1K4Way(t *testing.T) {
	const (
		capacity       = uint(1024)
		way            = uint(4)
		prefixLen      = 16
		sharedLower8   = uint32(42)
		wantedPrefixes = 8
		rounds         = 5
	)

	type routeCase struct {
		prefix16 uint32
		cidr     string
		nextHop  string
		packet   *FiveTuple
		hashSet  uint
	}

	setCount := capacity / way
	seenHashSets := make(map[uint]struct{})
	cases := make([]routeCase, 0, wantedPrefixes)
	for firstOctet := uint32(10); firstOctet < 256 && len(cases) < wantedPrefixes; firstOctet++ {
		prefix16 := firstOctet<<8 | sharedLower8
		hashSet := uint(crc32.ChecksumIEEE(uint32ToBytes(prefix16))) % setCount
		if _, exists := seenHashSets[hashSet]; exists {
			continue
		}
		seenHashSets[hashSet] = struct{}{}
		cases = append(cases, routeCase{
			prefix16: prefix16,
			cidr:     fmt.Sprintf("%d.%d.0.0/16", firstOctet, sharedLower8),
			nextHop:  fmt.Sprintf("192.0.2.%d", len(cases)+1),
			packet: &FiveTuple{
				Proto:       IP_TCP,
				DstIP:       prefix16<<16 | 1,
				IsLeafIndex: prefixLen,
			},
			hashSet: hashSet,
		})
	}
	if len(cases) != wantedPrefixes {
		t.Fatalf("found %d /16 prefixes with distinct CRC16 sets, want %d", len(cases), wantedPrefixes)
	}

	var rules string
	for _, tc := range cases {
		rules += fmt.Sprintf(
			"%d.%d.0.0 16 %s\n",
			tc.prefix16>>8,
			tc.prefix16&0xff,
			tc.nextHop,
		)
	}
	routingTable := newTestRoutingTable(t, rules)
	newCache := func(indexType int) *UnifiedCache {
		return NewUnifiedCache(
			capacity,
			way,
			routingTable,
			indexType,
			[][2]int{{prefixLen, prefixLen}},
			UnifiedCacheInsertionPolicyExclusive,
			false,
		)
	}
	hashCache := newCache(CACHE_INDEX_TYPE_HASH)
	directCache := newCache(CACHE_INDEX_TYPE_PREFIX_DIRECT_BASE + prefixLen)

	for _, tc := range cases {
		matchedPrefix, item := routingTable.SearchLongestIP(ipaddress.NewIPaddress(tc.packet.DstIP), 32)
		wantPrefix := ipaddress.NewIPaddress(tc.packet.DstIP).MaskedBitString(prefixLen)
		if matchedPrefix != wantPrefix {
			t.Fatalf("route lookup for %s returned prefix length %d, want /16", tc.cidr, len(matchedPrefix))
		}
		gotNextHop := item.(routingtable.Data).NextHop
		if gotNextHop != tc.nextHop {
			t.Fatalf("route lookup for %s returned next hop %s, want %s", tc.cidr, gotNextHop, tc.nextHop)
		}

		directSet := directCache.setIdx(tc.packet)
		if directSet != uint(sharedLower8) {
			t.Fatalf("direct set for %s = %d, want %d", tc.cidr, directSet, sharedLower8)
		}
		if gotHashSet := hashCache.setIdx(tc.packet); gotHashSet != tc.hashSet {
			t.Fatalf("CRC16 set for %s = %d, want %d", tc.cidr, gotHashSet, tc.hashSet)
		}
		t.Logf(
			"route %-14s -> nextHop %-11s | /16 lower8 direct set=%3d | CRC16 set=%3d",
			tc.cidr,
			gotNextHop,
			directSet,
			tc.hashSet,
		)
	}

	accessRound := func(cache *UnifiedCache) int {
		hits := 0
		for _, tc := range cases {
			if hit, _ := cache.IsCachedWithFiveTuple(tc.packet, true); hit {
				hits++
				continue
			}
			cache.CacheFiveTuple(tc.packet)
		}
		return hits
	}
	entriesInSet := func(cache *UnifiedCache, set uint) []string {
		entries := make([]string, 0, way)
		for _, tc := range cases {
			key := cache.Sets[set].entryKey(tc.packet.DstIP, prefixLen)
			if _, exists := cache.Sets[set].Entries[key]; exists {
				entries = append(entries, tc.cidr)
			}
		}
		return entries
	}

	hashHits := accessRound(hashCache)
	directHits := accessRound(directCache)
	if hashHits != 0 || directHits != 0 {
		t.Fatalf("cold round hits: CRC16=%d direct=%d, want both 0", hashHits, directHits)
	}

	directEntries := entriesInSet(directCache, uint(sharedLower8))
	if len(directEntries) != int(way) {
		t.Fatalf("direct set %d holds %d entries, want %d: %v", sharedLower8, len(directEntries), way, directEntries)
	}
	if len(hashCache.Sets[cases[0].hashSet].Entries) != 1 {
		t.Fatalf("CRC16 set %d entry count = %d, want 1", cases[0].hashSet, len(hashCache.Sets[cases[0].hashSet].Entries))
	}
	t.Logf("after cold round, direct set %d contains %v", sharedLower8, directEntries)
	for _, tc := range cases {
		t.Logf("after cold round, CRC16 set %d contains [%s]", tc.hashSet, tc.cidr)
	}

	directVictimHit, _ := directCache.IsCachedWithFiveTuple(cases[0].packet, false)
	hashVictimHit, _ := hashCache.IsCachedWithFiveTuple(cases[0].packet, false)
	if directVictimHit || !hashVictimHit {
		t.Fatalf(
			"second lookup for %s: direct hit=%t, CRC16 hit=%t; want false/true",
			cases[0].cidr,
			directVictimHit,
			hashVictimHit,
		)
	}
	t.Logf(
		"second lookup for %s: route still matches %s, direct set %d misses after eviction, CRC16 set %d hits",
		cases[0].cidr,
		cases[0].nextHop,
		sharedLower8,
		cases[0].hashSet,
	)

	for round := 1; round < rounds; round++ {
		hashHits += accessRound(hashCache)
		directHits += accessRound(directCache)
	}
	accesses := rounds * len(cases)
	if hashHits != 32 || directHits != 0 {
		t.Fatalf("unexpected hits: CRC16=%d/%d direct=%d/%d", hashHits, accesses, directHits, accesses)
	}
	t.Logf(
		"1K entries, 4-way, 5 rounds: CRC16=%d/%d (%.1f%%), /16 lower8 direct=%d/%d (%.1f%%)",
		hashHits,
		accesses,
		float64(hashHits)/float64(accesses)*100,
		directHits,
		accesses,
		float64(directHits)/float64(accesses)*100,
	)
}

func TestUnifiedCacheAllSlash24CRC24AvoidsDirect8AndCRC16Conflicts(t *testing.T) {
	const (
		capacity = uint(1024)
		way      = uint(4)
		rounds   = 5
	)

	setCount := capacity / way
	prefixesByCRC24Set := make(map[uint]uint32)
	for thirdOctet := uint32(0); thirdOctet < 256 && len(prefixesByCRC24Set) < 8; thirdOctet++ {
		prefix24 := uint32(10)<<16 | uint32(42)<<8 | thirdOctet
		set := uint(crc32.ChecksumIEEE(uint32ToBytes(prefix24))) % setCount
		if _, exists := prefixesByCRC24Set[set]; !exists {
			prefixesByCRC24Set[set] = prefix24
		}
	}
	if len(prefixesByCRC24Set) != 8 {
		t.Fatalf("found %d distinct CRC24 sets, want 8", len(prefixesByCRC24Set))
	}

	var rules string
	trace := make([]*FiveTuple, 0, len(prefixesByCRC24Set))
	for _, prefix24 := range prefixesByCRC24Set {
		rules += fmt.Sprintf("10.42.%d.0 24 192.0.2.1\n", prefix24&0xff)
		trace = append(trace, &FiveTuple{
			Proto:       IP_TCP,
			DstIP:       prefix24<<8 | 1,
			IsLeafIndex: 24,
		})
	}

	routingTable := newTestRoutingTable(t, rules)
	newCache := func(indexType int) *UnifiedCache {
		return NewUnifiedCache(
			capacity,
			way,
			routingTable,
			indexType,
			[][2]int{{24, 24}},
			UnifiedCacheInsertionPolicyExclusive,
			false,
		)
	}
	direct8Cache := newCache(CACHE_INDEX_TYPE_DIRECT)
	crc16Cache := newCache(CACHE_INDEX_TYPE_HASH)
	crc24Cache := newCache(CACHE_INDEX_TYPE_PREFIX24)

	direct8Sets := make(map[uint]struct{})
	crc16Sets := make(map[uint]struct{})
	crc24Sets := make(map[uint]struct{})
	for _, f := range trace {
		direct8Sets[direct8Cache.setIdx(f)] = struct{}{}
		crc16Sets[crc16Cache.setIdx(f)] = struct{}{}
		crc24Sets[crc24Cache.setIdx(f)] = struct{}{}
	}
	if len(direct8Sets) != 1 || len(crc16Sets) != 1 || len(crc24Sets) != len(trace) {
		t.Fatalf(
			"unexpected set distribution: direct8=%d CRC16=%d CRC24=%d for %d /24 prefixes",
			len(direct8Sets), len(crc16Sets), len(crc24Sets), len(trace),
		)
	}

	run := func(cache *UnifiedCache) (hits int, accesses int) {
		for range rounds {
			for _, f := range trace {
				accesses++
				if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
					hits++
					continue
				}
				cache.CacheFiveTuple(f)
			}
		}
		return hits, accesses
	}

	direct8Hits, accesses := run(direct8Cache)
	crc16Hits, crc16Accesses := run(crc16Cache)
	crc24Hits, crc24Accesses := run(crc24Cache)
	if crc16Accesses != accesses || crc24Accesses != accesses {
		t.Fatalf("access counts differ: direct8=%d CRC16=%d CRC24=%d", accesses, crc16Accesses, crc24Accesses)
	}
	if direct8Hits != 0 || crc16Hits != 0 || crc24Hits != 32 {
		t.Fatalf(
			"unexpected hits: direct8=%d/%d CRC16=%d/%d CRC24=%d/%d",
			direct8Hits, accesses, crc16Hits, accesses, crc24Hits, accesses,
		)
	}
	t.Logf(
		"all-/24 adversarial trace: direct8=%.1f%% CRC16=%.1f%% CRC24=%.1f%%",
		float64(direct8Hits)/float64(accesses)*100,
		float64(crc16Hits)/float64(accesses)*100,
		float64(crc24Hits)/float64(accesses)*100,
	)
}

func TestUnifiedCacheDirectWindowIndexUsesSelectedDstIPBitsWithoutHash(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		4,
		&routingTable,
		CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE+8*cacheIndexTypeWindowStride+16,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x12345678,
		IsLeafIndex: 16,
	}
	got := cache.setIdx(f)
	want := uint(0x3456 & 0x7)
	if got != want {
		t.Fatalf("setIdx = %d, want %d", got, want)
	}
}

func TestUnifiedCacheXorWindowIndexFoldsSelectedDstIPBits(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		4,
		&routingTable,
		CACHE_INDEX_TYPE_WINDOW_XOR_BASE+8*cacheIndexTypeWindowStride+16,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x12345678,
		IsLeafIndex: 16,
	}
	got := cache.setIdx(f)
	want := uint(0x2)
	if got != want {
		t.Fatalf("setIdx = %d, want %d", got, want)
	}
}

func TestUnifiedCacheCRCWindowIndexHashesSelectedDstIPBits(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		4,
		&routingTable,
		CACHE_INDEX_TYPE_WINDOW_CRC_BASE+8*cacheIndexTypeWindowStride+16,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x12345678,
		IsLeafIndex: 16,
	}
	got := cache.setIdx(f)
	want := uint(crc32.ChecksumIEEE(uint32ToBytes(0x3456))) % (cache.Size / cache.Way)
	if got != want {
		t.Fatalf("setIdx = %d, want %d", got, want)
	}
}

func TestUnifiedCacheWindowIndexRejectsInvalidWindow(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		4,
		&routingTable,
		CACHE_INDEX_TYPE_WINDOW_DIRECT_BASE+8*cacheIndexTypeWindowStride+33,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	defer func() {
		if recover() == nil {
			t.Fatal("expected panic for invalid window CacheIndexType")
		}
	}()
	cache.setIdx(&FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x12345678,
		IsLeafIndex: 16,
	})
}

func TestNewUnifiedCacheAllowsCompactTagLengthFor16Way(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		16,
		&routingTable,
		CACHE_INDEX_TYPE_PREFIX18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	if cache.Way != 16 {
		t.Fatalf("Way = %d, want 16", cache.Way)
	}
	if len(cache.Sets) != 2 {
		t.Fatalf("len(Sets) = %d, want 2", len(cache.Sets))
	}
}

func TestNewUnifiedCacheAllowsFullAssociativeCompactTagLength(t *testing.T) {
	routingTable := routingtable.RoutingTablePatriciaTrie{}
	cache := NewUnifiedCache(
		32,
		32,
		&routingTable,
		CACHE_INDEX_TYPE_PREFIX18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	if cache.Way != 32 {
		t.Fatalf("Way = %d, want 32", cache.Way)
	}
	if len(cache.Sets) != 1 {
		t.Fatalf("len(Sets) = %d, want 1", len(cache.Sets))
	}
}

func TestUnifiedCacheInclusiveCachesOverlappingPrefixesAndUsesLongestMatch(t *testing.T) {
	routingTable := newTestRoutingTable(t, ""+
		"127.0.0.0 8 192.0.2.8\n"+
		"127.0.0.0 24 192.0.2.24\n")
	cache := NewUnifiedCache(
		2,
		2,
		routingTable,
		CACHE_INDEX_TYPE_DIRECT,
		[][2]int{{8, 24}},
		UnifiedCacheInsertionPolicyInclusive,
		false,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x7f000001,
		IsLeafIndex: 24,
	}
	cache.CacheFiveTuple(f)

	line := &cache.Sets[0]
	if len(line.Entries) != 2 {
		t.Fatalf("len(Entries) = %d, want 2", len(line.Entries))
	}
	if _, ok := line.Entries[line.entryKey(f.DstIP, 8)]; !ok {
		t.Fatal("missing cached 127.0.0.0/8 entry")
	}
	if _, ok := line.Entries[line.entryKey(f.DstIP, 24)]; !ok {
		t.Fatal("missing cached 127.0.0.0/24 entry")
	}

	hit, _ := cache.IsCachedWithFiveTuple(f, true)
	if !hit {
		t.Fatal("expected cache hit")
	}
	if line.HitCount[24] != 1 {
		t.Fatalf("HitCount[24] = %d, want 1", line.HitCount[24])
	}
	if line.HitCount[8] != 0 {
		t.Fatalf("HitCount[8] = %d, want 0", line.HitCount[8])
	}
}

func TestUnifiedCacheInclusiveEvictingSpecificPrefixEvictsAncestor(t *testing.T) {
	routingTable := newTestRoutingTable(t, ""+
		"127.0.0.0 8 192.0.2.8\n"+
		"127.0.0.0 24 192.0.2.24\n"+
		"10.0.0.0 8 192.0.2.10\n")
	cache := NewUnifiedCache(
		2,
		2,
		routingTable,
		CACHE_INDEX_TYPE_DIRECT,
		[][2]int{{8, 24}},
		UnifiedCacheInsertionPolicyInclusive,
		false,
	)

	specific := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x7f000001,
		IsLeafIndex: 24,
	}
	cache.CacheFiveTuple(specific)

	ancestorOnly := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x7f010001,
		IsLeafIndex: 8,
	}
	if hit, _ := cache.IsCachedWithFiveTuple(ancestorOnly, true); !hit {
		t.Fatal("expected /8 hit before eviction")
	}

	replacement := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x0a000001,
		IsLeafIndex: 8,
	}
	cache.CacheFiveTuple(replacement)

	line := &cache.Sets[0]
	if _, ok := line.Entries[line.entryKey(specific.DstIP, 24)]; ok {
		t.Fatal("specific /24 entry remained cached after eviction")
	}
	if _, ok := line.Entries[line.entryKey(specific.DstIP, 8)]; ok {
		t.Fatal("ancestor /8 entry remained cached after /24 eviction")
	}
	if hit, _ := cache.IsCachedWithFiveTuple(ancestorOnly, false); hit {
		t.Fatal("unexpected /8 fallback hit after /24 eviction")
	}
	if _, ok := line.Entries[line.entryKey(replacement.DstIP, 8)]; !ok {
		t.Fatal("replacement /8 entry was not cached")
	}
}

func TestUnifiedCacheExclusiveDoesNotCacheOverlappingPrefixes(t *testing.T) {
	routingTable := newTestRoutingTable(t, ""+
		"127.0.0.0 8 192.0.2.8\n"+
		"127.0.0.0 24 192.0.2.24\n")
	cache := NewUnifiedCache(
		2,
		2,
		routingTable,
		CACHE_INDEX_TYPE_DIRECT,
		[][2]int{{8, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		false,
	)

	f := &FiveTuple{
		Proto:       IP_TCP,
		DstIP:       0x7f000001,
		IsLeafIndex: 24,
	}
	cache.CacheFiveTuple(f)

	line := &cache.Sets[0]
	if len(line.Entries) != 1 {
		t.Fatalf("len(Entries) = %d, want 1", len(line.Entries))
	}
	if _, ok := line.Entries[line.entryKey(f.DstIP, 24)]; !ok {
		t.Fatal("exclusive policy should cache only the selected /24 entry")
	}
}

func newAdaptiveUnifiedCache(t *testing.T, rules string, tagLength [2]int) *UnifiedCache {
	t.Helper()
	return NewUnifiedCacheWithIndexConfig(
		32,
		4,
		newTestRoutingTable(t, rules),
		18,
		[][2]int{tagLength},
		UnifiedCacheInsertionPolicyExclusive,
		UnifiedCacheIndexConfig{
			Policy:  UnifiedCacheIndexPolicyLastInserted,
			Initial: 18,
			Min:     6,
			Max:     24,
		},
		false,
	)
}

func TestUnifiedCacheAdaptiveUsesInsertedPrefixForNextLookup(t *testing.T) {
	cache := newAdaptiveUnifiedCache(t, "10.0.0.0 22 192.0.2.1\n", [2]int{9, 24})
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000101, IsLeafIndex: 22}

	if hit, _ := cache.IsCachedWithFiveTuple(f, true); hit {
		t.Fatal("unexpected initial hit")
	}
	cache.CacheFiveTuple(f)
	if cache.ActiveIndexLen != 22 {
		t.Fatalf("ActiveIndexLen = %d, want 22", cache.ActiveIndexLen)
	}
	if hit, _ := cache.IsCachedWithFiveTuple(f, true); !hit {
		t.Fatal("expected hit using the learned /22 index")
	}
	if cache.AdaptiveLookupCount[18] != 1 || cache.AdaptiveLookupCount[22] != 1 {
		t.Fatalf("lookup counts /18=%d /22=%d, want 1 and 1", cache.AdaptiveLookupCount[18], cache.AdaptiveLookupCount[22])
	}
	if cache.AdaptiveSelectionCount[22] != 1 || cache.AdaptiveSwitchCount != 1 {
		t.Fatalf("selection /22=%d switches=%d, want 1 and 1", cache.AdaptiveSelectionCount[22], cache.AdaptiveSwitchCount)
	}
	stat := cache.Stat().(UnifiedCacheStat)
	if stat.AdaptiveFinalIndexLength != 22 || stat.AdaptiveSwitchCount != 1 {
		t.Fatalf("stat final=%d switches=%d, want 22 and 1", stat.AdaptiveFinalIndexLength, stat.AdaptiveSwitchCount)
	}
}

func TestUnifiedCacheAdaptiveClampsInsertedPrefix(t *testing.T) {
	tests := []struct {
		name       string
		rule       string
		tagLength  [2]int
		leafLength int8
		want       int
	}{
		{name: "lower", rule: "8.0.0.0 5 192.0.2.1\n", tagLength: [2]int{5, 5}, leafLength: 5, want: 6},
		{name: "upper", rule: "10.0.0.0 30 192.0.2.1\n", tagLength: [2]int{30, 30}, leafLength: 30, want: 24},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cache := newAdaptiveUnifiedCache(t, tt.rule, tt.tagLength)
			f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000001, IsLeafIndex: tt.leafLength}
			if tt.leafLength == 5 {
				f.DstIP = 0x08000001
			}
			cache.CacheFiveTuple(f)
			if cache.ActiveIndexLen != tt.want {
				t.Fatalf("ActiveIndexLen = %d, want %d", cache.ActiveIndexLen, tt.want)
			}
		})
	}
}

func TestUnifiedCacheAdaptiveRejectedMissDoesNotChangeIndex(t *testing.T) {
	cache := newAdaptiveUnifiedCache(t, "10.0.0.0 30 192.0.2.1\n", [2]int{9, 24})
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000001, IsLeafIndex: 30}

	cache.CacheFiveTuple(f)
	if cache.ActiveIndexLen != 18 {
		t.Fatalf("ActiveIndexLen = %d, want initial 18", cache.ActiveIndexLen)
	}
	if cache.AdaptiveSwitchCount != 0 {
		t.Fatalf("AdaptiveSwitchCount = %d, want 0", cache.AdaptiveSwitchCount)
	}
}

func TestUnifiedCacheAdaptiveDoesNotMoveOldEntries(t *testing.T) {
	cache := newAdaptiveUnifiedCache(t, "10.0.0.0 22 192.0.2.1\n", [2]int{9, 24})
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000101, IsLeafIndex: 22}
	cache.CacheFiveTuple(f)

	cache.ActiveIndexLen = 18
	if cache.setIdx(f) == func() uint { cache.ActiveIndexLen = 22; return cache.setIdx(f) }() {
		t.Skip("selected address maps /18 and /22 to the same set")
	}
	cache.ActiveIndexLen = 18
	if hit, _ := cache.IsCachedWithFiveTuple(f, false); hit {
		t.Fatal("unexpected hit through the old /18 index")
	}
	cache.ActiveIndexLen = 22
	if hit, _ := cache.IsCachedWithFiveTuple(f, false); !hit {
		t.Fatal("expected entry to remain in its original /22-indexed set")
	}
}

func TestUnifiedCacheAdaptiveRejectsInclusiveInsertion(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected adaptive+inclusive configuration to panic")
		}
	}()
	NewUnifiedCacheWithIndexConfig(
		8,
		2,
		&routingtable.RoutingTablePatriciaTrie{},
		18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyInclusive,
		UnifiedCacheIndexConfig{Policy: UnifiedCacheIndexPolicyLastInserted, Initial: 18, Min: 6, Max: 24},
		false,
	)
}

func TestUnifiedCacheParameterOnlyPersistsAdaptiveIdentityForAdaptivePolicy(t *testing.T) {
	fixed := UnifiedCacheParameter{IndexPolicy: UnifiedCacheIndexPolicyFixed}.GetBson()
	if _, ok := fixed["indexpolicy"]; ok {
		t.Fatal("fixed parameter unexpectedly contains adaptive identity")
	}

	adaptive := UnifiedCacheParameter{
		IndexPolicy:     UnifiedCacheIndexPolicyLastInserted,
		AdaptiveInitial: 18,
		AdaptiveMin:     6,
		AdaptiveMax:     24,
	}.GetBson()
	if adaptive["indexpolicy"] != UnifiedCacheIndexPolicyLastInserted {
		t.Fatalf("indexpolicy = %v, want %q", adaptive["indexpolicy"], UnifiedCacheIndexPolicyLastInserted)
	}
}

func newEpochUnifiedCache(t *testing.T, epochLength int) *UnifiedCache {
	t.Helper()
	return NewUnifiedCacheWithIndexConfig(
		32,
		4,
		newTestRoutingTable(t, "10.0.0.0 24 192.0.2.1\n"),
		18,
		[][2]int{{9, 24}},
		UnifiedCacheInsertionPolicyExclusive,
		UnifiedCacheIndexConfig{
			Policy:      UnifiedCacheIndexPolicyEpochFrequent,
			Initial:     18,
			Min:         6,
			Max:         24,
			EpochLength: epochLength,
		},
		false,
	)
}

func TestUnifiedCacheEpochAppliesDecisionBeforeNextLookup(t *testing.T) {
	cache := newEpochUnifiedCache(t, 4)
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000001, IsLeafIndex: 24}

	for i := 0; i < 4; i++ {
		cache.IsCachedWithFiveTuple(f, true)
		if i < 2 {
			cache.recordAdaptiveEpochObservation(20)
		}
		if cache.ActiveIndexLen != 18 {
			t.Fatalf("access %d used index /%d, want /18", i+1, cache.ActiveIndexLen)
		}
	}
	cache.IsCachedWithFiveTuple(f, true)
	if cache.ActiveIndexLen != 20 {
		t.Fatalf("fifth access used index /%d, want /20", cache.ActiveIndexLen)
	}
	if cache.AdaptiveCompletedEpochs != 1 || cache.AdaptiveEpochAccessCount != 1 {
		t.Fatalf("completed=%d current accesses=%d, want 1 and 1", cache.AdaptiveCompletedEpochs, cache.AdaptiveEpochAccessCount)
	}
	if cache.AdaptiveEpochDecisionCount[20] != 1 || cache.AdaptiveSwitchCount != 1 {
		t.Fatalf("decisions /20=%d switches=%d, want 1 and 1", cache.AdaptiveEpochDecisionCount[20], cache.AdaptiveSwitchCount)
	}
}

func TestUnifiedCacheEpochTieBreaking(t *testing.T) {
	t.Run("current wins", func(t *testing.T) {
		cache := newEpochUnifiedCache(t, 4)
		cache.recordAdaptiveEpochObservation(18)
		cache.recordAdaptiveEpochObservation(20)
		selected, ok := cache.selectAdaptiveEpochIndex()
		if !ok || selected != 18 {
			t.Fatalf("selected=%d ok=%v, want current /18", selected, ok)
		}
	})
	t.Run("nearest then shorter", func(t *testing.T) {
		cache := newEpochUnifiedCache(t, 4)
		cache.recordAdaptiveEpochObservation(17)
		cache.recordAdaptiveEpochObservation(19)
		selected, ok := cache.selectAdaptiveEpochIndex()
		if !ok || selected != 17 {
			t.Fatalf("selected=%d ok=%v, want shorter equidistant /17", selected, ok)
		}
	})
}

func TestUnifiedCacheEpochEmptyEpochKeepsCurrentIndex(t *testing.T) {
	cache := newEpochUnifiedCache(t, 1)
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000001, IsLeafIndex: 24}
	cache.IsCachedWithFiveTuple(f, true)
	cache.IsCachedWithFiveTuple(f, true)
	if cache.ActiveIndexLen != 18 || cache.AdaptiveSwitchCount != 0 {
		t.Fatalf("active=/%d switches=%d, want /18 and 0", cache.ActiveIndexLen, cache.AdaptiveSwitchCount)
	}
	if cache.AdaptiveCompletedEpochs != 1 {
		t.Fatalf("completed epochs=%d, want 1", cache.AdaptiveCompletedEpochs)
	}
}

func TestUnifiedCacheEpochRejectedMissIsNotObserved(t *testing.T) {
	cache := newEpochUnifiedCache(t, 4)
	f := &FiveTuple{Proto: IP_TCP, DstIP: 0x0a000001, IsLeafIndex: 30}
	cache.CacheFiveTuple(f)
	for length, count := range cache.AdaptiveEpochObservationCount {
		if count != 0 {
			t.Fatalf("observation /%d=%d after rejected miss, want 0", length, count)
		}
	}
}

func TestUnifiedCacheEpochParameterIncludesEpochLength(t *testing.T) {
	parameter := UnifiedCacheParameter{
		IndexPolicy:         UnifiedCacheIndexPolicyEpochFrequent,
		AdaptiveInitial:     18,
		AdaptiveMin:         6,
		AdaptiveMax:         24,
		AdaptiveEpochLength: 1024,
	}.GetBson()
	if parameter["adaptiveepochlength"] != 1024 {
		t.Fatalf("adaptiveepochlength=%v, want 1024", parameter["adaptiveepochlength"])
	}
}
