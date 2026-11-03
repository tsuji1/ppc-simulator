package main

import (
	"encoding/csv"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"test-module/cache"
)

func TestParseMPConfigs(t *testing.T) {
	got, err := parseMPConfigs("24:128,18:128; 24:64,18:192;")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("構成数 = %d, want 2", len(got))
	}
	if got[1].refbits[1] != 18 || got[1].capacities[0] != 64 || got[1].capacities[1] != 192 {
		t.Fatalf("2 つ目の構成が違う: %+v", got[1])
	}
	for _, bad := range []string{"", "24-128", "24:0", "33:128", "24:x"} {
		if _, err := parseMPConfigs(bad); err == nil {
			t.Errorf("%q はエラーになるべき", bad)
		}
	}
}

func TestBuildMPConfigSpecIndex(t *testing.T) {
	opts := options{way: 8}
	mp := mpConfigSpec{refbits: []int{24, 18}, capacities: []int{2048, 2048}}

	crc, err := buildMPConfigSpec(opts, mp, "crc")
	if err != nil {
		t.Fatal(err)
	}
	// CRC は従来の id のまま
	if crc.id != "mp-24-18-2048-2048" || crc.cacheIndexType != "" || crc.totalCapacity != 4096 {
		t.Fatalf("crc: %+v", crc)
	}
	if crc.definition.Cache.CacheLayers[0].Index != "" {
		t.Fatalf("crc の層の Index = %q", crc.definition.Cache.CacheLayers[0].Index)
	}

	direct, err := buildMPConfigSpec(opts, mp, "direct")
	if err != nil {
		t.Fatal(err)
	}
	if direct.id != "mp-24-18-2048-2048-direct" || direct.cacheIndexType != "direct" {
		t.Fatalf("direct: %+v", direct)
	}
	for _, layer := range direct.definition.Cache.CacheLayers {
		if layer.Index != "direct" {
			t.Fatalf("direct の層の Index = %q", layer.Index)
		}
	}

	if _, err := buildMPConfigSpec(opts, mpConfigSpec{refbits: []int{24}, capacities: []int{100}}, "crc"); err == nil {
		t.Fatal("way の倍数でない容量はエラーになるべき")
	}
}

func TestBuildConfigSpecsMPOnly(t *testing.T) {
	opts := options{
		way:       8,
		mpConfigs: []mpConfigSpec{{refbits: []int{24, 18}, capacities: []int{64, 64}}, {refbits: []int{24, 16}, capacities: []int{32, 96}}},
		mpIndexes: []string{"crc", "direct"},
	}
	configs, err := buildConfigSpecs(opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(configs) != 4 {
		t.Fatalf("構成数 = %d, want 4（PS なし）", len(configs))
	}
	seen := map[string]bool{}
	for _, c := range configs {
		if seen[c.id] {
			t.Fatalf("id が重複: %s", c.id)
		}
		seen[c.id] = true
	}
}

func TestWriteResultJSON(t *testing.T) {
	dir := t.TempDir()
	// 本番の rule と同じく default route を入れる（無いと最長一致の検索が空になる）
	rule := filepath.Join(dir, "rule.txt")
	trace := filepath.Join(dir, "trace.txt")
	if err := os.WriteFile(rule, []byte("0.0.0.0 0 0\n10.0.0.0 8 1\n10.1.0.0 16 2\n192.168.1.0 24 3\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	var lines []string
	for i := 0; i < 50; i++ {
		dst := []string{"10.1.2.3", "10.9.9.9", "192.168.1.7"}[i%3]
		lines = append(lines, "0 0 1.1.1.1 "+dst+" tcp 1 2")
	}
	if err := os.WriteFile(trace, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	opts := options{
		ruleFile: rule, trace: trace, way: 8, windows: []uint64{10}, insertionPolicy: "exclusive",
		mpConfigs:      []mpConfigSpec{{refbits: []int{24, 18}, capacities: []int{16, 16}}},
		mpIndexes:      []string{"direct"},
		psCapacity:     32,
		psIndexTypes:   []int{118},
		cacheTagLength: [][2]int{{9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}, {9, 24}},
		resultJSON:     filepath.Join(dir, "result.json"),
	}
	table, err := loadRoutingTable(rule)
	if err != nil {
		t.Fatal(err)
	}
	configs, err := buildConfigSpecs(opts)
	if err != nil {
		t.Fatal(err)
	}
	runs, err := buildWarmRuns(configs, opts, table)
	if err != nil {
		t.Fatal(err)
	}
	writer := csv.NewWriter(io.Discard)
	if _, err := processTrace(opts, table, func(p *cache.MinPacket) error {
		return processMinPacket(writer, opts, time.Now(), runs, p)
	}); err != nil {
		t.Fatal(err)
	}
	if err := writeResultJSON(opts, runs); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(opts.resultJSON)
	if err != nil {
		t.Fatal(err)
	}
	var got []struct {
		ConfigID string `json:"config_id"`
		Result   struct {
			Processed  int
			Hit        int
			StatDetail map[string]any
		} `json:"simulator_result"`
	}
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("構成数 = %d, want 2（MP と PS）", len(got))
	}
	for _, r := range got {
		if r.Result.Processed != 50 {
			t.Errorf("%s: Processed = %d, want 50", r.ConfigID, r.Result.Processed)
		}
		if r.Result.Hit >= 50 || r.Result.Hit <= 0 {
			t.Errorf("%s: Hit = %d（ミスもヒットもあるはず）", r.ConfigID, r.Result.Hit)
		}
		if d, _ := r.Result.StatDetail["DepthSum"].(float64); d <= 0 {
			t.Errorf("%s: StatDetail.DepthSum = %v, want > 0", r.ConfigID, r.Result.StatDetail["DepthSum"])
		}
	}
}
