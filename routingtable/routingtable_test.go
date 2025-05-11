package routingtable

import (
	"fmt"
	"os"
	"test-module/ipaddress"
	"testing"

	"github.com/tsuji1/go-patricia/patricia"
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
		routingTable.SearchLongestIP(dstIP, 16)

	}
}
func BenchmarkIsShorter(b *testing.B) {
	// テスト実施
	routingTable := initializeRoutingTable()
	for i := 0; i < b.N; i++ {

		dstIP := GetRandomDstIP()
		routingTable.IsShorter(dstIP, 32, 16)
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

func TestIsLeaf(t *testing.T) {
	// テスト実施
	fmt.Println("Test IsLeaf")
	routingTable := initializeRoutingTable()
	dstIP := GetRandomDstIP()
	fmt.Println(routingTable.IsLeaf(dstIP, 3))
}

func TestPatriciaTrie(t *testing.T) {
	t.Log("test Patricia trie")
	routingTable := initializeRoutingTable()
	refbits := 20
	dstIP := GetRandomDstIP()
	// 最初の3bitが111の場合は再生成
	for 0 <= refbits && refbits <= 32 && dstIP.BitString()[:3] == "111" {
		dstIP = GetRandomDstIP()
	}
	t.Log("dstIP:", dstIP.String())
	t.Log("dstIP masked:", dstIP.MaskedBitString(refbits))

	dstIPMaskedWithInt := dstIP.Uint32() & (0xFFFFFFFF << (32 - refbits))
	dstIPMasked := ipaddress.NewIPaddress(dstIPMaskedWithInt)
	t.Log("dstIPMasked:", dstIPMasked.String())

	prefix := patricia.Prefix(dstIP.MaskedBitString(refbits))

	l, found, leftover := routingTable.RoutingTablePatriciaTrie.FindSubtreePath(prefix)
	parent, root, _, _ := routingTable.RoutingTablePatriciaTrie.FindSubtree(prefix)

	t.Log("root:", root)
	t.Log("parent:", parent)

	visitoFunc := func(k patricia.Prefix, i patricia.Item) error {
		t.Log("VisitorFunc prefix:", ipaddress.BitStringToIP(string(k)), "item:", i, len(k))
		return nil
	}

	routingTable.RoutingTablePatriciaTrie.VisitSubtree(prefix, visitoFunc)

	p := ""
	for _, node := range l {
		p = p + string(node.GetPrefix())
	}
	// p はleftoverが末尾についているはずなので消したい
	p = p[:len(p)-len(leftover)]

	visitoFunc = func(k patricia.Prefix, i patricia.Item) error {
		t.Log("VisitorFunc2 prefix:", ipaddress.BitStringToIP(string(k)), "item:", i, "len:", len(k))
		return nil
	}
	routingTable.RoutingTablePatriciaTrie.VisitSubtree(patricia.Prefix(p), visitoFunc)

	t.Log("prefix:", p, "len:", len(p))

	t.Log(ipaddress.BitStringToIP(p))

	t.Log(found)

	t.Log(leftover)

}

// func TestPrintTrie(t *testing.T) {
// 	// テスト実施
// 	fmt.Println("Test PrintTrie")
// 	routingTable := initializeRoutingTable()
// 	routingTable.PrintTrie()
// }
