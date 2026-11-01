package main

import "testing"

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
