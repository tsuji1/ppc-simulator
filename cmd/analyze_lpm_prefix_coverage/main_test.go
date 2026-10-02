package main

import "testing"

func TestDistinctPrefixesCountRoutingEntriesOnce(t *testing.T) {
	a := newAccumulator([]uint64{2, 4})
	a.observe(prefixKey{network: 0x0a000000, length: 8})
	a.observe(prefixKey{network: 0x0a000000, length: 8})
	a.observe(prefixKey{network: 0x0a010000, length: 16})
	a.observe(prefixKey{network: 0x0a020000, length: 16})
	a.finish()
	if len(a.snapshots) != 2 {
		t.Fatalf("snapshots=%d want=2", len(a.snapshots))
	}
	if got := a.snapshots[0].distinct[8]; got != 1 {
		t.Fatalf("first /8 distinct=%d want=1", got)
	}
	if got := a.snapshots[1].distinct[16]; got != 2 {
		t.Fatalf("final /16 distinct=%d want=2", got)
	}
	if a.snapshots[1].counts[8] != 2 || a.snapshots[1].counts[16] != 2 {
		t.Fatalf("packet counts=%v", a.snapshots[1].counts)
	}
}

func TestSameNetworkDifferentLengthsAreDistinct(t *testing.T) {
	a := newAccumulator(nil)
	a.observe(prefixKey{network: 0, length: 0})
	a.observe(prefixKey{network: 0, length: 1})
	a.finish()
	if len(a.prefixHits) != 2 {
		t.Fatalf("distinct=%d want=2", len(a.prefixHits))
	}
}

func TestMatcherReturnsExactLongAndShortPrefix(t *testing.T) {
	m := &matcher{by24: make([]uint8, 1<<24)}
	m.by24[0xc00002] = 24
	m.longer[25] = map[uint32]struct{}{0xc0000280: {}}
	m.longLengths = []int{25}
	if got := m.match(0xc0000281); got != (prefixKey{network: 0xc0000280, length: 25}) {
		t.Fatalf("long match=%v", got)
	}
	if got := m.match(0xc0000201); got != (prefixKey{network: 0xc0000200, length: 24}) {
		t.Fatalf("short match=%v", got)
	}
}

func TestCheckpointsAreSortedDeduplicatedAndCapped(t *testing.T) {
	got, err := parseCheckpoints("100,10,100,1000", 100)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0] != 10 || got[1] != 100 {
		t.Fatalf("checkpoints=%v", got)
	}
}
