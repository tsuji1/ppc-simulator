package cache

import (
	"fmt"
	"net"

	. "github.com/tchap/go-patricia/patricia"
)

type Packet struct {
	Time             float64
	Len              uint32
	Proto            string
	SrcIP, DstIP     net.IP
	SrcPort, DstPort uint16
	DstIPMasked      *[33]string
	IsDstIPLeaf      *[33]bool
	HitIPList        *[33][]string
	HitItemList      *[]Item
	// IcmpType, IcmpCode uint16
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
