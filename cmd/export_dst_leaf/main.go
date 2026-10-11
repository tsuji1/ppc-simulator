// export_dst_leaf は gob-packet の []cache.MinPacket から TCP/UDP パケットの
// (DstIP, IsLeafIndex) だけを取り出し、5 byte/packet の little-endian バイナリに書き出す。
// variable_index_explore など、LPM 済みの宛先列だけを使う高速実験の入力に使う。
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/gob"
	"flag"
	"fmt"
	"os"
	"test-module/cache"
)

var (
	gobPath    = flag.String("gob", "", "gob file containing []cache.MinPacket")
	outputPath = flag.String("out", "", "output .dstleaf file")
	maxPacket  = flag.Uint64("max", 20_000_000, "maximum TCP/UDP packets to export; 0 means all")
)

func main() {
	flag.Parse()
	if *gobPath == "" || *outputPath == "" {
		fmt.Fprintln(os.Stderr, "-gob and -out are required")
		os.Exit(2)
	}
	file, err := os.Open(*gobPath)
	if err != nil {
		panic(err)
	}
	var packets []cache.MinPacket
	if err := gob.NewDecoder(bufio.NewReaderSize(file, 1<<22)).Decode(&packets); err != nil {
		panic(err)
	}
	file.Close()

	out, err := os.Create(*outputPath)
	if err != nil {
		panic(err)
	}
	writer := bufio.NewWriterSize(out, 1<<22)
	var written uint64
	var buf [5]byte
	for i := range packets {
		if *maxPacket > 0 && written >= *maxPacket {
			break
		}
		if packets[i].FiveTuple() == nil {
			continue
		}
		binary.LittleEndian.PutUint32(buf[:4], packets[i].DstIP)
		buf[4] = byte(packets[i].IsLeafIndex)
		writer.Write(buf[:])
		written++
	}
	if err := writer.Flush(); err != nil {
		panic(err)
	}
	out.Close()
	fmt.Printf("%s: total=%d exported=%d\n", *outputPath, len(packets), written)
}
