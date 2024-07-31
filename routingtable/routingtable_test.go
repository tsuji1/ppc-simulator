package routingtable

import (
	"os"
	"testing"
)

func initializeRoutingTable() *RoutingTablePatriciaTrie {
	// 初期化処理

	rulefile := "../rules/wide.rib.20240625.1400.rule"
	fp, err := os.Open(rulefile)
	if err != nil {
		panic(err)
	}
	defer fp.Close()

	routingTable := NewRoutingTablePatriciaTrie()
	routingTable.ReadRule(fp)
	return routingTable
}

func BenchmarkSearchLongestIP(b *testing.B) {
	// テスト実施
	routingTable := initializeRoutingTable()
	for i := 0; i < b.N; i++ {

		dstIP := GetRandomDstIP()
		routingTable.SearchLongestIP(dstIP, 3)

	}
}
func BenchmarkIsShorter(b *testing.B) {
	// テスト実施
	routingTable := initializeRoutingTable()
	for i := 0; i < b.N; i++ {

		dstIP := GetRandomDstIP()
		routingTable.IsShorter(dstIP, 32, 3)
	}
}


func BenchmarkIsLeaf(b *testing.B) {
	// テスト実施
	routingTable := initializeRoutingTable()
	for i := 0; i < b.N; i++ {

		dstIP := GetRandomDstIP()
		routingTable.IsLeaf(dstIP, 3)

	}

}
