package main

import (
	"strings"
	"testing"
)

func TestLoadKnownHosts(t *testing.T) {
	hosts, err := loadKnownHosts()
	if err != nil {
		t.Fatal(err)
	}
	if len(hosts) != 3 {
		t.Fatalf("got %d known hosts, want 3", len(hosts))
	}
	ftp := findKnownHost(hosts, "150.65.7.130")
	if ftp.ASN != "AS17932" || ftp.ReverseDNS != "ftp.jaist.ac.jp" {
		t.Fatalf("unexpected JAIST attribution: %+v", ftp)
	}
	if unknown := findKnownHost(hosts, "192.0.2.1"); unknown != (knownHost{}) {
		t.Fatalf("unexpected attribution for unknown host: %+v", unknown)
	}
}

func TestFormatTopServices(t *testing.T) {
	ports := map[serviceKey]*serviceStats{
		{protocol: "tcp", port: 443}: {packets: 20, dsts: map[uint32]struct{}{1: {}, 2: {}}},
		{protocol: "tcp", port: 80}:  {packets: 30, dsts: map[uint32]struct{}{3: {}}},
		{protocol: "udp", port: 53}:  {packets: 10, dsts: map[uint32]struct{}{4: {}}},
	}
	got := formatTopServices(ports, 2)
	want := "tcp/80:30 packets,1 dst; tcp/443:20 packets,2 dst"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	if strings.Contains(got, "udp/53") {
		t.Fatal("service limit was not applied")
	}
}
