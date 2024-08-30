package routingtable

import (
	"bufio"
	"fmt"
	"math/rand"
	"os"
	"strconv"
	"strings"
	"test-module/ipaddress"
	"time"

	"github.com/tchap/go-patricia/patricia"
	. "github.com/tchap/go-patricia/patricia"
)

// RoutingTablePatriciaTrie は、ルーティングテーブルのためのPatricia Trieを保持する構造体です。
type RoutingTablePatriciaTrie struct {
	RoutingTablePatriciaTrie *Trie
}

// Data は、ルーティング情報を深さとネクストホップで保持するデータ構造です。
type Data struct {
	Depth   uint64
	NextHop string
}

// PrintMatchRulesInfo は、指定されたIPアドレスと参照ビットに一致するルールの情報を出力します。
func (routingtable *RoutingTablePatriciaTrie) PrintMatchRulesInfo(ip ipaddress.IPaddress, refbits int) {
	hitted, _ := routingtable.SearchIP(ip, refbits, nil, nil)
	ans := "["
	for _, p := range hitted {
		ans += strconv.Itoa(len(p))
		ans += " "
	}
	ans += "],"
	ans += strconv.Itoa(int(routingtable.CountIPsInChildrenRule(ip, len(hitted[len(hitted)-1])))) // 最長一致ルールの子ノード数
	ans += ","
	ans += strconv.Itoa(int(routingtable.CountIPsInChildrenRule(ip, 24))) // /24にキャッシュするのに必要なIP数
	fmt.Println(ans)
}

// ReturnIPsInRule は、指定されたプレフィックスに含まれるすべてのIPアドレスを返します。
func (routingtable *RoutingTablePatriciaTrie) ReturnIPsInRule(prefix Prefix) []string {
	num_IPs := routingtable.CountIPsInRule(prefix)
	temp := ipaddress.NewIPaddress(string(prefix))
	start := temp.Uint32()
	var ans []string
	var i uint32
	for i = 0; i < num_IPs; i++ {
		temp.SetIP(start + i)
		ans = append(ans, temp.String())
	}
	return ans
}

// CountIPsInRule は、指定されたプレフィックスに含まれるIPアドレスの数を返します。
// 例えば、/24のプレフィックスに含まれるIPアドレスの数は256です。
func (routingtable *RoutingTablePatriciaTrie) CountIPsInRule(prefix Prefix) uint32 {
	prefix_length := len(prefix)
	var ans uint32
	ans = 1
	for i := 0; i < 32-prefix_length; i++ {
		ans *= 2
	}
	if ans == 0 {
		return 4294967295
	}
	return ans
}

// ReturnIPsInChildrenRule は、指定されたIPアドレスと参照ビットに一致するルールの子ノードに含まれるすべてのIPアドレスを返します。
func (routingtable *RoutingTablePatriciaTrie) ReturnIPsInChildrenRule(ip ipaddress.IPaddress, refbits int) []string {
	hitted, data := routingtable.SearchLongestIP(ip, refbits, nil, nil)
	depth := data.(Data).Depth // 最長一致ルールの深さ
	var ans []string
	countchild := func(prefix Prefix, item Item) error {

		// 子ノードの深さが最長一致ルールの深さ+1の場合、そのルールに含まれるIPアドレスを返す
		if item.(Data).Depth == depth+1 {
			ans = append(ans, routingtable.ReturnIPsInRule(prefix)...)
		}
		return nil
	}

	if len(hitted) == refbits {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(hitted), countchild)
	} else {
		var temp Data
		routingtable.RoutingTablePatriciaTrie.Insert(Prefix(ip.MaskedBitString(refbits)), temp)
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(ip.MaskedBitString(refbits)), countchild)
		routingtable.RoutingTablePatriciaTrie.Delete(Prefix(ip.MaskedBitString(refbits)))
	}

	return ans
}

// CountIPsInChildrenRule は、指定されたIPアドレスと参照ビットに一致するルールの子ノードに含まれるIPアドレスの数を返します。
func (routingtable *RoutingTablePatriciaTrie) CountIPsInChildrenRule(ip ipaddress.IPaddress, refbits int) uint32 {
	hitted, data := routingtable.SearchLongestIP(ip, refbits, nil, nil)
	depth := data.(Data).Depth
	var ans uint32
	countchild := func(prefix Prefix, item Item) error {
		if item.(Data).Depth == depth+1 {
			ans += routingtable.CountIPsInRule(prefix)
		}
		return nil
	}

	if len(hitted) == refbits {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(hitted), countchild)
	} else {
		var temp Data
		routingtable.RoutingTablePatriciaTrie.Insert(Prefix(ip.MaskedBitString(refbits)), temp)
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(ip.MaskedBitString(refbits)), countchild)
		routingtable.RoutingTablePatriciaTrie.Delete(Prefix(ip.MaskedBitString(refbits)))
	}

	return ans
}

// IsLeaf は、指定されたIPアドレスと参照ビットに一致するルールがリーフノードかどうかをチェックします。
// リーフノードである場合にtrueを返却します。
func (routingtable *RoutingTablePatriciaTrie) IsLeaf(ip ipaddress.IPaddress, refbits int, hitIpList *[]string, hitItemList *[]Item) bool {
	// 指定されたIPアドレスと参照ビットに一致する最長一致を検索します
	var hitted string
	if hitIpList == nil {
		hitted, _ = routingtable.SearchLongestIP(ip, refbits, hitIpList, hitItemList)
	}
	// if len(hitted) == 0 {
	// 	return false
	// }
	// 子ノードの数をカウントするための変数を初期化します
	// children := -1
	hasChildren := false

	// サブツリーを訪問する際に呼び出される関数
	// countchild := func(prefix Prefix, item Item) error {
	// 	children += 1
	// 	// println("counted : ", string(prefix))
	// 	return nil
	// }

	// 検索結果の長さが参照ビットと一致する場合
	if len(hitted) == refbits {
		// サブツリーを訪問し、子ノードの数をカウントします
		// println("hitted : ", hitted)
		hitted_0 := hitted + "0"
		hitted_1 := hitted + "1"
		// routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(hitted), countchild)
		hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(Prefix(hitted_0))
		hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(Prefix(hitted_1)) || hasChildren
	} else {
		// 一時的なデータを作成し、ツリーに挿入します

		test_node_ip := ip.MaskedBitString(refbits)
		test_node_ip_0 := test_node_ip + "0" // MatchSubtreeは自身もマッチしてしまうので、子ノードを探すために+1したIPを作成
		test_node_ip_1 := test_node_ip + "1"
		// test_node_ip_str := ipaddress.BitStringToIP(test_node_ip) // for debug
		// fmt.Println("test_node_ip:", test_node_ip_str)
		// println("test_node_ip:", test_node_ip)
		var temp Data
		if !routingtable.RoutingTablePatriciaTrie.Match(Prefix(test_node_ip)) {
			routingtable.RoutingTablePatriciaTrie.Insert(Prefix(test_node_ip), temp)
			// サブツリーを訪問し、子ノードの数をカウントします
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(Prefix(test_node_ip_0))
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(Prefix(test_node_ip_1)) || hasChildren
			// routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(test_node_ip), countchild)

			// 一時的に挿入したデータを削除します
			routingtable.RoutingTablePatriciaTrie.Delete(Prefix(test_node_ip))
		} else {
			// routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(test_node_ip), countchild)
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(Prefix(test_node_ip_0))
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(Prefix(test_node_ip_1)) || hasChildren
		}
	}

	// 子ノードの数に応じてリーフノードかどうかを判定します
	// if children == 0 {
	// 	// println("children == 0", !hasChildren)
	// 	if hasChildren {
	// 		panic("Isleaf")
	// 	}
	// 	return true
	// }
	// if 1 <= children {
	// 	if !hasChildren {
	// 		panic("Isleaf")
	// 	}
	// 	// println("1 <= ", children, !hasChildren)
	// 	return false
	// }

	return !hasChildren // childrenがないということはリーフノード
}

// IsShorter は、指定されたIPアドレスと参照ビットに一致するルールが指定された長さより短いかどうかをチェックします。
func (routingtable *RoutingTablePatriciaTrie) IsShorter(ip ipaddress.IPaddress, refbits int, length int, hitIpList *[]string, hitItemList *[]Item) bool {
	hitted, _ := routingtable.SearchLongestIP(ip, refbits, hitIpList, hitItemList)

	// len(hitted) != 0 &&
	if len(hitted) <= length {
		return true
	} else {
		return false
	}

}

// SearchIP は、指定されたIPアドレスと参照ビットに一致するすべてのプレフィックスとアイテムを検索します。
func (routingtable *RoutingTablePatriciaTrie) SearchIP(ip ipaddress.IPaddress, refbits int, hitIpList *[]string, hitItemList *[]Item) ([]string, []Item) {

	var hitted []string // ヒットしたプレフィックスを格納 "101110"など
	var items []Item    // nexthop とdepth を格納
	if hitIpList == nil {
		storeans := func(prefix Prefix, item Item) error {
			hitted = append(hitted, string(prefix))
			items = append(items, item)
			return nil
		}
		routingtable.RoutingTablePatriciaTrie.VisitPrefixes(Prefix(ip.MaskedBitString(refbits)), storeans)
	} else {
		hitted = *hitIpList
		items = *hitItemList
	}
	return hitted, items
}

// SearchLongestIP は、指定されたIPアドレスと参照ビットに一致する最も長いプレフィックスとアイテムを検索します。
func (routingtable *RoutingTablePatriciaTrie) SearchLongestIP(ip ipaddress.IPaddress, refbits int, hitIpList *[]string, hitItemList *[]Item) (string, Item) {
	hitted, hoge := routingtable.SearchIP(ip, refbits, hitIpList, hitItemList) //hogeはdatas
	return hitted[len(hitted)-1], hoge[len(hoge)-1]
}

// ResetTreeDepth は、Patricia Trie内のすべてのノードの深さをリセットします。
func (routingtable *RoutingTablePatriciaTrie) ResetTreeDepth() {
	storeans := func(prefix Prefix, item Item) error {
		temp := item.(Data)
		temp.Depth = 0
		routingtable.RoutingTablePatriciaTrie.Set(prefix, temp)
		return nil
	}

	routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(""), storeans)
}

// ReadRule は、ファイルからルーティングルールを読み取り、Patricia Trieに挿入します。
func (routingtable *RoutingTablePatriciaTrie) ReadRule(fp *os.File) {
	scanner := bufio.NewScanner(fp)
	// refbits := 3
	for scanner.Scan() {
		slice := strings.Split(scanner.Text(), " ")

		ip := ipaddress.NewIPaddress(slice[0])
		i, _ := strconv.Atoi(slice[1])
		a := ip.MaskedBitString(i)

		var item Data
		item.NextHop = slice[2]

		// プレフィックスの長さに基づいて深さを設定
		if len(a) <= 16 {
			item.Depth = 2
		} else if len(a) <= 24 {
			item.Depth = 3
		} else if len(a) <= 32 {
			item.Depth = 4
		}
		// routingtable.RoutingTablePatriciaTrie.Insert(Prefix(ip.MaskedBitString(refbits)), nil)
		routingtable.RoutingTablePatriciaTrie.Insert(Prefix(ip.MaskedBitString(i)), item)
	}
}

// NewRoutingTablePatriciaTrie は、Patricia Trieを用いた新しいルーティングテーブルを初期化します。
func NewRoutingTablePatriciaTrie() *RoutingTablePatriciaTrie {
	trie := NewTrie(MaxPrefixPerNode(33), MaxChildrenPerSparseNode(257))

	return &RoutingTablePatriciaTrie{
		RoutingTablePatriciaTrie: trie,
	}
}

// PrintTrie
func (routingtable *RoutingTablePatriciaTrie) PrintTrie() {
	printItem := func(prefix patricia.Prefix, item patricia.Item) error {
		fmt.Printf("%q: %v\n", prefix, item)
		return nil
	}
	routingtable.RoutingTablePatriciaTrie.Visit(printItem)
}

// p は、指定されたデータを出力するデバッグ用関数です。
func p(hoge interface{}) {
	fmt.Println(hoge)
}

func GetRandomDstIP() ipaddress.IPaddress {

	// 乱数生成
	strIP := ""
	for i := 0; i < 4; i++ {
		rand.NewSource(time.Now().UnixNano())
		randomint := rand.Intn(254) // 0-253の乱数生成
		randomint = randomint + 1
		strIP += strconv.Itoa(randomint)
		if i != 3 {
			strIP += "."
		}
	}
	ip := ipaddress.NewIPaddress(strIP)

	return ip
}

/*func (routingtable *RoutingTablePatriciaTrie) CalTreeDepth() {
	hoge := func(prefix Prefix, item Item) error {
		temp := item.(Data)
		temp.Depth += 1
		routingtable.RoutingTablePatriciaTrie.Set(prefix, temp)
		return nil
	}
	storeans := func(prefix Prefix, item Item) error {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(prefix, hoge)
		return nil
	}

	routingtable.ResetTreeDepth()
	routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(""), storeans)
}*/
