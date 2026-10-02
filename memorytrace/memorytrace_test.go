package memorytrace

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestTracerWritesRequestCSV(t *testing.T) {
	tracer := NewTracer()
	tracePath := filepath.Join(t.TempDir(), "requests.csv")

	if err := tracer.OpenCSV(tracePath); err != nil {
		t.Fatalf("OpenCSV failed: %v", err)
	}

	tracer.AddDRAMAccess(&DRAMAccess{
		Timestamp:   7,
		Address:     0x1234abcd,
		Type:        "R",
		Source:      "UnifiedCache",
		CacheHit:    false,
		MissType:    "cache-miss",
		SrcIP:       0x0a000001,
		DstIP:       0x0a000002,
		Proto:       "tcp",
		SrcPort:     1000,
		DstPort:     443,
		IsLeafIndex: 24,
	})

	if err := tracer.Close(); err != nil {
		t.Fatalf("Close failed: %v", err)
	}

	body, err := os.ReadFile(tracePath)
	if err != nil {
		t.Fatalf("ReadFile failed: %v", err)
	}

	text := string(body)
	if !strings.Contains(text, "cycle,sequence,op,address,cache_hit,miss_type,source") {
		t.Fatalf("CSV header missing: %s", text)
	}
	if !strings.Contains(text, "7,1,R,0x000000001234abcd,false,cache-miss,UnifiedCache") {
		t.Fatalf("CSV row missing: %s", text)
	}
}

func TestTracerStats(t *testing.T) {
	tracer := NewTracer()
	tracer.EnableInMemory()

	tracer.AddDRAMAccess(&DRAMAccess{Timestamp: 10, Type: "R", CacheHit: false})
	tracer.AddDRAMAccess(&DRAMAccess{Timestamp: 20, Type: "W", CacheHit: true})

	stats := tracer.Stats()
	if stats.Accesses != 2 {
		t.Fatalf("Accesses = %d, want 2", stats.Accesses)
	}
	if stats.Reads != 1 {
		t.Fatalf("Reads = %d, want 1", stats.Reads)
	}
	if stats.Writes != 1 {
		t.Fatalf("Writes = %d, want 1", stats.Writes)
	}
	if stats.Hits != 1 {
		t.Fatalf("Hits = %d, want 1", stats.Hits)
	}
	if stats.Misses != 1 {
		t.Fatalf("Misses = %d, want 1", stats.Misses)
	}
	if stats.FirstCycle != 10 || stats.LastCycle != 20 {
		t.Fatalf("cycle range = %d-%d, want 10-20", stats.FirstCycle, stats.LastCycle)
	}
}
