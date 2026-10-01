package main

import (
	"testing"

	"test-module/cache"
)

func TestCachePrefixUsesExclusiveUnifiedTagRange(t *testing.T) {
	tests := []struct {
		name        string
		packet      cache.MinPacket
		wantOK      bool
		wantLength  int8
		wantNetwork uint32
	}{
		{
			name:        "leaf shorter than minimum is stored at minimum",
			packet:      cache.MinPacket{DstIP: 0x0a123456, IsLeafIndex: 8},
			wantOK:      true,
			wantLength:  9,
			wantNetwork: 0x14,
		},
		{
			name:        "leaf in range keeps exact length",
			packet:      cache.MinPacket{DstIP: 0xc0000201, IsLeafIndex: 24},
			wantOK:      true,
			wantLength:  24,
			wantNetwork: 0xc00002,
		},
		{
			name:   "leaf longer than maximum is not cacheable",
			packet: cache.MinPacket{DstIP: 0xc0000201, IsLeafIndex: 25},
			wantOK: false,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			key, ok := cachePrefix(test.packet, 9, 24)
			if ok != test.wantOK {
				t.Fatalf("cachePrefix ok = %v, want %v", ok, test.wantOK)
			}
			if !ok {
				return
			}
			if key.length != test.wantLength || key.network != test.wantNetwork {
				t.Fatalf(
					"cachePrefix = {length:%d network:%x}, want {length:%d network:%x}",
					key.length,
					key.network,
					test.wantLength,
					test.wantNetwork,
				)
			}
		})
	}
}
