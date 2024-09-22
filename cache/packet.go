package cache

import (
	"fmt"
)

type Packet struct {
	Time             float64
	Len              uint32
	Proto            string
	SrcIP, DstIP     uint32
	SrcPort, DstPort uint16
	IsLeafIndex      int8
	// IcmpType, IcmpCode uint16
}

type MinPacket struct {
	Proto        string
	SrcIP, DstIP uint32
	IsLeafIndex  int8
}

func (p *MinPacket) Packet() *Packet {
	return &Packet{
		Proto:       p.Proto,
		SrcIP:       p.SrcIP,
		DstIP:       p.DstIP,
		IsLeafIndex: p.IsLeafIndex,
	}
}

func (p *Packet) String() string {
	switch p.Proto {
	case "tcp", "udp":
		return fmt.Sprintf("{Time:%f Len:%v Proto:%v SrcIP:%v DstIP:%v SrcPort:%v DstPort:%v}", p.Time, p.Len, p.Proto, p.SrcIP, p.DstIP, p.SrcPort, p.DstPort)
	// case "icmp":
	// 	return fmt.Sprintf("{Time:%f Len:%v Proto:%v SrcIP:%v DstIP:%v IcmpType:%v IcmpCode:%v}", p.Time, p.Len, p.Proto, p.SrcIP, p.DstIP, p.IcmpType, p.IcmpCode)
	default:
		return fmt.Sprintf("{Time:%f Len:%v Proto:%v SrcIP:%v DstIP:%v SrcPort:%v DstPort:%v}", p.Time, p.Len, p.Proto, p.SrcIP, p.DstIP, p.SrcPort, p.DstPort)
		// return fmt.Sprintf("{Time:%f Len:%v Proto:%v SrcIP:%v DstIP:%v SrcPort:%v DstPort:%v IcmpType:%v IcmpCode:%v}", p.Time, p.Len, p.Proto, p.SrcIP, p.DstIP, p.SrcPort, p.DstPort, p.IcmpType, p.IcmpCode)
	}
}
