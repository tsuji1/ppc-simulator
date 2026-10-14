package main

// Streaming trace input (-stream).
//
// The default path keeps every packet of the trace in memory ([]MinPacket from a gob), which
// needs about 200 bytes per packet and does not fit traces of several hundred million packets.
// With -stream the trace is converted once to a flat .mpk file next to the gob, and every
// simulation task reads that file sequentially, so memory does not grow with the trace length.
//
// .mpk record (10 bytes, little endian): SrcIP uint32, DstIP uint32, IsLeafIndex int8, proto uint8.
// Only packets that the gob path would keep are written (parse succeeds and FiveTuple() != nil).

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"strings"
	. "test-module/cache"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcap"
)

const mpkRecordSize = 10

var mpkProtos = []string{"", "tcp", "udp", "icmp"}

// streamTracePath is set when -stream is used; runSimpleCacheSimulatorWithPackets then reads it.
var streamTracePath string
var streamPacketCount uint64

func mpkPathFromGob(gobPath string) string {
	return strings.TrimSuffix(gobPath, ".gob") + ".mpk"
}

func encodeMPKProto(proto string) (byte, error) {
	for i, p := range mpkProtos {
		if i > 0 && p == proto {
			return byte(i), nil
		}
	}
	return 0, fmt.Errorf("unsupported proto for mpk: %q", proto)
}

// convertPcapToMPK streams a pcap into an .mpk file with the same filtering as the gob path.
func convertPcapToMPK(tracePath string, mpkPath string) error {
	handle, err := pcap.OpenOffline(tracePath)
	if err != nil {
		return err
	}
	defer handle.Close()
	isLinkTypeRaw := layers.LinkType(handle.LinkType()) == layers.LinkTypeRaw

	tmp := mpkPath + ".part"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	w := bufio.NewWriterSize(f, 1<<22)
	var rec [mpkRecordSize]byte
	total, kept := 0, 0
	source := gopacket.NewPacketSource(handle, handle.LinkType())
	source.NoCopy = true
	for packet := range source.Packets() {
		total++
		if total%gobProgressInterval == 0 {
			fmt.Printf("mpk変換進捗: %d パケット処理済み (有効: %d)\n", total, kept)
		}
		mp, err := parsePcapPacketToMinPacket(packet, routingTable, isLinkTypeRaw)
		if err != nil || mp.FiveTuple() == nil {
			continue
		}
		proto, err := encodeMPKProto(mp.Proto)
		if err != nil {
			f.Close()
			return err
		}
		binary.LittleEndian.PutUint32(rec[0:4], mp.SrcIP)
		binary.LittleEndian.PutUint32(rec[4:8], mp.DstIP)
		rec[8] = byte(mp.IsLeafIndex)
		rec[9] = proto
		if _, err := w.Write(rec[:]); err != nil {
			f.Close()
			return err
		}
		kept++
	}
	if err := w.Flush(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	fmt.Printf("mpk変換完了: %d パケット中 %d を保存: %s\n", total, kept, mpkPath)
	return os.Rename(tmp, mpkPath)
}

// prepareStreamTrace makes sure the .mpk exists and records its packet count.
func prepareStreamTrace(tracePath string, gobPath string) {
	mpkPath := mpkPathFromGob(gobPath)
	if _, err := os.Stat(mpkPath); os.IsNotExist(err) {
		if !strings.HasSuffix(tracePath, ".pcap") {
			panic("-stream supports .pcap traces only: " + tracePath)
		}
		fmt.Printf("mpkファイルを作成中: %s\n", mpkPath)
		if err := convertPcapToMPK(tracePath, mpkPath); err != nil {
			panic(err)
		}
	} else if err != nil {
		panic(err)
	}
	st, err := os.Stat(mpkPath)
	if err != nil {
		panic(err)
	}
	if st.Size()%mpkRecordSize != 0 {
		panic(fmt.Sprintf("broken mpk file (size %d): %s", st.Size(), mpkPath))
	}
	streamTracePath = mpkPath
	streamPacketCount = uint64(st.Size() / mpkRecordSize)
	fmt.Printf("stream mode: %s (%d packets)\n", mpkPath, streamPacketCount)
}

// forEachStreamPacket calls step for each packet of the .mpk file until step returns false.
func forEachStreamPacket(path string, step func(p *MinPacket) bool) {
	f, err := os.Open(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	r := bufio.NewReaderSize(f, 1<<22)
	var rec [mpkRecordSize]byte
	for {
		if _, err := io.ReadFull(r, rec[:]); err != nil {
			if err == io.EOF {
				return
			}
			panic(err)
		}
		proto := int(rec[9])
		if proto == 0 || proto >= len(mpkProtos) {
			panic(fmt.Sprintf("broken mpk record (proto %d): %s", proto, path))
		}
		p := MinPacket{
			Proto:       mpkProtos[proto],
			SrcIP:       binary.LittleEndian.Uint32(rec[0:4]),
			DstIP:       binary.LittleEndian.Uint32(rec[4:8]),
			IsLeafIndex: int8(rec[8]),
		}
		if !step(&p) {
			return
		}
	}
}
