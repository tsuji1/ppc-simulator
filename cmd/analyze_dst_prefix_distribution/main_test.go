package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAnalyzeTextTraceDestinationPrefixes(t *testing.T) {
	tracePath := filepath.Join(t.TempDir(), "sinet2jpix90s_5tuple.txt")
	content := "" +
		"0.000000000 115.36.174.87 1136 150.69.51.34 58745 UDP 0x00 94\n" +
		"0.000000342 115.36.174.87 1136 150.69.51.34 58745 UDP 0x00 94\n" +
		"0.000013090 64.56.182.146 443 130.54.130.227 8203 TCP 0x00 1518\n"
	if err := os.WriteFile(tracePath, []byte(content), 0o644); err != nil {
		t.Fatalf("write text trace: %v", err)
	}

	counts := map[int]map[uint32]uint64{
		24: {},
		32: {},
	}
	sum, err := analyze(options{
		trace:         tracePath,
		prefixLengths: []int{24, 32},
	}, counts)
	if err != nil {
		t.Fatalf("analyze text trace: %v", err)
	}

	if sum.Format != "text-5tuple" {
		t.Fatalf("format = %q, want text-5tuple", sum.Format)
	}
	if sum.TotalPackets != 3 || sum.IPv4Packets != 3 {
		t.Fatalf("packets = total %d IPv4 %d, want 3/3", sum.TotalPackets, sum.IPv4Packets)
	}
	if counts[24][0x96453300] != 2 {
		t.Fatalf("150.69.51.0/24 count = %d, want 2", counts[24][0x96453300])
	}
	if counts[32][0x96453322] != 2 {
		t.Fatalf("150.69.51.34/32 count = %d, want 2", counts[32][0x96453322])
	}
	if counts[32][0x823682e3] != 1 {
		t.Fatalf("130.54.130.227/32 count = %d, want 1", counts[32][0x823682e3])
	}
}
