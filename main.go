package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha1"
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
	"test-module/memorytrace"
	"test-module/routingtable"
	"test-module/simulator"
	"time"
	"unicode"

	"encoding/gob"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
	"github.com/google/gopacket/pcap"

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
var recordCacheHit = flag.Bool("recordCachehit", false, " record cache hit")
var cacheTypeFlag = flag.String("cachetype", "UnifiedCache", "cache type (LRU, FullLRU, FullAssociativeLRUCache, MultiLayerCacheExclusive, MultiLayerCacheInclusive, UnifiedCache)")
var capacityStartFlag = flag.Int("capacity-start", 10, "start of log2 cache capacity range (inclusive)")
var capacityEndFlag = flag.Int("capacity-end", 10, "end of log2 cache capacity range (inclusive)")
var capacityStepFlag = flag.Int("capacity-step", 1, "step of log2 cache capacity range")
var capacityValuesFlag = flag.String("capacity-values", "", "comma-separated exact cache capacities; overrides capacity range")
var refbitsStartFlag = flag.Int("refbits-start", 32, "start of refbits range (inclusive)")
var refbitsEndFlag = flag.Int("refbits-end", 32, "end of refbits range (inclusive)")
var refbitsStepFlag = flag.Int("refbits-step", 1, "step of refbits range")
var mpRefbitsFlag = flag.String("mp-refbits", "", "comma-separated fixed refbits for MultiLayerCacheExclusive, for example 24,20,16")
var mpCapacitiesFlag = flag.String("mp-capacities", "", "comma-separated fixed capacities for MultiLayerCacheExclusive, for example 2048,2048,2048")
var wayFlag = flag.String("way", "4", "cache way for associative caches; UnifiedCache also accepts full")
var cacheIndexTypeFlag = flag.Int("cache-index-type", 5, "cache index type for UnifiedCache")
var cacheTagLengthFlag = flag.String("cache-tag-length", "9-24", "cache tag length ranges for UnifiedCache (min-max, /N, or comma separated one per way)")
var cacheInsertionPolicyFlag = flag.String("cache-insertion-policy", cache.UnifiedCacheInsertionPolicyExclusive, "UnifiedCache insertion policy (exclusive or inclusive)")
var cacheIndexPolicyFlag = flag.String("cache-index-policy", cache.UnifiedCacheIndexPolicyFixed, "UnifiedCache index policy (fixed, last-inserted-prefix, or epoch-most-frequent-prefix)")
var adaptiveIndexInitialFlag = flag.Int("adaptive-index-initial", 18, "initial index prefix length for adaptive UnifiedCache index policy")
var adaptiveIndexMinFlag = flag.Int("adaptive-index-min", 6, "minimum index prefix length for adaptive UnifiedCache index policy")
var adaptiveIndexMaxFlag = flag.Int("adaptive-index-max", 24, "maximum index prefix length for adaptive UnifiedCache index policy")
var adaptiveIndexEpochLengthFlag = flag.Int("adaptive-index-epoch-length", 1024, "accesses per epoch for epoch-most-frequent-prefix policy")
var lengthAwareMultiProbeFlag = flag.Bool("length-aware-multi-probe", false, "probe length-specific UnifiedCache sets in parallel")
var multiProbeLengthsFlag = flag.String("multi-probe-lengths", "18,20,22,24", "comma-separated prefix lengths for length-aware multi-probe")
var wayQuotaWideMaxFlag = flag.Int("way-quota-wide-max", 18, "largest prefix length in the reserved wide-prefix way group")
var wayQuotaWideWaysFlag = flag.Int("way-quota-wide-ways", 0, "ways reserved for wide prefixes; zero disables way quota")
var skewedAssociativeFlag = flag.Bool("skewed-associative", false, "use two independent candidate-set hashes and insert into the emptier set")
var setExtensionPolicyFlag = flag.String("set-extension-policy", cache.UnifiedCacheSetExtensionOff, "UnifiedCache set extension policy (off or epoch-full-repeat-miss)")
var setExtensionCapacityModeFlag = flag.String("set-extension-capacity-mode", cache.UnifiedCacheSetExtensionAdditive, "UnifiedCache set extension capacity mode (fixed-total or additive)")
var setExtensionPoolRatioFlag = flag.Float64("set-extension-pool-ratio", 0.125, "fraction of nominal capacity reserved/added as extension sets")
var setExtensionEpochLengthFlag = flag.Int("set-extension-epoch-length", 4096, "lookups per set-extension pressure epoch")
var setExtensionPressureThresholdFlag = flag.Uint64("set-extension-pressure-threshold", 8, "full repeat misses required to allocate an extension set")
var setExtensionMaxPerSetFlag = flag.Int("set-extension-max-per-set", 2, "maximum extension sets assigned to one logical set")
var logIPFlag = flag.Bool("logip", false, "write UnifiedCache top second-miss IP/prefix CSV")
var logIPTopFlag = flag.Int("logip-top", 100, "number of UnifiedCache second-miss IP/prefix records to write")
var logIPOutputDirFlag = flag.String("logip-output-dir", "scripts/reports/unified_second_miss_ip", "output directory for -logip CSV files")
var logLengthFlag = flag.Bool("loglength", false, "write UnifiedCache resident entry Length distribution CSV")
var logLengthOutputDirFlag = flag.String("loglength-output-dir", "scripts/reports/unified_cache_length", "output directory for -loglength CSV files")
var dramRequestTraceOutputDirFlag = flag.String("dram-request-trace-dir", "", "write request-level DRAM trace CSV files into this directory")
var routingTable *routingtable.RoutingTablePatriciaTrie

const gobProgressInterval = 10_000_000

func init() {
	// routingtable.Data 型の登録

	flag.Parse()
	debug.SetGCPercent(50)
	gob.Register(routingtable.Data{})

	gobPath := buildGobPath(*rulefile, *trace)
	gobdebugmode := false
	ext := filepath.Ext(*trace)
	fpRule, err := os.Open(*rulefile)
	if err != nil {
		panic(err)
	}
	routingTable = routingtable.NewRoutingTablePatriciaTrie()
	routingTable.ReadRule(fpRule)
	fpRule.Close()
	// gobPathファイルが存在するか確認

	if _, err := os.Stat(gobPath); err == nil && !gobdebugmode {
		// gobファイルが存在する場合、デコードする
		fmt.Println("gobファイルが見つかりました。デコード中...")
		packets = decodeGobFile(gobPath)
	} else if os.IsNotExist(err) || gobdebugmode {
		// gobファイルが存在しない場合、通常の処理を行う
		if !gobdebugmode {
			fmt.Println("gobファイルが見つかりません。新しいファイルを生成中...")
			fmt.Printf("作成するgobファイル名: %s\n", filepath.Base(gobPath))
		} else {
			fmt.Println("debugmode で実行中")
		}

		switch ext {
		case ".csv", ".tsv", ".p7", ".data", ".txt":
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

			totalPackets := 0
			for {
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
				totalPackets++
				if totalPackets%gobProgressInterval == 0 {
					fmt.Printf("gob変換進捗: %d パケット処理済み (有効: %d)\n", totalPackets, len(packets))
					if gobdebugmode {
						break
					}
				}

				packet, err := parseCSVRecordToMinPacket(record, routingTable)

				if err != nil {
					continue
				}

				if packet.FiveTuple() == nil {
					continue
				}
				packets = append(packets, *packet)
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
			// メタデータを表示
			fmt.Printf("PCAP File Metadata:\n")
			fmt.Printf("LinkType: %v\n", handle.LinkType())
			fmt.Printf("SnapLen: %d\n", handle.SnapLen())

			isLinkTypeRaw := false
			if layers.LinkType(handle.LinkType()) == layers.LinkTypeRaw {
				isLinkTypeRaw = true
			}

			fmt.Printf("isLinkTypeRaw: %v\n", isLinkTypeRaw)

			// range over the channel (only one iteration variable is allowed)
			totalPackets := 0
			num_minpackets := 0
			for packet := range packetSource.Packets() {
				totalPackets++
				if totalPackets%gobProgressInterval == 0 {
					fmt.Printf("gob変換進捗: %d パケット処理済み (有効: %d)\n", totalPackets, num_minpackets)
				}
				minPacket, err := parsePcapPacketToMinPacket(packet, routingTable, isLinkTypeRaw)
				if err != nil {
					// エラーでてもcontinueしない
					continue
				}
				if minPacket.FiveTuple() == nil {

					continue
				}

				packets = append(packets, *minPacket)
				num_minpackets++
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

func buildGobPath(rulePath string, tracePath string) string {
	ruleName := strings.TrimSuffix(filepath.Base(rulePath), filepath.Ext(rulePath))
	traceName := strings.TrimSuffix(filepath.Base(tracePath), filepath.Ext(tracePath))
	gobFileName := fmt.Sprintf("%s_%s.gob", sanitizeFileName(ruleName), sanitizeFileName(traceName))
	gobDir := strings.TrimSpace(os.Getenv("GOB_PACKET_DIR"))
	if gobDir == "" {
		gobDir = "gob-packet"
	}
	return filepath.Join(gobDir, gobFileName)
}

func sanitizeFileName(name string) string {
	sanitized := strings.Map(func(r rune) rune {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' {
			return r
		}
		return '-'
	}, name)

	sanitized = strings.Trim(sanitized, "-_")
	if sanitized == "" {
		return "unknown"
	}
	return sanitized
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

	if recordProtoStr == "0x00" {
		fmt.Printf("recordProtoStr: %v\n", record)
		return nil, fmt.Errorf("recordProtoStr is 0x00")
	}

	srcip := net.ParseIP(recordSrcIPStr)
	if srcip == nil {
		return nil, fmt.Errorf("srcip is nil")
	}
	packet.SrcIP = IpToUInt32(srcip)

	dstip := net.ParseIP(recordDstIPStr)
	if dstip == nil {
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
func parsePcapPacketToMinPacket(packet gopacket.Packet, r *routingtable.RoutingTablePatriciaTrie, isRawType bool) (*cache.MinPacket, error) {
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
	// ipuint32src := IpToUInt32(ip.SrcIP)
	// ipuint32dst := IpToUInt32(ip.DstIP)

	// fmt.Println(ipaddress.NewIPaddress(ipuint32src).String())
	// fmt.Println(ipaddress.NewIPaddress(ipuint32dst).String())
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
		sim.Process(packet, *recordCacheHit)
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
		sim.Process(packet, *recordCacheHit)
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

func runSimpleCacheSimulatorWithPackets(packetList *[]MinPacket, sim *simulator.SimpleCacheSimulator, printInterval int, maxProccess uint64, bench bool, recordCacheHit bool) simulator.SimulatorResult {

	var file *os.File
	if recordCacheHit {
		fmt.Print("recordCacheHit is true\n")
		paramString := sim.Parameter().GetParameterString()
		// hasCacheLayers := false
		// if _, ok := paramString["CacheLayers"]; ok {
		// 	hasCacheLayers = true
		// }
		var paramStringStr = ""

		for k, p := range paramString {
			if k == "Type" {
				// paramStringStr += fmt.Sprintf("%s-", p)
				continue
			} else if k == "CacheLayers" {
				for _, cacheparam := range p.([]Parameter) {
					cp := cacheparam.GetParameterString()
					for kk, pp := range cp {
						if kk == "Type" {
							paramStringStr += fmt.Sprintf("%s-", pp.(string)[:5])
						} else {
							paramStringStr += fmt.Sprintf("%s-", pp)
						}
					}

				}
			} else if k == "CachePolicies" {
				continue
			} else {
				paramStringStr += fmt.Sprintf("%s-", p)
			}
		}

		// ファイル名に使えない文字をハイフンに置換
		safeParamString := strings.Map(func(r rune) rune {
			if unicode.IsLetter(r) || unicode.IsDigit(r) {
				return r
			}
			return '-'
		}, paramStringStr)

		// 連続するハイフンを1つにまとめる
		safeParamString = strings.ReplaceAll(safeParamString, "--", "-")
		for strings.Contains(safeParamString, "--") {
			safeParamString = strings.ReplaceAll(safeParamString, "--", "-")
		}
		// 先頭のハイフンを取り除く
		safeParamString = strings.TrimLeft(safeParamString, "-")
		if len(safeParamString) > 180 {
			sum := sha1.Sum([]byte(safeParamString))
			safeParamString = strings.TrimRight(safeParamString[:160], "-") + fmt.Sprintf("-%x", sum[:6])
		}

		var err error
		filePath := filepath.Join("cachehitrace", safeParamString+".txt")
		// Ensure the directory exists
		if err := os.MkdirAll(filepath.Dir(filePath), 0755); err != nil {
			panic(err)
		}
		file, err = os.Create(filePath)
		if err != nil {
			panic(err)
		}
		defer file.Close()
	}

	for _, p := range *packetList {

		start := time.Now()
		hit := sim.Process(&p, recordCacheHit)
		elapsed := time.Since(start)

		if recordCacheHit {
			dstIp := ipaddress.NewIPaddress(p.DstIP).String()

			if hit {
				// hit or miss とdstipを書き込む
				_, err := file.WriteString(fmt.Sprintf("hit %v\n", dstIp))
				if err != nil {
					panic(err)
				}
			} else {
				// miss とdstipを書き込む
				_, err := file.WriteString(fmt.Sprintf("miss %v\n", dstIp))
				if err != nil {
					panic(err)
				}
			}
		}

		if sim.GetStat().Processed%printInterval == 0 {

			fmt.Printf("sim process time: %s\n", elapsed)
			fmt.Printf("%v\n", sim.GetStatString())
		}
		if sim.GetStat().Processed == 10000 && bench {
			break
		}
		if maxProccess != 0 && uint64(sim.GetStat().Processed) == maxProccess {
			break
		}
	}
	stat := sim.GetSimulatorResult()
	if sim.Tracer != nil {
		traceEnabled := sim.Tracer.Enabled()
		traceStats := sim.Tracer.Stats()
		if traceEnabled {
			if err := sim.Tracer.Close(); err != nil {
				panic(err)
			}
			fmt.Printf(
				"DRAM request trace stats: accesses=%d reads=%d writes=%d first_cycle=%d last_cycle=%d\n",
				traceStats.Accesses,
				traceStats.Reads,
				traceStats.Writes,
				traceStats.FirstCycle,
				traceStats.LastCycle,
			)
		}
		sim.Tracer.Reset()
	} else {
		memorytrace.Reset()
	}
	return stat

}

func safeFileNamePart(value string) string {
	safe := strings.Map(func(r rune) rune {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			return r
		}
		return '-'
	}, value)
	for strings.Contains(safe, "--") {
		safe = strings.ReplaceAll(safe, "--", "-")
	}
	safe = strings.Trim(safe, "-")
	if safe == "" {
		return "unknown"
	}
	return safe
}

func dramRequestTraceRequested() bool {
	return strings.TrimSpace(*dramRequestTraceOutputDirFlag) != ""
}

func configureDRAMRequestTrace(sim *simulator.SimpleCacheSimulator, ruleFileName string, traceFileName string) (string, error) {
	outputDir := strings.TrimSpace(*dramRequestTraceOutputDirFlag)
	if outputDir == "" {
		return "", nil
	}
	if sim.Tracer == nil {
		sim.Tracer = memorytrace.NewTracer()
	}

	paramName := safeFileNamePart(sim.Cache.ParameterString())
	fileName := fmt.Sprintf(
		"dram_requests_%s_%s_%s_%s.csv",
		safeFileNamePart(ruleFileName),
		safeFileNamePart(traceFileName),
		paramName,
		time.Now().Format("20060102T150405.000000000"),
	)
	filePath := filepath.Join(outputDir, fileName)
	if err := sim.Tracer.OpenCSV(filePath); err != nil {
		return "", err
	}
	return filePath, nil
}

func writeUnifiedSecondMissIPReport(sim *simulator.SimpleCacheSimulator, ruleFileName string, traceFileName string) (string, error) {
	if *logIPTopFlag <= 0 {
		return "", fmt.Errorf("-logip-top must be greater than 0")
	}

	unifiedCache, ok := sim.Cache.(*cache.UnifiedCache)
	if !ok {
		return "", nil
	}

	records := unifiedCache.TopSecondMissIPRecords(*logIPTopFlag)
	if err := os.MkdirAll(*logIPOutputDirFlag, 0755); err != nil {
		return "", err
	}

	fileName := fmt.Sprintf(
		"second_miss_ip_%s_%s_cap%d_way%d_index%d_top%d_%s.csv",
		safeFileNamePart(ruleFileName),
		safeFileNamePart(traceFileName),
		unifiedCache.Size,
		unifiedCache.Way,
		unifiedCache.CacheIndexType,
		*logIPTopFlag,
		time.Now().Format("20060102T150405.000000000"),
	)
	filePath := filepath.Join(*logIPOutputDirFlag, fileName)

	file, err := os.Create(filePath)
	if err != nil {
		return "", err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"rank",
		"capacity",
		"way",
		"cache_index_type",
		"set_idx",
		"prefix_len",
		"network",
		"network_key",
		"second_miss_count",
		"rule_file_name",
		"trace_file_name",
	}
	if err := writer.Write(header); err != nil {
		return "", err
	}

	for i, record := range records {
		row := []string{
			strconv.Itoa(i + 1),
			strconv.FormatUint(uint64(unifiedCache.Size), 10),
			strconv.FormatUint(uint64(unifiedCache.Way), 10),
			strconv.Itoa(unifiedCache.CacheIndexType),
			strconv.Itoa(record.SetIndex),
			strconv.Itoa(record.PrefixLen),
			record.NetworkCIDR,
			strconv.FormatUint(uint64(record.Network), 10),
			strconv.FormatUint(uint64(record.Count), 10),
			ruleFileName,
			traceFileName,
		}
		if err := writer.Write(row); err != nil {
			return "", err
		}
	}
	if err := writer.Error(); err != nil {
		return "", err
	}

	return filePath, nil
}

func writeUnifiedCacheLengthReport(sim *simulator.SimpleCacheSimulator, ruleFileName string, traceFileName string) (string, error) {
	unifiedCache, ok := sim.Cache.(*cache.UnifiedCache)
	if !ok {
		return "", nil
	}

	if err := os.MkdirAll(*logLengthOutputDirFlag, 0755); err != nil {
		return "", err
	}

	fileName := fmt.Sprintf(
		"cache_length_%s_%s_cap%d_way%d_index%d_%s.csv",
		safeFileNamePart(ruleFileName),
		safeFileNamePart(traceFileName),
		unifiedCache.Size,
		unifiedCache.Way,
		unifiedCache.CacheIndexType,
		time.Now().Format("20060102T150405.000000000"),
	)
	filePath := filepath.Join(*logLengthOutputDirFlag, fileName)

	file, err := os.Create(filePath)
	if err != nil {
		return "", err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	header := []string{
		"scope",
		"capacity",
		"way",
		"cache_index_type",
		"set_idx",
		"length",
		"entry_count",
		"refered_sum",
		"rule_file_name",
		"trace_file_name",
	}
	if err := writer.Write(header); err != nil {
		return "", err
	}

	writeRecord := func(scope string, record cache.UnifiedCacheLengthRecord) error {
		setIndex := ""
		if record.SetIndex >= 0 {
			setIndex = strconv.Itoa(record.SetIndex)
		}
		return writer.Write([]string{
			scope,
			strconv.FormatUint(uint64(unifiedCache.Size), 10),
			strconv.FormatUint(uint64(unifiedCache.Way), 10),
			strconv.Itoa(unifiedCache.CacheIndexType),
			setIndex,
			strconv.Itoa(record.Length),
			strconv.Itoa(record.EntryCount),
			strconv.Itoa(record.ReferedSum),
			ruleFileName,
			traceFileName,
		})
	}

	for _, record := range unifiedCache.LengthSummaryRecords() {
		if err := writeRecord("summary", record); err != nil {
			return "", err
		}
	}
	for _, record := range unifiedCache.LengthBySetRecords() {
		if err := writeRecord("set", record); err != nil {
			return "", err
		}
	}
	if err := writer.Error(); err != nil {
		return "", err
	}

	return filePath, nil
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

func buildRange(start int, end int, step int, rangeName string) ([]int, error) {
	if step <= 0 {
		return nil, fmt.Errorf("%s-step must be greater than 0", rangeName)
	}
	if start > end {
		return nil, fmt.Errorf("%s-start must be less than or equal to %s-end", rangeName, rangeName)
	}

	result := make([]int, 0, ((end-start)/step)+1)
	for i := start; i <= end; i += step {
		result = append(result, i)
	}
	return result, nil
}

func parseIntCSV(spec string, name string) ([]int, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return nil, nil
	}
	parts := strings.Split(spec, ",")
	result := make([]int, 0, len(parts))
	for _, raw := range parts {
		part := strings.TrimSpace(raw)
		if part == "" {
			return nil, fmt.Errorf("%s contains an empty item", name)
		}
		value, err := strconv.Atoi(part)
		if err != nil {
			return nil, fmt.Errorf("invalid %s item %q: %w", name, part, err)
		}
		if value <= 0 {
			return nil, fmt.Errorf("%s item must be greater than 0: %d", name, value)
		}
		result = append(result, value)
	}
	return result, nil
}

func parseFixedMPSetting(refbitsSpec string, capacitiesSpec string, cacheNum int) ([][2]int, error) {
	if strings.TrimSpace(refbitsSpec) == "" && strings.TrimSpace(capacitiesSpec) == "" {
		return nil, nil
	}
	if strings.TrimSpace(refbitsSpec) == "" || strings.TrimSpace(capacitiesSpec) == "" {
		return nil, fmt.Errorf("mp-refbits and mp-capacities must be specified together")
	}
	refbits, err := parseIntCSV(refbitsSpec, "mp-refbits")
	if err != nil {
		return nil, err
	}
	capacities, err := parseIntCSV(capacitiesSpec, "mp-capacities")
	if err != nil {
		return nil, err
	}
	if len(refbits) != cacheNum {
		return nil, fmt.Errorf("mp-refbits item count (%d) must match cachenum (%d)", len(refbits), cacheNum)
	}
	if len(capacities) != cacheNum {
		return nil, fmt.Errorf("mp-capacities item count (%d) must match cachenum (%d)", len(capacities), cacheNum)
	}
	for i := 1; i < len(refbits); i++ {
		if refbits[i] >= refbits[i-1] {
			return nil, fmt.Errorf("mp-refbits must be strictly descending: %v", refbits)
		}
	}
	setting := make([][2]int, cacheNum)
	for i := range setting {
		setting[i] = [2]int{capacities[i], refbits[i]}
	}
	return setting, nil
}

func parseCacheTagLengthSpec(spec string, way int) ([][2]int, error) {
	if way <= 0 {
		return nil, fmt.Errorf("way must be greater than 0")
	}

	parts := strings.Split(spec, ",")
	if len(parts) != 1 && len(parts) != way {
		return nil, fmt.Errorf("cache-tag-length item count (%d) must be 1 or match way (%d)", len(parts), way)
	}

	result := make([][2]int, 0, len(parts))
	for _, raw := range parts {
		part := strings.TrimSpace(raw)
		if part == "" {
			return nil, fmt.Errorf("cache-tag-length contains an empty item")
		}

		if strings.HasPrefix(part, "/") {
			part = strings.TrimPrefix(part, "/")
		}

		var minVal int
		var maxVal int
		minMax := strings.Split(part, "-")
		switch len(minMax) {
		case 1:
			value, err := strconv.Atoi(strings.TrimSpace(minMax[0]))
			if err != nil {
				return nil, fmt.Errorf("invalid value in cache-tag-length item %q: %w", part, err)
			}
			minVal = value
			maxVal = value
		case 2:
			var err error
			minVal, err = strconv.Atoi(strings.TrimSpace(minMax[0]))
			if err != nil {
				return nil, fmt.Errorf("invalid min value in cache-tag-length item %q: %w", part, err)
			}
			maxVal, err = strconv.Atoi(strings.TrimSpace(minMax[1]))
			if err != nil {
				return nil, fmt.Errorf("invalid max value in cache-tag-length item %q: %w", part, err)
			}
		default:
			return nil, fmt.Errorf("invalid cache-tag-length item %q: expected min-max or /N", part)
		}

		if minVal < 0 || maxVal > 32 || minVal > maxVal {
			return nil, fmt.Errorf("cache-tag-length item %q must satisfy 0 <= min <= max <= 32", part)
		}

		result = append(result, [2]int{minVal, maxVal})
	}

	return result, nil
}

func isUnifiedFullAssociativeWaySpec(spec string) bool {
	switch strings.ToLower(strings.TrimSpace(spec)) {
	case "full", "full-associative", "full_associative":
		return true
	default:
		return false
	}
}

func parseFixedWaySpec(spec string) (int, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return 0, fmt.Errorf("way must not be empty")
	}
	if isUnifiedFullAssociativeWaySpec(spec) {
		return 0, fmt.Errorf("way=%s is only valid for UnifiedCache", spec)
	}
	way, err := strconv.Atoi(spec)
	if err != nil {
		return 0, fmt.Errorf("way must be an integer: %s", spec)
	}
	if way <= 0 {
		return 0, fmt.Errorf("way must be greater than 0")
	}
	return way, nil
}

func resolveUnifiedCacheWaySpec(spec string, capacity int) (int, error) {
	if capacity <= 0 {
		return 0, fmt.Errorf("capacity must be greater than 0")
	}
	if isUnifiedFullAssociativeWaySpec(spec) {
		return capacity, nil
	}
	way, err := parseFixedWaySpec(spec)
	if err != nil {
		return 0, err
	}
	if capacity%way != 0 {
		return 0, fmt.Errorf("capacity (%d) must be divisible by way (%d) for UnifiedCache", capacity, way)
	}
	return way, nil
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
		log.Fatalf("Failed to initialize MongoDB: %v", err)
	}
	defer func() {
		if err := mongoDB.Client.Disconnect(ctx); err != nil {
			log.Printf("Failed to disconnect MongoDB: %v", err)
		}
	}()

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

		cacheSim, err := simulator.BuildSimpleCacheSimulator(simDef, *rulefile, routingTable)

		if err != nil {
			panic(err)
		}

		if tracePath, err := configureDRAMRequestTrace(cacheSim, filepath.Base(*rulefile), filepath.Base(*trace)); err != nil {
			panic(err)
		} else if tracePath != "" {
			fmt.Printf("Writing DRAM request trace: %s\n", tracePath)
		}

		runSimpleCacheSimulatorWithPackets(&packets, cacheSim, int(interval), 0, *bench, *recordCacheHit)
		runSimpleCacheSimulatorWithPackets(&packets, cacheSim, int(interval), 0, *bench, *recordCacheHit)
		fmt.Printf("%v\n", cacheSim.GetStatString())
	} else {
		wg := new(sync.WaitGroup)
		queue := make(chan simulator.SimpleCacheSimulator, 4)

		capacity := []int{}
		if strings.TrimSpace(*capacityValuesFlag) != "" {
			capacity, err = parseIntCSV(*capacityValuesFlag, "capacity-values")
			if err != nil {
				panic(err)
			}
			for _, value := range capacity {
				if value <= 0 {
					panic(fmt.Sprintf("capacity-values must be positive, got %d", value))
				}
			}
		} else {
			capacityRange, rangeErr := buildRange(*capacityStartFlag, *capacityEndFlag, *capacityStepFlag, "capacity")
			if rangeErr != nil {
				panic(rangeErr)
			}
			capacity = make([]int, 0, len(capacityRange))
			for _, c := range capacityRange {
				capacity = append(capacity, 1<<uint(c))
			}
		}

		fmt.Print("capacity: ")
		for _, c := range capacity {
			fmt.Print(c, ",")
		}

		traceFileName := filepath.Base(*trace)

		ruleFileName := filepath.Base(*rulefile)
		var totalTask int

		cachetype := strings.TrimSpace(*cacheTypeFlag)
		fmt.Println("var cachetype: ", cachetype)
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

		for i := 0; i < runtime.NumCPU(); i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				for sim := range queue {
					tempsim := sim

					param, err := tempsim.SimDefinition.GetParameter()
					if err != nil {
						panic(err)
					}

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

					shouldRun := ex == nil || *forceupdate || *logIPFlag || *logLengthFlag || dramRequestTraceRequested()
					shouldInsert := ex == nil || *forceupdate

					if shouldRun {

						if *forceupdate {
							fmt.Print("forceupdate is true\n")
						} else if (*logIPFlag || *logLengthFlag || dramRequestTraceRequested()) && ex != nil {
							fmt.Print("data found; rerun simulation for report output without DB insert\n")
						} else {
							fmt.Print("data not found\n")
						}
						if tracePath, err := configureDRAMRequestTrace(&sim, ruleFileName, traceFileName); err != nil {
							panic(err)
						} else if tracePath != "" {
							fmt.Printf("Writing DRAM request trace: %s\n", tracePath)
						}
						// 実際のシミュレーション処理
						stat := runSimpleCacheSimulatorWithPackets(&packets, &sim, int(tempsim.SimDefinition.Interval), packetlen, *bench, *recordCacheHit)
						if *logIPFlag {
							reportPath, err := writeUnifiedSecondMissIPReport(&sim, ruleFileName, traceFileName)
							if err != nil {
								panic(err)
							}
							if reportPath != "" {
								fmt.Printf("Saved second-miss IP report: %s\n", reportPath)
							}
						}
						if *logLengthFlag {
							reportPath, err := writeUnifiedCacheLengthReport(&sim, ruleFileName, traceFileName)
							if err != nil {
								panic(err)
							}
							if reportPath != "" {
								fmt.Printf("Saved cache Length report: %s\n", reportPath)
							}
						}
						sim.SimDefinition.Print()
						stat.Print()
						fmt.Println(param.GetParameterString())

						if shouldInsert {
							err = mongoDB.InsertResult(ctx, stat, ruleFileName, traceFileName)
							if err != nil {
								// 挿入中にエラーが発生した場合、エラーハンドリングを行う
								panic(err)
							}
						} else {
							fmt.Print("skip DB insert because Data founded and -dbupdate is false\n")
						}

					} else {
						fmt.Print("skip because Data founded\n")
						fmt.Println("param: ", param.GetParameterString())
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
					cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile, routingTable)
					fmt.Print("cacheSim: ")
					if err != nil {
						panic(err)
					}
					queue <- *cacheSim
				}
			}

		} else if cachetype == "FullLRU" || cachetype == "FullAssociativeLRUCache" {
			baseSimulatorDefinition, err = simulator.NewSimulatorDefinition("FullLRU")
			if err != nil {
				panic(err)
			}

			totalTask = len(capacity)

			for i, c := range capacity {
				if i > *skip {
					newSim := simulator.CreateSimulatorWithCapacity(baseSimulatorDefinition, c)
					fmt.Print("newSim: ")
					newSim.Interval = 100000000000
					cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile, routingTable)
					fmt.Print("cacheSim: ")
					if err != nil {
						panic(err)
					}
					queue <- *cacheSim
				}
			}
		} else if cachetype == "MultiLayerCacheExclusive" {
			fmt.Printf("cachetype: MultiLayerCacheExclusive\n")
			baseSimulatorDefinition, err = simulator.NewSimulatorDefinition("MultiLayerCacheExclusive")
			if err != nil {
				panic(err)
			}
			way, err := parseFixedWaySpec(*wayFlag)
			if err != nil {
				panic(err)
			}

			// ruleFileName := filepath.Base(*rulefile)
			// settings,err := mongoDB.GetForDepth(
			// 	ctx,
			// 	ruleFileName,
			// 	traceFileName,
			// )
			// if err != nil {
			// 	panic(err)
			// }

			refbitsRange, err := buildRange(*refbitsStartFlag, *refbitsEndFlag, *refbitsStepFlag, "refbits")
			if err != nil {
				panic(err)
			}
			// cachenumを反映
			for i := 1; i < *cachenum; i++ {
				baseSimulatorDefinition.AddCacheLayer(nil)
			}
			for i := range baseSimulatorDefinition.Cache.CacheLayers {
				baseSimulatorDefinition.Cache.CacheLayers[i].Way = way
			}

			fmt.Printf("refbitsRange: %v\n", refbitsRange)

			fixedMPSetting, err := parseFixedMPSetting(*mpRefbitsFlag, *mpCapacitiesFlag, *cachenum)
			if err != nil {
				panic(err)
			}
			var settngs [][][2]int
			if fixedMPSetting != nil {
				settngs = [][][2]int{fixedMPSetting}
				fmt.Printf("fixedMPSetting: %v\n", fixedMPSetting)
			} else {
				settngs = simulator.GenerateCapacityAndRefbitsPermutations(capacity, refbitsRange, *cachenum)
			}
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
					cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile, routingTable)

					if err != nil {
						panic(err)
					}
					queue <- *cacheSim
				}
			}

		} else if cachetype == "MultiLayerCacheInclusive" {

			baseSimulatorDefinition, err = simulator.NewSimulatorDefinition("MultiLayerCacheInclusive")
			if err != nil {
				panic(err)
			}
			way, err := parseFixedWaySpec(*wayFlag)
			if err != nil {
				panic(err)
			}
			refbitsRange, err := buildRange(*refbitsStartFlag, *refbitsEndFlag, *refbitsStepFlag, "refbits")
			if err != nil {
				panic(err)
			}
			// cachenumを反映
			for i := 1; i < *cachenum; i++ {
				baseSimulatorDefinition.AddCacheLayer(nil)
			}
			for i := range baseSimulatorDefinition.Cache.CacheLayers {
				baseSimulatorDefinition.Cache.CacheLayers[i].Way = way
			}

			onceCacheLimits := make([]int, 0, 128)
			for i := 0; i <= 8; i += 2 {
				onceCacheLimits = append(onceCacheLimits, i)
			}

			if err != nil {
				panic(err)
			}

			settngs := simulator.GenerateCapacityAndRefbitsPermutations(capacity, refbitsRange, *cachenum)
			fmt.Printf("%v \n", settngs)

			debugmodeEnv := os.Getenv("DEBUG_MODE")
			debugmode := false
			if debugmodeEnv == "true" || debugmodeEnv == "1" {
				debugmode = true
			}
			totalTask := len(settngs)

			fmt.Println("Total tasks:", totalTask)

			fmt.Printf("rulefile:%v", rulefile)
			fmt.Printf("traceFileName: %v, ruleFileName: %v\n", traceFileName, ruleFileName)

			for i, setting := range settngs {

				for _, onceCacheLimit := range onceCacheLimits {
					if i > *skip {
						newSim := simulator.CreateSimulatorWithCapacityAndRefbits(baseSimulatorDefinition, setting)
						newSim.DebugMode = debugmode
						newSim.Cache.OnceCacheLimit = onceCacheLimit

						newSim.Interval = 1000000000000000
						cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile, routingTable)

						if err != nil {
							panic(err)
						}
						queue <- *cacheSim
					}
				}
			}
		} else if "UnifiedCache" == cachetype {
			fmt.Printf("cachetype: UnifiedCache\n")

			baseSimulatorDefinition, err = simulator.NewSimulatorDefinition("UnifiedCache")
			if err != nil {
				panic(err)
			}

			cacheInsertionPolicy, err := cache.NormalizeUnifiedCacheInsertionPolicy(*cacheInsertionPolicyFlag)
			if err != nil {
				panic(err)
			}
			cacheIndexPolicy, err := cache.NormalizeUnifiedCacheIndexPolicy(*cacheIndexPolicyFlag)
			if err != nil {
				panic(err)
			}
			multiProbeLengths, err := parseIntCSV(*multiProbeLengthsFlag, "multi-probe-lengths")
			if err != nil {
				panic(err)
			}
			baseSimulatorDefinition.Cache.CacheIndexType = *cacheIndexTypeFlag
			baseSimulatorDefinition.Cache.InsertionPolicy = cacheInsertionPolicy
			baseSimulatorDefinition.Cache.IndexPolicy = cacheIndexPolicy
			baseSimulatorDefinition.Cache.LengthAwareMultiProbe = *lengthAwareMultiProbeFlag
			baseSimulatorDefinition.Cache.MultiProbeLengths = multiProbeLengths
			baseSimulatorDefinition.Cache.WayQuotaWideMax = *wayQuotaWideMaxFlag
			baseSimulatorDefinition.Cache.WayQuotaWideWays = *wayQuotaWideWaysFlag
			baseSimulatorDefinition.Cache.SkewedAssociative = *skewedAssociativeFlag
			baseSimulatorDefinition.Cache.AdaptiveInitial = *adaptiveIndexInitialFlag
			baseSimulatorDefinition.Cache.AdaptiveMin = *adaptiveIndexMinFlag
			baseSimulatorDefinition.Cache.AdaptiveMax = *adaptiveIndexMaxFlag
			baseSimulatorDefinition.Cache.AdaptiveEpochLength = *adaptiveIndexEpochLengthFlag
			setExtensionPolicy, err := cache.NormalizeUnifiedCacheSetExtensionPolicy(*setExtensionPolicyFlag)
			if err != nil {
				panic(err)
			}
			setExtensionCapacityMode, err := cache.NormalizeUnifiedCacheSetExtensionCapacityMode(*setExtensionCapacityModeFlag)
			if err != nil {
				panic(err)
			}
			baseSimulatorDefinition.Cache.SetExtensionPolicy = setExtensionPolicy
			baseSimulatorDefinition.Cache.SetExtensionCapacityMode = setExtensionCapacityMode
			baseSimulatorDefinition.Cache.SetExtensionPoolRatio = *setExtensionPoolRatioFlag
			baseSimulatorDefinition.Cache.SetExtensionEpochLength = *setExtensionEpochLengthFlag
			baseSimulatorDefinition.Cache.SetExtensionPressureThreshold = *setExtensionPressureThresholdFlag
			baseSimulatorDefinition.Cache.SetExtensionMaxPerSet = *setExtensionMaxPerSetFlag

			debugmodeEnv := os.Getenv("DEBUG_MODE")
			debugmode := false
			if debugmodeEnv == "true" || debugmodeEnv == "1" {
				debugmode = true
			}
			settings := capacity
			totalTask = len(settings)

			for i, setting := range settings {
				if i > *skip {
					way, err := resolveUnifiedCacheWaySpec(*wayFlag, setting)
					if err != nil {
						panic(err)
					}
					cacheTagLength, err := parseCacheTagLengthSpec(*cacheTagLengthFlag, way)
					if err != nil {
						panic(err)
					}
					newSim := simulator.CreateSimulatorWithCapacity(baseSimulatorDefinition, setting)
					newSim.Cache.Way = way
					newSim.Cache.CacheTagLength = cacheTagLength
					newSim.DebugMode = debugmode
					newSim.Interval = 100000000000
					cacheSim, err := simulator.BuildSimpleCacheSimulator(newSim, *rulefile, routingTable)
					if err != nil {
						panic(err)
					}
					queue <- *cacheSim
				}
			}

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
