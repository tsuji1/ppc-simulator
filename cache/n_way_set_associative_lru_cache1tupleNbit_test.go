package cache

import "testing"

func newTestMPLayer(refbits, size, way uint, index string) *NWaySetAssociativeDstipNbitLRUCache {
	c := NewNWaySetAssociativeDstipNbitLRUCache(refbits, size, way, nil, false, nil, 0)
	c.Index = index
	return c
}

func TestMPDirectIndexUsesLowBitsOfKey(t *testing.T) {
	// /18, 4096 entries, 8-way -> 512 sets (9 bits): index = bits 10..18 of the address.
	c := newTestMPLayer(18, 4096, 8, MPIndexDirect)
	ip := uint32(0xC0A8_7B45) // 192.168.123.69
	key := ip >> (32 - 18)
	want := uint(key & 511)
	if got := c.setIdxFromMaskedDstIp(&FiveTuple{DstIP: ip}); got != want {
		t.Fatalf("set index = %d, want %d", got, want)
	}
	// Bits below the /18 prefix must not change the set.
	if got := c.setIdxFromMaskedDstIp(&FiveTuple{DstIP: ip | 0x3FFF}); got != want {
		t.Fatalf("host bits changed set index: %d, want %d", got, want)
	}
}

func TestMPDirectIndexKeysInSameSetDifferOnlyInTagBits(t *testing.T) {
	// Two keys that share the low 9 bits land in the same set; their remaining
	// 18-9 = 9 bits (the stored tag) tell them apart.
	c := newTestMPLayer(18, 4096, 8, MPIndexDirect)
	a := uint32(0x0001) << (32 - 18)
	b := (uint32(0x0001) | uint32(1)<<9) << (32 - 18)
	ia := c.setIdxFromMaskedDstIp(&FiveTuple{DstIP: a})
	ib := c.setIdxFromMaskedDstIp(&FiveTuple{DstIP: b})
	if ia != ib {
		t.Fatalf("expected same set, got %d and %d", ia, ib)
	}
}

func TestMPIndexDefaultIsCRCAndParameterUnchanged(t *testing.T) {
	c := newTestMPLayer(24, 2048, 4, "")
	p := c.Parameter().(*NbitSetAssociativeParameter)
	if p.Index != "" {
		t.Fatalf("CRC layer parameter Index = %q, want empty", p.Index)
	}
	if _, ok := p.GetBson()["index"]; ok {
		t.Fatalf("CRC layer bson must not contain index")
	}
	d := newTestMPLayer(24, 2048, 4, MPIndexDirect).Parameter().(*NbitSetAssociativeParameter)
	if d.GetBson()["index"] != MPIndexDirect {
		t.Fatalf("direct layer bson index = %v", d.GetBson()["index"])
	}
}

func TestNormalizeMPIndex(t *testing.T) {
	for in, want := range map[string]string{"": "", "crc": "", "CRC": "", "direct": MPIndexDirect} {
		got, err := NormalizeMPIndex(in)
		if err != nil || got != want {
			t.Fatalf("NormalizeMPIndex(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	if _, err := NormalizeMPIndex("xor"); err == nil {
		t.Fatalf("expected error for unknown index")
	}
}
