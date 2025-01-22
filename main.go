package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/csv"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	_ "net/http/pprof"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"runtime"
	"runtime/debug"
	"runtime/pprof"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"test-module/cache"
	. "test-module/cache"
	"test-module/db"
	"test-module/ipaddress"
	"test-module/routingtable"
	"test-module/simulator"
	"time"
	"unicode"

	"encoding/gob"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcap"
	"github.com/joho/godotenv"

	"github.com/yosuke-furukawa/json5/encoding/json5"
)

// グローバル変数でパケットを保存するスライス
var packets []MinPacket
var cpuprofile = flag.String("cpuprofile", "", "write cpu profile to file")
var memprofile = flag.String("memprofile", "", "write memory profile to this file")
var cacheparam = flag.String("cacheparam", "", "cache parameter file")
var forceupdate = flag.Bool("dbupdate", false, "update db")
var cachenum = flag.Int("cachenum", 2, "cache number")
var trace = flag.String("trace", "", "network trace file")
var bench = flag.Bool("bench", false, "to benchmark")
var maxProccess = flag.Uint64("max", 0, "max process")
var skip = flag.Int("skip", 0, "skip")
var rulefile = flag.String("rulefile", "", "rule file")

func init() {
	// routingtable.Data 型の登録
	flag.Parse()
	debug.SetGCPercent(50)
	gob.Register(routingtable.Data{})

	// ファイル名から拡張子を外して取得する
	base := filepath.Base(*trace)
	filename := strings.TrimSuffix(base, filepath.Ext(base))

	// 新しいパスを生成する
	gobPath := filepath.Join("gob-packet", filename+".gob")
	gobdebugmode := false 
	ext := filepath.Ext(*trace)
	// gobPathファイルが存在するか確認

	if _, err := os.Stat(gobPath); err == nil && !gobdebugmode {
		// gobファイルが存在する場合、デコードする
		fmt.Println("gobファイルが見つかりました。デコード中...")
		packets = decodeGobFile(gobPath)
	} else if os.IsNotExist(err) || gobdebugmode {
		// gobファイルが存在しない場合、通常の処理を行う
		if !gobdebugmode {
			fmt.Println("gobファイルが見つかりません。新しいファイルを生成中...")
		} else {
			fmt.Println("debugmode で実行中")
		}

		switch ext {
		case ".csv", ".tsv", ".p7",".data",".txt":
			// CSV/TSVファイル処理
			fpCSV, err := os.Open(*trace)
			if err != nil {
				panic(err)
			}
			defer fpCSV.Close()

			// パケットスライスを初期化
			packets = make([]MinPacket, 0, 230000000) // 2億個分の容量を初期確保
			reader := deprecatedGetProperCSVReader(fpCSV)

			if reader == nil {
				panic("Can't read input as valid tsv/csv file")
			}

			fp, err := os.Open(*rulefile)
			if err != nil {
				panic(err)
			}
			defer fp.Close()
			r := routingtable.NewRoutingTablePatriciaTrie()
			r.ReadRule(fp)

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

				packet, err := parseCSVRecordToMinPacket(record, r)

				if err != nil {
					fmt.Println("Error:", err)
					continue
				}

				if packet.FiveTuple() == nil {
					continue
				}
				packets = append(packets, *packet)
				if i%100000 == 0 {
					if i != 0 {
						fmt.Printf("i: %d\n", i)
						if gobdebugmode {
							break
						}
					}
				}
			}

			// gobファイルに書き込む処理
			if !gobdebugmode {
				err = savePacketsToGob(gobPath, packets)
				if err != nil {
					fmt.Println("gobファイルへの保存に失敗しました:", err)
				} else {
					fmt.Println("gobファイルにパケットデータを保存しました:", gobPath)
				}
			}

			runtime.GC()

		case ".pcap":
			fmt.Println("pcapファイルを処理中...")
			traceBase := filepath.Base(*trace)
			ruleBase := filepath.Base(*rulefile)
			if extractDigits(traceBase) != extractDigits(ruleBase) {
				// panic("rulefileとtracefileの文字が一致しません")
				fmt.Printf("rulefileとtracefileの文字が一致しませんが無視します。")

			}
			handle, err := pcap.OpenOffline(*trace)
			if err != nil {
				panic(err)
			}
			defer handle.Close()

			packetSource := gopacket.NewPacketSource(handle, handle.LinkType())

			// パケットスライスを初期化
			packets = make([]MinPacket, 0, 230000000) // 2億個分の容量を初期確保
			fp, err := os.Open(*rulefile)
			if err != nil {
				panic(err)
			}
			defer fp.Close()
			r := routingtable.NewRoutingTablePatriciaTrie()
			r.ReadRule(fp)

				// メタデータを表示
			fmt.Printf("PCAP File Metadata:\n")
			fmt.Printf("LinkType: %v\n", handle.LinkType())
			fmt.Printf("SnapLen: %d\n", handle.SnapLen())
			


			isLinkTypeRaw := false
			if layers.LinkType(handle.LinkType()) == layers.LinkTypeRaw{
				isLinkTypeRaw = true
			}
			
			fmt.Printf("isLinkTypeRaw: %v\n", isLinkTypeRaw)


			// range over the channel (only one iteration variable is allowed)
			num_minpackets := 0
			for packet := range packetSource.Packets() {
				minPacket, err := parsePcapPacketToMinPacket(packet, r,isLinkTypeRaw)
				if err != nil {
					fmt.Println("Error:", err)// かなりerrorが出るのでコメントアウト
					// エラーでてもcontinueしない
					continue
				}
				if minPacket.FiveTuple() == nil {
					
					continue
				}

				packets = append(packets, *minPacket)
				num_minpackets++
				if num_minpackets%100000 == 0 {
					if num_minpackets != 0 {
						fmt.Printf("num_minpacket %d\n", num_minpackets)
						if gobdebugmode {
							break
						}
					}
				}

			}

			// gobファイルに書き込む処理
			if !gobdebugmode {
				err = savePacketsToGob(gobPath, packets)
				if err != nil {
					fmt.Println("gobファイルへの保存に失敗しました:", err)
				} else {
					fmt.Println("gobファイルにパケットデータを保存しました:", gobPath)
				}
			}

			runtime.GC()

		default:
			panic("未対応のファイル形式です: " + ext)
		}
	} else {
		// その他のエラー
		panic(err)
	}
}

func extractDigits(input string) string {
	result := ""
	for _, r := range input {
		if unicode.IsDigit(r) {
			result += string(r)
		}
	}
	return result
}

// gobファイルをデコードしてパケットデータを取得
func decodeGobFile(filepath string) []MinPacket {

	// packets = make([]MinPacket, 0, 230000000) // 2億個分の容量を初期確保
	file, err := os.Open(filepath)
	if err != nil {
		log.Fatal("ファイルオープンエラー:", err)
	}
	defer file.Close()

	decoder := gob.NewDecoder(file)
	if err := decoder.Decode(&packets); err != nil {
		log.Fatal("デコードエラー:", err)
	}
	return packets
}

// パケットデータをgobファイルに保存する関数
func savePacketsToGob(filepath string, packets []MinPacket) error {
	file, err := os.Create(filepath)
	if err != nil {
		return err
	}
	defer file.Close()

	encoder := gob.NewEncoder(file)
	if err := encoder.Encode(packets); err != nil {
		return err
	}
	return nil
}

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

	packet.SrcIP = IpToUInt32(net.ParseIP(recordSrcIPStr))
	packet.DstIP = IpToUInt32(net.ParseIP(recordDstIPStr))
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

	return packet, nil
}
func parseCSVRecordToMinPacket(record []string, r *routingtable.RoutingTablePatriciaTrie) (*cache.MinPacket, error) {
	packet := new(cache.MinPacket)

	var recordProtoStr, recordSrcIPStr, recordDstIPStr string

	switch len(record) {
	case 8:
		recordSrcIPStr = record[1]

		recordDstIPStr = record[3]

		recordProtoStr = record[5]
	case 7:
		recordSrcIPStr = record[2]
		recordDstIPStr = record[3]
		recordProtoStr = record[4]

	default:
		return nil, fmt.Errorf("expected record have 7 or 8 fields, but not: %d", len(record))
	}
	
	if(recordProtoStr == "0x00" ){
		fmt.Printf("recordProtoStr: %v\n",record)
		return nil, fmt.Errorf("recordProtoStr is 0x00")
	}

	srcip := net.ParseIP(recordSrcIPStr)
	if srcip == nil{
		return nil, fmt.Errorf("srcip is nil")
	}
	packet.SrcIP = IpToUInt32(srcip)

	dstip := net.ParseIP(recordDstIPStr)
	if dstip == nil{
		return nil, fmt.Errorf("dstip is nil")
	}
	packet.DstIP = IpToUInt32(dstip)
	packet.Proto = strings.ToLower(recordProtoStr)

	dstIP := ipaddress.NewIPaddress(packet.DstIP)
	for i := 0; i < 33; i++ {
		b := r.IsLeaf(dstIP, i)
		if b {
			packet.IsLeafIndex = int8(i)
			break
		}
	}

	// switch packet.Proto {
	// case "tcp", "udp", "UDP", "TCP":
	// 	srcPort, err := strconv.ParseUint(recordSrcPortStr, 10, 16)
	// 	if err != nil {
	// 		return nil, err
	// 	}
	// 	packet.SrcPort = uint16(srcPort)

	// 	dstPort, err := strconv.ParseUint(recordDstPortStr, 10, 16)
	// 	if err != nil {
	// 		return nil, err
	// }
	// packet.DstPort = uint16(dstPort)
	// case "icmp":
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
	// default:
	// return nil, fmt.Errorf("unknown packet proto: %s", packet.Proto)
	// }

	return packet, nil
}

// parsePcapPacketToMinPacket parses a gopacket.Packet into a MinPacket
func parsePcapPacketToMinPacket(packet gopacket.Packet, r *routingtable.RoutingTablePatriciaTrie,isRawType bool) (*cache.MinPacket, error) {
	// MinPacket構造体を新規作成
	minPacket := new(cache.MinPacket)
	// if !isRawType {

	// // Ethernet層があるか確認
	// ethernetLayer := packet.Layer(layers.LayerTypeEthernet)
	// if ethernetLayer == nil {
	// 	return nil, fmt.Errorf("No Ethernet layer found")
	// }
	// }

	// IP層があるか確認
	ipLayer := packet.Layer(layers.LayerTypeIPv4)
	if ipLayer == nil {
		return nil, fmt.Errorf("No IPv4 layer found")
	}
	ip, _ := ipLayer.(*layers.IPv4)

	// SrcIP, DstIPを設定
	ipuint32src := IpToUInt32(ip.SrcIP)
	ipuint32dst := IpToUInt32(ip.DstIP)

	fmt.Println(ipaddress.NewIPaddress(ipuint32src).String())
	fmt.Println(ipaddress.NewIPaddress(ipuint32dst).String())
	minPacket.SrcIP = IpToUInt32(ip.SrcIP)
	minPacket.DstIP = IpToUInt32(ip.DstIP)

	// プロトコルを設定
	switch ip.Protocol {
	case layers.IPProtocolTCP:
		minPacket.Proto = "tcp"
	case layers.IPProtocolUDP:
		minPacket.Proto = "udp"
	case layers.IPProtocolICMPv4:
		minPacket.Proto = "icmp"
	default:
		// minPacket.Proto = strings.ToLower(ip.Protocol.String())
		return nil, fmt.Errorf("Unsupported protocol: %s", ip.Protocol)
	}

	// ルーティングテーブルを用いてDstIPのleaf indexを設定
	dstIP := ipaddress.NewIPaddress(minPacket.DstIP)
	for i := 0; i < 33; i++ {
		if r.IsLeaf(dstIP, i) {
			minPacket.IsLeafIndex = int8(i)
			break
		}
	}

	// // TCP/UDPプロトコルに応じたポート情報を取得
	// if minPacket.Proto == "tcp" || minPacket.Proto == "udp" {
	// 	transportLayer := packet.TransportLayer()
	// 	switch layer := transportLayer.(type) {
	// 	case *layers.TCP:
	// 		minPacket.SrcPort = uint16(layer.SrcPort)
	// 		minPacket.DstPort = uint16(layer.DstPort)
	// 	case *layers.UDP:
	// 		minPacket.SrcPort = uint16(layer.SrcPort)
	// 		minPacket.DstPort = uint16(layer.DstPort)
	// 	default:
	// 		return nil, fmt.Errorf("Unsupported transport layer protocol")
	// 	}
	// }

	// // ICMPプロトコルの場合、タイプとコードを取得
	// if minPacket.Proto == "icmp" {
	// 	icmpLayer := packet.Layer(layers.LayerTypeICMPv4)
	// 	if icmpLayer == nil {
	// 		return nil, fmt.Errorf("No ICMPv4 layer found")
	// 	}
	// 	icmp, _ := icmpLayer.(*layers.ICMPv4)
	// 	minPacket.IcmpType = uint16(icmp.TypeCode.Type())
	// 	minPacket.IcmpCode = uint16(icmp.TypeCode.Code())
	// }

	return minPacket, nil
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

// func runSimpleCacheSimulatorWithGoRoutine() {
// 	reader := getProperCSVReader(fp)

// 	if reader == nil {
// 		panic("Can't read input as valid tsv/csv file")
// 	}
// 	var wg sync.WaitGroup
// 	// var mu sync.Mutex
// 	var start time.Time
// 	var elapsed time.Duration
// 	var isEnd bool
// 	isEnd = false

// 	resultChan := make(chan bool)
// 	limit := make(chan struct{}, 1000)
// 	for i := 0; !isEnd; i += 1 {

// 		wg.Add(1)
// 		go func(resultChan chan bool) {
// 			limit <- struct{}{} // バッファ付きのchanがバッファを超える要素を送信しようとしたときにブロックする。
// 			defer wg.Done()

// 			record, err := reader.Read()

// 			if err != nil {
// 				if err == io.EOF {
// 					resultChan <- true
// 				} else {

// 					switch err.(type) {
// 					case *csv.ParseError:
// 						fmt.Println("ParseError:", err)
// 						panic(err)
// 					default:
// 						fmt.Println(reflect.TypeOf(err))
// 						panic(err)
// 					}
// 				}
// 			} else {

// 				packet, err := parseCSVRecord(record)

// 				if err != nil {
// 					fmt.Println("Error:", err)
// 					panic(err)
// 					// panic(err)
// 				}

// 				// if packet.Proto == "icmp" {
// 				// 	// ICMPパケットは無視
// 				// 	continue
// 				// }

// 				if packet.FiveTuple() == nil {
// 					panic("FiveTuple is nil")
// 				}
// 				start = time.Now()
// 				sim.Process(packet)
// 				elapsed = time.Since(start)
// 				if sim.GetStat().Processed%printInterval == 0 {
// 					fmt.Printf("sim process time: %s\n", elapsed)
// 					fmt.Printf("%v\n", sim.GetStatString())
// 				}
// 				resultChan <- false
// 			}
// 			<-limit
// 		}(resultChan)
// 		isEnd = <-resultChan

// 		// go func() {

// 		// 	mu.Lock()

// 		// 	mu.Unlock()
// 		// }()
// 	}
// 	wg.Wait()

// }

func runSimpleCacheSimulatorWithGoRoutine(fp *os.File, sim *simulator.SimpleCacheSimulator, printInterval int, bench bool) {
	reader := deprecatedGetProperCSVReader(fp)

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

// runSimpleCacheSimulatorWithCSV は、指定された CSV ファイルとキャッシュシミュレータを使用してシミュレーションを実行します。
// printInterval ごとにシミュレーションの統計情報を出力します。
func runSimpleCacheSimulatorWithCSV(fp *os.File, sim *simulator.SimpleCacheSimulator, printInterval int, bench bool) {
	reader := deprecatedGetProperCSVReader(fp)

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

func runSimpleCacheSimulatorWithPackets(packetList *[]MinPacket, sim *simulator.SimpleCacheSimulator, printInterval int, maxProccess uint64, bench bool) simulator.SimulatorResult {

	for _, p := range *packetList {

		start := time.Now()
		sim.Process(&p)
		elapsed := time.Since(start)

		if sim.GetStat().Processed%printInterval == 0 {

			fmt.Printf("sim process time: %s\n", elapsed)
			fmt.Printf("%v\n", sim.GetStatString())
			if bench {
				break
			}
		}
		if sim.GetStat().Processed == 10000 && bench {
			break
		}
		if maxProccess != 0 && uint64(sim.GetStat().Processed) == maxProccess {
			break
		}
	}
	stat := sim.GetSimulatorResult()
	fmt.Printf("%v\n", stat)
	return stat

}

func generateFileName() string {
	// 現在時刻を取得
	currentTime := time.Now()
	timestamp := currentTime.Format("200601021504") // フォーマット YYYYMMDDHHMM

	// ランダムな文字列を生成
	randomString := generateRandomString(8) // 長さ8のランダム文字列

	// ファイル名を構築
	fileName := fmt.Sprintf("memorytrace-%s-%s.txt", timestamp, randomString)
	return fileName
}

func generateRandomString(length int) string {
	const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	b := make([]byte, length)
	_, err := rand.Read(b)
	if err != nil {
		panic("ランダム文字列の生成に失敗しました")
	}

	// charsetからランダムな文字を選択
	for i := range b {
		b[i] = charset[b[i]%byte(len(charset))]
	}
	return string(b)
}

// main は、シミュレーションを実行するエントリーポイントです。
// コマンドライン引数でキャッシュ構成のコンフィグファイルとオプションの CSV ファイルを指定します。
func main() {

	if *trace == "" {
		fmt.Printf("You must specify the trace file\n")
		os.Exit(1)
	}

	var f *os.File
	var err error

	err = godotenv.Load()
	if err != nil {
		log.Fatal("Error loading .env file")
	}

	if *cpuprofile != "" {
		f, err = os.Create(*cpuprofile)
		if err != nil {
			log.Fatal("could not create CPU profile: ", err)
		}

		if err := pprof.StartCPUProfile(f); err != nil {
			log.Fatal("could not start CPU profile: ", err)
		}
	}

	// シグナルを受け取るチャネルを設定
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	// dbにInsert

	ctx := context.Background()

	// Create a new test MongoDB instance
	mongoDB, err := db.NewMongoDB()
	if err != nil {
		fmt.Printf("Failed to create test MongoDB instance: %v", err)
	}
	defer mongoDB.Client.Disconnect(ctx)

	// プロファイルの停止処理をシグナル受信時に行う
	go func() {
		sig := <-sigChan
		fmt.Printf("Received signal: %v, stopping CPU profile...\n", sig)

		if *cpuprofile != "" {
			pprof.StopCPUProfile()
			if f != nil {
				f.Close()
			}
		}

		if *memprofile != "" {
			mf, err := os.Create(*memprofile)
			if err != nil {
				log.Fatal("could not create memory profile: ", err)
			}
			defer mf.Close()
			runtime.GC() // get up-to-date statistics
			if err := pprof.WriteHeapProfile(mf); err != nil {
				log.Fatal("could not write memory profile: ", err)
			}
		}
		os.Exit(0)
	}()

	if *cacheparam != "" {

		simulaterDefinitionBytes, _ := os.ReadFile(*cacheparam)

		var simulatorDefinition interface{}
		var err = json5.Unmarshal(simulaterDefinitionBytes, &simulatorDefinition)
		if err != nil {
			panic(err)
		}
		simDef := simulator.InitializedSimulatorDefinition(simulatorDefinition)
		interval := simDef.Interval
		simDef.Rule = *rulefile
		// fp, _ := os.Open(rulefile)

		cacheSim, err := simulator.BuildSimpleCacheSimulator(simDef, *rulefile)

		if err != nil {
			panic(err)
		}

		runSimpleCacheSimulatorWithPackets(&packets, cacheSim, int(interval), 0, *bench)
		fmt.Printf("%v\n", cacheSim.GetStatString())
	} else {
		wg := new(sync.WaitGroup)
		queue := make(chan simulator.SimpleCacheSimulator, 4)

		// キャッシュ容量の範囲を取得

		// キャッシュ容量のスタートを定義
		capacityStart, err := strconv.Atoi(os.Getenv("CAPACITY_START"))
		if err != nil {
			panic(err)
		}

		// キャッシュ容量のエンドを定義
		capacityEnd, err := strconv.Atoi(os.Getenv("CAPACITY_END"))
		if err != nil {
			panic(err)
		}

		// キャッシュ容量の倍率を定義
		capacityMultiplier, err := strconv.Atoi(os.Getenv("CAPACITY_MULTIPLIER"))
		if err != nil {
			panic(err)
		}

		// キャッシュ容量のリストを生成
		capacity := make([]int, 0, 30)
		for i := capacityStart; i <= capacityEnd; i++ {
			capacity = append(capacity, 1<<uint(i*capacityMultiplier))
		}

		fmt.Print("capacity: ")
		for _, c := range capacity {
			fmt.Print(c, ",")
		}

		traceFileName := filepath.Base(*trace)

		var ruleFileName string
		var totalTask int

		cachetype := os.Getenv("CACHE_TYPE")
		var baseSimulatorDefinition simulator.SimulatorDefinition

		packetlen := uint64(len(packets))
		if *maxProccess != 0 {
			packetlen = *maxProccess
		}

		fmt.Printf("packetlen: %v\n", packetlen)

		// タスクの総数に基づいてWaitGroupを設定

		// ワーカーゴルーチンを生成
		var completedTasks int
		var totalDuration time.Duration
		var mu sync.Mutex // 進捗状況を守るためのMutex

		for i := 0; i < runtime.NumCPU()-3; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				for sim := range queue {
					tempsim := sim

					param, err := tempsim.SimDefinition.GetParameter()
					if err != nil {
						panic(err)
					}

					ruleFileName = filepath.Base(*rulefile)

					ex, err := mongoDB.IsResultExist(ctx,
						param,
						packetlen,
						tempsim.SimDefinition.Cache.Type,
						ruleFileName,
						traceFileName)

					// err の場合と
					if err != nil {
						// エラーが発生した場合、エラーハンドリングを行う
						panic(err)
					}
					startTime := time.Now()
					// resultが存在する場合にはスキップ

					if ex == nil || *forceupdate {

						// 実際のシミュレーション処理
						stat := runSimpleCacheSimulatorWithPackets(&packets, &sim, int(tempsim.SimDefinition.Interval), packetlen, *bench)
						fmt.Println(stat)
						err = mongoDB.InsertResult(ctx, stat, ruleFileName, traceFileName)
						if err != nil {
							// 挿入中にエラーが発生した場合、エラーハンドリングを行う
							panic(err)
						}

					} else {
						fmt.Print("skip because Data founded\n")
					}
					mu.Lock()

					duration := time.Since(startTime)
					completedTasks++
					totalDuration += duration
					avgDuration := totalDuration / time.Duration(completedTasks)

					fmt.Printf("Task %d / %dcompleted, Average time per task: %v\n", completedTasks, totalTask, avgDuration)

					// forceupdate が true またはデータが存在しない場合に挿入

					mu.Unlock()
					// filename := generateFileName()
					// memorytrace.WriteDRAMAccessesToFile(filename)
				}
			}()
		}
		if cachetype == "LRU" {
			baseSimulatorDefinition, err = simulator.NewSimulatorDefinition("LRU")
			if err != nil {
				panic(err)
			}

			totalTask = len(capacity)

			for i, c := range capacity {
				if i > *skip {
					newSim := simulator.CreateSimulatorWithCapacity(baseSimulatorDefinition, c)
					fmt.Print("newSim: ")
					newSim.Interval = 100000000000
					cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile)
					fmt.Print("cacheSim: ")
					if err != nil {
						panic(err)
					}
					queue <- *cacheSim
				}
			}

		} else if cachetype == "MultiLayerCacheExclusive" {
			baseSimulatorDefinition, err = simulator.NewSimulatorDefinition("MultiLayerCacheExclusive")

			// ruleFileName := filepath.Base(*rulefile)
			// settings,err := mongoDB.GetForDepth(
			// 	ctx,
			// 	ruleFileName,
			// 	traceFileName,
			// )
			// if err != nil {
			// 	panic(err)
			// }

			refbitsRange := make([]int, 0, 32)
			// cachenumを反映
			for i := 2; i < *cachenum; i++ {
				baseSimulatorDefinition.AddCacheLayer(nil)
			}
			// refbitsStart, err := strconv.Atoi(os.Getenv("REFBITS_START"))
			// if err != nil {
			// 	panic(err)
			// }
			// refbitsEnd, err := strconv.Atoi(os.Getenv("REFBITS_END"))
			// if err != nil {
			// 	panic(err)
			// }

			// refbitsMultiplier, err := strconv.Atoi(os.Getenv("REFBITS_MULTIPLIER"))
			// if err != nil {
			// 	panic(err)
			// }
			// for i := 8; i <= 15; i = i + 3 {
			// 	refbitsRange = append(refbitsRange, i)
			// }
			// for i := 16; i <= 24; i++ {
			// 	refbitsRange = append(refbitsRange, i)
			// }
			for i := 1; i <= 32; i++  {
				refbitsRange = append(refbitsRange, i)
			}

			fmt.Printf("refbitsRange: %v\n", refbitsRange)

			settngs := simulator.GenerateCapacityAndRefbitsPermutations(capacity, refbitsRange, *cachenum)
			fmt.Printf("%v \n", settngs)
			debugmode := false
			totalTask := len(settngs)

			fmt.Println("Total tasks:", totalTask)

			fmt.Printf("rulefile:%v", rulefile)
			fmt.Printf("traceFileName: %v, ruleFileName: %v\n", traceFileName, ruleFileName)

			for i, setting := range settngs {
				if i > *skip {
					newSim := simulator.CreateSimulatorWithCapacityAndRefbits(baseSimulatorDefinition, setting)
					newSim.DebugMode = debugmode

					newSim.Interval = 100000000000
					cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile)

					if err != nil {
						panic(err)
					}
					queue <- *cacheSim
				}
			}
			// 各タスクに対してWaitGroupを増加させ、キューに送信
			// for i, setting := range settings {
			// 	if i > *skip {
			// 	baseSimulatorDefinition, err := simulator.NewSimulatorDefinition("MultiLayerCacheExclusive")
			// 	if err != nil {

			// 		panic(err)
			// 	}
			// 	if(len(setting) == 3){
			// 		baseSimulatorDefinition.AddCacheLayer(nil);

			// 	}
			// 		newSim := simulator.CreateSimulatorWithCapacityAndRefbits(baseSimulatorDefinition, setting)
			// 		newSim.DebugMode = false

			// 		newSim.Interval = 100000000
			// 		cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile)

			// 		if err != nil {
			// 			panic(err)
			// 		}
			// 		queue <- *cacheSim
			// 	}
			// }

		} else {
			panic("not supported cache type")
		}

		// 全タスクの終了を待つ
		close(queue)
		wg.Wait()

		if err != nil {
			fmt.Println("ファイルへの書き込みエラー:", err)
		}

		fmt.Printf("All tasks completed, total tasks: %d, average time per task: %v\n", completedTasks, totalDuration/time.Duration(completedTasks))
	}

	// シミュレーションの後にプロファイル停止（通常終了時）
	if *cpuprofile != "" {
		pprof.StopCPUProfile()
		if f != nil {
			f.Close()
		}
	}

	if *memprofile != "" {
		mf, err := os.Create(*memprofile)
		if err != nil {
			log.Fatal("could not create memory profile: ", err)
		}
		defer mf.Close()
		runtime.GC() // get up-to-date statistics
		if err := pprof.WriteHeapProfile(mf); err != nil {
			log.Fatal("could not write memory profile: ", err)
		}
	}
}
