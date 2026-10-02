package main

import (
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcapgo"
)

func TestAnalyzeTracksIPv4FiveTupleFlowStats(t *testing.T) {
	tracePath := filepath.Join(t.TempDir(), "flows.pcap")
	if err := writeTestPcap(tracePath); err != nil {
		t.Fatalf("write test pcap: %v", err)
	}

	flows := map[flowKey]*flowStats{}
	sum, err := analyze(options{trace: tracePath, traceKind: "test"}, flows)
	if err != nil {
		t.Fatalf("analyze: %v", err)
	}

	if sum.TotalPackets != 4 {
		t.Fatalf("total packets = %d, want 4", sum.TotalPackets)
	}
	if sum.IPv4Packets != 4 {
		t.Fatalf("IPv4 packets = %d, want 4", sum.IPv4Packets)
	}
	if sum.ProtocolPackets[uint8(layers.IPProtocolTCP)] != 2 {
		t.Fatalf("TCP packets = %d, want 2", sum.ProtocolPackets[uint8(layers.IPProtocolTCP)])
	}
	if sum.ProtocolPackets[uint8(layers.IPProtocolUDP)] != 1 {
		t.Fatalf("UDP packets = %d, want 1", sum.ProtocolPackets[uint8(layers.IPProtocolUDP)])
	}
	if sum.ProtocolPackets[uint8(layers.IPProtocolICMPv4)] != 1 {
		t.Fatalf("ICMP packets = %d, want 1", sum.ProtocolPackets[uint8(layers.IPProtocolICMPv4)])
	}
	if len(flows) != 3 {
		t.Fatalf("flow count = %d, want 3", len(flows))
	}

	tcpKey := flowKey{
		Proto:   uint8(layers.IPProtocolTCP),
		SrcIP:   0x0a000001,
		DstIP:   0x0a000002,
		SrcPort: 12345,
		DstPort: 80,
	}
	tcpFlow := flows[tcpKey]
	if tcpFlow == nil {
		t.Fatalf("TCP flow key not found: %+v", tcpKey)
	}
	if tcpFlow.Packets != 2 {
		t.Fatalf("TCP flow packets = %d, want 2", tcpFlow.Packets)
	}
	if got := durationSeconds(tcpFlow.FirstSeen, tcpFlow.LastSeen); got != 1 {
		t.Fatalf("TCP flow duration = %f, want 1", got)
	}

	rows := buildFlowRows(flows)
	agg := buildAggregate(rows)
	if agg.UniqueFlows != 3 {
		t.Fatalf("unique flows = %d, want 3", agg.UniqueFlows)
	}
	if agg.OnePacketFlows != 2 {
		t.Fatalf("one-packet flows = %d, want 2", agg.OnePacketFlows)
	}
	if agg.PacketPercentiles.P50 != 1 || agg.PacketPercentiles.P99 != 2 {
		t.Fatalf("packet percentiles = %+v, want p50=1 p99=2", agg.PacketPercentiles)
	}
}

func TestAnalyzeTracksTextFiveTupleFlowStats(t *testing.T) {
	tracePath := filepath.Join(t.TempDir(), "jpix2sinet90s_5tuple.txt")
	content := "" +
		"0.000000000 115.36.174.87 1136 150.69.51.34 58745 UDP 0x00 94\n" +
		"0.000000342 115.36.174.87 1136 150.69.51.34 58745 UDP 0x00 94\n" +
		"0.000013090 64.56.182.146 443 130.54.130.227 8203 TCP 0x00 1518\n"
	if err := os.WriteFile(tracePath, []byte(content), 0o644); err != nil {
		t.Fatalf("write text trace: %v", err)
	}

	flows := map[flowKey]*flowStats{}
	sum, err := analyze(options{trace: tracePath, traceKind: "jpix-sinet"}, flows)
	if err != nil {
		t.Fatalf("analyze text trace: %v", err)
	}

	if sum.Format != "text-5tuple" {
		t.Fatalf("format = %q, want text-5tuple", sum.Format)
	}
	if sum.TotalPackets != 3 || sum.IPv4Packets != 3 {
		t.Fatalf("packets = total %d IPv4 %d, want 3/3", sum.TotalPackets, sum.IPv4Packets)
	}
	if sum.ProtocolPackets[uint8(layers.IPProtocolUDP)] != 2 {
		t.Fatalf("UDP packets = %d, want 2", sum.ProtocolPackets[uint8(layers.IPProtocolUDP)])
	}
	if sum.ProtocolPackets[uint8(layers.IPProtocolTCP)] != 1 {
		t.Fatalf("TCP packets = %d, want 1", sum.ProtocolPackets[uint8(layers.IPProtocolTCP)])
	}
	if len(flows) != 2 {
		t.Fatalf("flow count = %d, want 2", len(flows))
	}

	udpKey := flowKey{
		Proto:   uint8(layers.IPProtocolUDP),
		SrcIP:   0x7324ae57,
		DstIP:   0x96453322,
		SrcPort: 1136,
		DstPort: 58745,
	}
	if flows[udpKey] == nil || flows[udpKey].Packets != 2 {
		t.Fatalf("UDP flow = %+v, want 2 packets", flows[udpKey])
	}
}

func writeTestPcap(path string) error {
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := pcapgo.NewWriter(file)
	if err := writer.WriteFileHeader(1600, layers.LinkTypeEthernet); err != nil {
		return err
	}

	base := time.Unix(100, 0)
	packets := []struct {
		timestamp time.Time
		protocol  layers.IPProtocol
		srcIP     net.IP
		dstIP     net.IP
		srcPort   uint16
		dstPort   uint16
	}{
		{base, layers.IPProtocolTCP, net.IP{10, 0, 0, 1}, net.IP{10, 0, 0, 2}, 12345, 80},
		{base.Add(time.Second), layers.IPProtocolTCP, net.IP{10, 0, 0, 1}, net.IP{10, 0, 0, 2}, 12345, 80},
		{base.Add(2 * time.Second), layers.IPProtocolUDP, net.IP{10, 0, 0, 3}, net.IP{10, 0, 0, 4}, 5353, 53},
		{base.Add(3 * time.Second), layers.IPProtocolICMPv4, net.IP{10, 0, 0, 5}, net.IP{10, 0, 0, 6}, 0, 0},
	}

	for _, packet := range packets {
		data, err := serializeIPv4Packet(packet.protocol, packet.srcIP, packet.dstIP, packet.srcPort, packet.dstPort)
		if err != nil {
			return err
		}
		info := gopacket.CaptureInfo{
			Timestamp:     packet.timestamp,
			CaptureLength: len(data),
			Length:        len(data),
		}
		if err := writer.WritePacket(info, data); err != nil {
			return err
		}
	}
	return nil
}

func serializeIPv4Packet(protocol layers.IPProtocol, srcIP, dstIP net.IP, srcPort, dstPort uint16) ([]byte, error) {
	eth := layers.Ethernet{
		SrcMAC:       net.HardwareAddr{0x00, 0x11, 0x22, 0x33, 0x44, 0x55},
		DstMAC:       net.HardwareAddr{0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb},
		EthernetType: layers.EthernetTypeIPv4,
	}
	ip := layers.IPv4{
		Version:  4,
		TTL:      64,
		Protocol: protocol,
		SrcIP:    srcIP,
		DstIP:    dstIP,
	}

	buffer := gopacket.NewSerializeBuffer()
	options := gopacket.SerializeOptions{FixLengths: true, ComputeChecksums: true}
	switch protocol {
	case layers.IPProtocolTCP:
		tcp := layers.TCP{SrcPort: layers.TCPPort(srcPort), DstPort: layers.TCPPort(dstPort), SYN: true}
		if err := tcp.SetNetworkLayerForChecksum(&ip); err != nil {
			return nil, err
		}
		if err := gopacket.SerializeLayers(buffer, options, &eth, &ip, &tcp, gopacket.Payload([]byte("tcp"))); err != nil {
			return nil, err
		}
	case layers.IPProtocolUDP:
		udp := layers.UDP{SrcPort: layers.UDPPort(srcPort), DstPort: layers.UDPPort(dstPort)}
		if err := udp.SetNetworkLayerForChecksum(&ip); err != nil {
			return nil, err
		}
		if err := gopacket.SerializeLayers(buffer, options, &eth, &ip, &udp, gopacket.Payload([]byte("udp"))); err != nil {
			return nil, err
		}
	case layers.IPProtocolICMPv4:
		icmp := layers.ICMPv4{TypeCode: layers.CreateICMPv4TypeCode(layers.ICMPv4TypeEchoRequest, 0)}
		if err := gopacket.SerializeLayers(buffer, options, &eth, &ip, &icmp, gopacket.Payload([]byte("icmp"))); err != nil {
			return nil, err
		}
	default:
		if err := gopacket.SerializeLayers(buffer, options, &eth, &ip, gopacket.Payload([]byte("raw"))); err != nil {
			return nil, err
		}
	}
	return buffer.Bytes(), nil
}
