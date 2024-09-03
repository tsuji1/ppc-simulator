package main

import (
	"bytes"
	"encoding/csv"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	_ "net/http/pprof"
	"os"
	"reflect"
	"runtime"
	"runtime/pprof"
	"strconv"
	"strings"
	"sync"
	"test-module/cache"
	"test-module/simulator"
	"time"

	"github.com/koron/go-dproxy"
	"github.com/yosuke-furukawa/json5/encoding/json5"
)

// parseCSVRecord は、CSVレコードを解析して cache.Packet オブジェクトを生成します。
// 7-tuple または 8-tuple フォーマットに対応しています。
//
// 7-tuple: [time] [len] [srcIP] [dstIP] [proto] [srcPort] [dstPort]
//
// 8-tuple: [time] [srcIP] [srcPort] [dstIP] [dstPort] [proto] 0x[type (hex)] [len]
func parseCSVRecord(record []string) (*cache.Packet, error) {
	packet := new(cache.Packet)
	var err error

	var recordTimeStr, recordPacketLenStr, recordProtoStr, recordSrcIPStr, recordSrcPortStr, recordDstIPStr, recordDstPortStr string

	switch len(record) {
	case 8:
		recordTimeStr = record[0]
		recordSrcIPStr = record[1]
		recordSrcPortStr = record[2]
		recordDstIPStr = record[3]
		recordDstPortStr = record[4]
		recordProtoStr = record[5]
		recordPacketLenStr = record[7]
	case 7:
		recordTimeStr = record[0]
		recordPacketLenStr = record[1]
		recordSrcIPStr = record[2]
		recordDstIPStr = record[3]
		recordProtoStr = record[4]
		recordSrcPortStr = record[5]
		recordDstPortStr = record[6]
	default:
		return nil, fmt.Errorf("expected record have 7 or 8 fields, but not: %d", len(record))
	}

	packet.Time, err = strconv.ParseFloat(recordTimeStr, 64)
	if err != nil {
		return nil, err
	}
	packetLen, err := strconv.ParseUint(recordPacketLenStr, 10, 32)
	if err != nil {
		return nil, err
	}
	packet.Len = uint32(packetLen)

	packet.SrcIP = net.ParseIP(recordSrcIPStr)
	packet.DstIP = net.ParseIP(recordDstIPStr)
	packet.Proto = strings.ToLower(recordProtoStr)

	switch packet.Proto {
	case "tcp", "udp", "UDP", "TCP":
		srcPort, err := strconv.ParseUint(recordSrcPortStr, 10, 16)
		if err != nil {
			return nil, err
		}
		packet.SrcPort = uint16(srcPort)

		dstPort, err := strconv.ParseUint(recordDstPortStr, 10, 16)
		if err != nil {
			return nil, err
		}
		packet.DstPort = uint16(dstPort)
	case "icmp":
		// icmpType, err := strconv.ParseUint(record[5], 10, 16)
		// if err != nil {
		// 	return nil, err
		// }
		// packet.IcmpType = uint16(icmpType)
		// icmpCode, err := strconv.ParseUint(record[6], 10, 16)
		// if err != nil {
		// 	return nil, err
		// }
		// packet.IcmpCode = uint16(icmpCode)
	default:
		return nil, fmt.Errorf("unknown packet proto: %s", packet.Proto)
	}
	
	packet.DstIPMasked = nil
	packet.HitIPList = nil
	packet.IsDstIPLeaf = nil
	packet.HitItemList = nil
	return packet, nil
}

func deprecatedGetProperCSVReader(fp *os.File) *csv.Reader {
	newReader := func(fp *os.File, comma rune) *csv.Reader {
		fp.Seek(0, 0)
		reader := csv.NewReader(fp)
		reader.Comma = comma

		return reader
	}

	tryRead := func(reader *csv.Reader) (bool, error) {
		record, err := reader.Read()

		if err == io.EOF {
			return true, nil
		}

		if err != nil {
			return false, err
		}

		return len(record) != 1, nil
	}

	for _, comma := range []rune{',', '\t', ' '} {
		if ok, _ := tryRead(newReader(fp, comma)); ok {
			return newReader(fp, comma)
		}
	}

	return nil
}

// getProperCSVReader は、ファイルポインタから適切な区切り文字を見つけて CSVリーダーを生成します。
func getProperCSVReader(fp *os.File) *csv.Reader {
	// ファイル全体をメモリに読み込む
	content, err := io.ReadAll(fp)
	if err != nil {
		return nil
	}

	newReader := func(content []byte, comma rune) *csv.Reader {
		reader := csv.NewReader(bytes.NewReader(content))
		reader.Comma = comma
		return reader
	}

	tryRead := func(reader *csv.Reader) (bool, error) {
		record, err := reader.Read()

		if err == io.EOF {
			return true, nil
		}

		if err != nil {
			return false, err
		}

		return len(record) != 1, nil
	}

	for _, comma := range []rune{',', '\t', ' '} {
		reader := newReader(content, comma)
		if ok, err := tryRead(reader); ok || err != nil {
			return reader
		}
	}

	return nil
}

// runSimpleCacheSimulatorWithCSV は、指定された CSV ファイルとキャッシュシミュレータを使用してシミュレーションを実行します。
// printInterval ごとにシミュレーションの統計情報を出力します。
func runSimpleCacheSimulatorWithCSVSync(fp *os.File, sim *simulator.SimpleCacheSimulator, printInterval int, bench bool) {
	reader := getProperCSVReader(fp)

	if reader == nil {
		panic("Can't read input as valid tsv/csv file")
	}
	var wg sync.WaitGroup
	// var mu sync.Mutex
	var start time.Time
	var elapsed time.Duration
	var isEnd bool
	isEnd = false

	resultChan := make(chan bool)
	limit := make(chan struct{}, 1000)
	for i := 0; !isEnd; i += 1 {

		wg.Add(1)
		go func(resultChan chan bool) {
			limit <- struct{}{} // バッファ付きのchanがバッファを超える要素を送信しようとしたときにブロックする。
			defer wg.Done()

			record, err := reader.Read()

			if err != nil {
				if err == io.EOF {
					resultChan <- true
				} else {

					switch err.(type) {
					case *csv.ParseError:
						fmt.Println("ParseError:", err)
						panic(err)
					default:
						fmt.Println(reflect.TypeOf(err))
						panic(err)
					}
				}
			} else {

				packet, err := parseCSVRecord(record)

				if err != nil {
					fmt.Println("Error:", err)
					panic(err)
					// panic(err)
				}

				// if packet.Proto == "icmp" {
				// 	// ICMPパケットは無視
				// 	continue
				// }

				if packet.FiveTuple() == nil {
					panic("FiveTuple is nil")
				}
				start = time.Now()
				sim.Process(packet)
				elapsed = time.Since(start)
				if sim.GetStat().Processed%printInterval == 0 {
					fmt.Printf("sim process time: %s\n", elapsed)
					fmt.Printf("%v\n", sim.GetStatString())
				}
				resultChan <- false
			}
			<-limit
		}(resultChan)
		isEnd = <-resultChan

		// go func() {

		// 	mu.Lock()

		// 	mu.Unlock()
		// }()
	}
	wg.Wait()

}

// runSimpleCacheSimulatorWithCSV は、指定された CSV ファイルとキャッシュシミュレータを使用してシミュレーションを実行します。
// printInterval ごとにシミュレーションの統計情報を出力します。
func runSimpleCacheSimulatorWithCSV(fp *os.File, sim *simulator.SimpleCacheSimulator, printInterval int, bench bool) {
	reader := getProperCSVReader(fp)

	if reader == nil {
		panic("Can't read input as valid tsv/csv file")
	}

	for i := 0; ; i += 1 {
		record, err := reader.Read()

		if err != nil {
			if err == io.EOF {
				break
			}

			switch err.(type) {
			case *csv.ParseError:
				continue
			default:
				fmt.Println(reflect.TypeOf(err))
				continue
			}
		}

		packet, err := parseCSVRecord(record)

		if err != nil {
			fmt.Println("Error:", err)
			continue
			// panic(err)
		}

		// if packet.Proto == "icmp" {
		// 	// ICMPパケットは無視
		// 	continue
		// }

		if packet.FiveTuple() == nil {
			continue
		}
		start := time.Now()
		sim.Process(packet)
		elapsed := time.Since(start)

		if sim.GetStat().Processed%printInterval == 0 {

			fmt.Printf("sim process time: %s\n", elapsed)
			fmt.Printf("%v\n", sim.GetStatString())
			if bench {
				os.Exit(0)
			}
		}
	}
}

var cpuprofile = flag.String("cpuprofile", "", "write cpu profile to file")
var memprofile = flag.String("memprofile", "", "write memory profile to this file")
var cacheparam = flag.String("cacheparam", "", "cache parameter file")
var trace = flag.String("trace", "", "network trace file")
var bench = flag.Bool("bench", false, "to benchmark")

// main は、シミュレーションを実行するエントリーポイントです。
// コマンドライン引数でキャッシュ構成のコンフィグファイルとオプションの CSV ファイルを指定します。
func main() {
	flag.Parse()
	if *trace == "" {
		fmt.Printf("You must specify the trace file\n")
		os.Exit(1)
	}
	if *cacheparam == "" {
		fmt.Printf("You must specify the cache parameter file\n")
		os.Exit(1)
	}
	if *cpuprofile != "" {
		f, err := os.Create(*cpuprofile)
		if err != nil {
			log.Fatal("could not create CPU profile: ", err)
		}
		defer f.Close()

		if err := pprof.StartCPUProfile(f); err != nil {
			log.Fatal("could not start CPU profile: ", err)
		}
		defer pprof.StopCPUProfile()
	}

	simulaterDefinitionBytes, err := os.ReadFile(*cacheparam)
	if err != nil {
		panic(err)
	}

	var simlatorDefinition interface{}
	err = json5.Unmarshal(simulaterDefinitionBytes, &simlatorDefinition)
	if err != nil {
		panic(err)
	}
	p := dproxy.New(simlatorDefinition)
	interval, err := p.M("Interval").Int64()
	if err != nil {
		interval = 100000 // interval回ごとに出力
	}

	cacheSim, err := simulator.BuildSimpleCacheSimulator(simlatorDefinition)

	if err != nil {
		panic(err)
	}

	var fpCSV *os.File

	fpCSV, err = os.Open(*trace)

	if err != nil {
		panic(err)
	}
	defer fpCSV.Close()

	useSync := false // 今のところgoroutineを使う方が遅いので、基本はfalse

	if useSync {
		runSimpleCacheSimulatorWithCSVSync(fpCSV, cacheSim, int(interval), *bench)
	} else {
		runSimpleCacheSimulatorWithCSV(fpCSV, cacheSim, int(interval), *bench)
	}
	// runSimpleCacheSimulatorWithCSV(fpCSV, cacheSim, 1)

	fmt.Printf("%v\n", cacheSim.GetStatString())

	if *memprofile != "" {
		f, err := os.Create(*memprofile)
		if err != nil {
			log.Fatal("could not create memory profile: ", err)
		}
		defer f.Close() // error handling omitted for example
		runtime.GC()    // get up-to-date statistics
		if err := pprof.WriteHeapProfile(f); err != nil {
			log.Fatal("could not write memory profile: ", err)
		}
	}
}
