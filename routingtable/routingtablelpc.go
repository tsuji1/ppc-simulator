package routingtable

// import (
// 	"bufio"
// 	"fmt"
// 	"math/rand"
// 	"os"
// 	"strconv"
// 	"strings"
// 	"test-module/ipaddress"
// 	"time"
// 	"test-module/lpctrie"

// 	lru "github.com/hashicorp/golang-lru/v2"
// 	"github.com/tsuji1/go-patricia/patricia"
// )

// // RoutingTableLPCtrie は、ルーティングテーブルのためのPatricia Trieを保持する構造体です。
// type RoutingTableLPCtrie struct {
// 	RoutingTableLPCTrie 	*lpctrie.Trie
// 	IsLeafCache              *lru.Cache[string, bool]
// 	IsLeafCacheHit           int
// 	IsLeafCacheTotal         int
// 	SearchIpCache            *lru.Cache[string, Result]
// 	SearchIpCacheHit         int
// 	SearchIpCacheTotal       int
// }

// // PrintMatchRulesInfo は、指定されたIPアドレスと参照ビットに一致するルールの情報を出力します。
// func (routingtable *RoutingTableLPCtrie) PrintMatchRulesInfo(ip ipaddress.IPaddress, refbits int) {
// 	hitted, _ := routingtable.SearchIP(ip, refbits)
// 	ans := "["
// 	for _, p := range hitted {
// 		ans += strconv.Itoa(len(p))
// 		ans += " "
// 	}
// 	ans += "],"
// 	ans += strconv.Itoa(int(routingtable.CountIPsInChildrenRule(ip, len(hitted[len(hitted)-1])))) // 最長一致ルールの子ノード数
// 	ans += ","
// 	ans += strconv.Itoa(int(routingtable.CountIPsInChildrenRule(ip, 24))) // /24にキャッシュするのに必要なIP数
// 	// fmt.Println(ans)
// }

// // ReturnIPsInRule は、指定されたプレフィックスに含まれるすべてのIPアドレスを返します。
// func (routingtable *RoutingTableLPCtrie) ReturnIPsInRule(prefix patricia.Prefix) []string {
// 	num_IPs := routingtable.CountIPsInRule(prefix)
// 	temp := ipaddress.NewIPaddress(string(prefix))
// 	start := temp.Uint32()
// 	var ans []string
// 	var i uint32
// 	for i = 0; i < num_IPs; i++ {
// 		temp.SetIP(start + i)
// 		ans = append(ans, temp.String())
// 	}
// 	return ans
// }

// // CountIPsInRule は、指定されたプレフィックスに含まれるIPアドレスの数を返します。
// // 例えば、/24のプレフィックスに含まれるIPアドレスの数は256です。
// func (routingtable *RoutingTableLPCtrie) CountIPsInRule(prefix patricia.Prefix) uint32 {
// 	prefix_length := len(prefix)
// 	var ans uint32
// 	ans = 1
// 	for i := 0; i < 32-prefix_length; i++ {
// 		ans *= 2
// 	}
// 	if ans == 0 {
// 		return 4294967295
// 	}
// 	return ans
// }

// // ReturnIPsInChildrenRule は、指定されたIPアドレスと参照ビットに一致するルールの子ノードに含まれるすべてのIPアドレスを返します。
// func (routingtable *RoutingTableLPCtrie) ReturnIPsInChildrenRule(ip ipaddress.IPaddress, refbits int) []string {
// 	hitted, data := routingtable.SearchLongestIP(ip, refbits)
// 	depth := data.(Data).Depth // 最長一致ルールの深さ
// 	var ans []string
// 	countchild := func(prefix patricia.Prefix, item patricia.Item) error {

// 		// 子ノードの深さが最長一致ルールの深さ+1の場合、そのルールに含まれるIPアドレスを返す
// 		if item.(Data).Depth == depth+1 {
// 			ans = append(ans, routingtable.ReturnIPsInRule(prefix)...)
// 		}
// 		return nil
// 	}

// 	if len(hitted) == refbits {
// 		routingtable.RoutingTableLPCtrie.VisitSubtree(patricia.Prefix(hitted), countchild)
// 	} else {
// 		var temp Data
// 		routingtable.RoutingTableLPCtrie.Insert(patricia.Prefix(ip.MaskedBitString(refbits)), temp)
// 		routingtable.RoutingTableLPCtrie.VisitSubtree(patricia.Prefix(ip.MaskedBitString(refbits)), countchild)
// 		routingtable.RoutingTableLPCtrie.Delete(patricia.Prefix(ip.MaskedBitString(refbits)))
// 	}

// 	return ans
// }

// // CountIPsInChildrenRule は、指定されたIPアドレスと参照ビットに一致するルールの子ノードに含まれるIPアドレスの数を返します。
// func (routingtable *RoutingTableLPCtrie) CountIPsInChildrenRule(ip ipaddress.IPaddress, refbits int) uint32 {
// 	hitted, data := routingtable.SearchLongestIP(ip, refbits)
// 	depth := data.(Data).Depth
// 	var ans uint32
// 	countchild := func(prefix patricia.Prefix, item patricia.Item) error {
// 		if item.(Data).Depth == depth+1 {
// 			ans += routingtable.CountIPsInRule(prefix)
// 		}
// 		return nil
// 	}

// 	if len(hitted) == refbits {
// 		routingtable.RoutingTableLPCtrie.VisitSubtree(patricia.Prefix(hitted), countchild)
// 	} else {
// 		var temp Data
// 		routingtable.RoutingTableLPCtrie.Insert(patricia.Prefix(ip.MaskedBitString(refbits)), temp)
// 		routingtable.RoutingTableLPCtrie.VisitSubtree(patricia.Prefix(ip.MaskedBitString(refbits)), countchild)
// 		routingtable.RoutingTableLPCtrie.Delete(patricia.Prefix(ip.MaskedBitString(refbits)))
// 	}

// 	return ans
// }

// // IsLeaf は、指定されたIPアドレスと参照ビットに一致するルールがリーフノードかどうかをチェックします。
// // リーフノードである場合にtrueを返却します。
// func (routingtable *RoutingTableLPCtrie) IsLeaf(ip ipaddress.IPaddress, refbits int) bool {
// 	// 指定されたIPアドレスと参照ビットに一致する最長一致を検索します
// 	var hitted string
// 	var maskip = ip.MaskedBitString(refbits)
// 	routingtable.IsLeafCacheTotal++
// 	s, ok := routingtable.IsLeafCache.Get(maskip)
// 	if ok {
// 		routingtable.IsLeafCacheHit++
// 		return s
// 	}

// 	hitted, _ = routingtable.SearchLongestIP(ip, refbits)

// 	hasChildren := false

// 	// 検索結果の長さが参照ビットと一致する場合
// 	if len(hitted) == refbits {
// 		// サブツリーを訪問し、子ノードの数をカウントします
// 		// println("hitted : ", hitted)
// 		hitted_0 := hitted + "0"
// 		hitted_1 := hitted + "1"
// 		hasChildren = routingtable.RoutingTableLPCtrie.MatchSubtree(patricia.Prefix(hitted_0))
// 		hasChildren = routingtable.RoutingTableLPCtrie.MatchSubtree(patricia.Prefix(hitted_1)) || hasChildren
// 	} else {
// 		// 一時的なデータを作成し、ツリーに挿入します

// 		test_node_ip := ip.MaskedBitString(refbits)
// 		test_node_ip_0 := test_node_ip + "0" // MatchSubtreeは自身もマッチしてしまうので、子ノードを探すために+1したIPを作成
// 		test_node_ip_1 := test_node_ip + "1"
// 		var temp Data
// 		if !routingtable.RoutingTableLPCtrie.Match(patricia.Prefix(test_node_ip)) {
// 			routingtable.RoutingTableLPCtrie.Insert(patricia.Prefix(test_node_ip), temp)
// 			// サブツリーを訪問し、子ノードの数をカウントします
// 			hasChildren = routingtable.RoutingTableLPCtrie.MatchSubtree(patricia.Prefix(test_node_ip_0))
// 			hasChildren = routingtable.RoutingTableLPCtrie.MatchSubtree(patricia.Prefix(test_node_ip_1)) || hasChildren

// 			// 一時的に挿入したデータを削除します
// 			routingtable.RoutingTableLPCtrie.Delete(patricia.Prefix(test_node_ip))
// 		} else {
// 			hasChildren = routingtable.RoutingTableLPCtrie.MatchSubtree(patricia.Prefix(test_node_ip_0))
// 			hasChildren = routingtable.RoutingTableLPCtrie.MatchSubtree(patricia.Prefix(test_node_ip_1)) || hasChildren
// 		}
// 	}
// 	routingtable.IsLeafCache.Add(maskip, !hasChildren)
// 	return !hasChildren // childrenがないということはリーフノード
// }

// // IsShorter は、指定されたIPアドレスと参照ビットに一致するルールが指定された長さより短いかどうかをチェックします。
// func (routingtable *RoutingTableLPCtrie) IsShorter(ip ipaddress.IPaddress, refbits int, length int) bool {
// 	hitted, _ := routingtable.SearchLongestIP(ip, refbits)

// 	// len(hitted) != 0 &&
// 	if len(hitted) <= length {
// 		return true
// 	} else {
// 		return false
// 	}

// }

// // SearchIP は、指定されたIPアドレスと参照ビットに一致するすべてのプレフィックスとアイテムを検索します。
// func (routingtable *RoutingTableLPCtrie) SearchIP(ip ipaddress.IPaddress, refbits int) ([]string, []patricia.Item) {
// 	var maskip = ip.MaskedBitString(refbits)
// 	// fmt.Println(ipaddress.BitStringToIP(maskip))
// 	routingtable.SearchIpCacheTotal++
// 	s, ok := routingtable.SearchIpCache.Get(maskip)
// 	if ok {
// 		routingtable.SearchIpCacheHit++
// 		return s.hitted, s.items
// 	}

// 	var hitted []string       // ヒットしたプレフィックスを格納 "101110"など
// 	var items []patricia.Item // nexthop とdepth を格納

// 	storeans := func(prefix patricia.Prefix, item patricia.Item) error {
// 		hitted = append(hitted, string(prefix))
// 		items = append(items, item)
// 		return nil
// 	}
// 	routingtable.RoutingTableLPCtrie.VisitPrefixes(patricia.Prefix(ip.MaskedBitString(refbits)), storeans)
// 	// routingtable.SearchIpCache.Add(maskip, temp)

// 	return hitted, items
// }

// // SearchLongestIP は、指定されたIPアドレスと参照ビットに一致する最も長いプレフィックスとアイテムを検索します。
// func (routingtable *RoutingTableLPCtrie) SearchLongestIP(ip ipaddress.IPaddress, refbits int) (string, patricia.Item) {
// 	hitted, hoge := routingtable.SearchIP(ip, refbits) //hogeはdatas
// 	return hitted[len(hitted)-1], hoge[len(hoge)-1]
// }

// // ResetTreeDepth は、Patricia Trie内のすべてのノードの深さをリセットします。
// func (routingtable *RoutingTableLPCtrie) ResetTreeDepth() {
// 	storeans := func(prefix patricia.Prefix, item patricia.Item) error {
// 		temp := item.(Data)
// 		temp.Depth = 0
// 		routingtable.RoutingTableLPCtrie.Set(prefix, temp)
// 		return nil
// 	}

// 	routingtable.RoutingTableLPCtrie.VisitSubtree(patricia.Prefix(""), storeans)
// }

// // ReadRule は、ファイルからルーティングルールを読み取り、Patricia Trieに挿入します。
// func (routingtable *RoutingTableLPCtrie) ReadRule(fp *os.File) {
// 	scanner := bufio.NewScanner(fp)
// 	// refbits := 3
// 	for scanner.Scan() {
// 		slice := strings.Split(scanner.Text(), " ")

// 		ip := ipaddress.NewIPaddress(slice[0])
// 		i, _ := strconv.Atoi(slice[1])
// 		a := ip.MaskedBitString(i)

// 		var item Data
// 		item.NextHop = slice[2]

// 		// プレフィックスの長さに基づいて深さを設定
// 		if len(a) <= 16 {
// 			item.Depth = 2
// 		} else if len(a) <= 24 {
// 			item.Depth = 3
// 		} else if len(a) <= 32 {
// 			item.Depth = 4
// 		}
// 		// routingtable.RoutingTableLPCtrie.Insert(patricia.Prefix(ip.MaskedBitString(refbits)), nil)
// 		routingtable.RoutingTableLPCtrie.Insert(patricia.Prefix(ip.MaskedBitString(i)), item)
// 	}
// }

// // NewRoutingTableLPCtrie は、Patricia Trieを用いた新しいルーティングテーブルを初期化します。
// func NewRoutingTableLPCtrie() *RoutingTableLPCtrie {
// 	trie := patricia.NewTrie(patricia.MaxPrefixPerNode(33), patricia.MaxChildrenPerSparseNode(257))
// 	l, _ := lru.New[string, bool](2048)
// 	s, _ := lru.New[string, Result](2048)

// 	return &RoutingTableLPCtrie{
// 		RoutingTableLPCtrie: trie,
// 		IsLeafCache:              l,
// 		IsLeafCacheHit:           0,
// 		IsLeafCacheTotal:         0,
// 		SearchIpCache:            s,
// 		SearchIpCacheHit:         0,
// 		SearchIpCacheTotal:       0,
// 	}
// }

// // PrintTrie
// func (routingtable *RoutingTableLPCtrie) PrintTrie() {
// 	printItem := func(prefix patricia.Prefix, item patricia.Item) error {
// 		fmt.Printf("%q: %v\n", prefix, item)
// 		return nil
// 	}
// 	routingtable.RoutingTableLPCtrie.Visit(printItem)
// }

// // p は、指定されたデータを出力するデバッグ用関数です。
// func p(hoge interface{}) {
// 	fmt.Println(hoge)
// }

// func GetRandomDstIP() ipaddress.IPaddress {

// 	// 乱数生成
// 	strIP := ""
// 	for i := 0; i < 4; i++ {
// 		rand.NewSource(time.Now().UnixNano())
// 		randomint := rand.Intn(254) // 0-253の乱数生成
// 		randomint = randomint + 1
// 		strIP += strconv.Itoa(randomint)
// 		if i != 3 {
// 			strIP += "."
// 		}
// 	}
// 	ip := ipaddress.NewIPaddress(strIP)
// 	return ip
// }

// func (routingtable *RoutingTableLPCtrie) StatDetail() {
// 	fmt.Println("IsLeafCacheHit : ", float64(routingtable.IsLeafCacheHit)/float64(routingtable.IsLeafCacheTotal))
// 	fmt.Println("SearchIpCacheHit : ", float64(routingtable.SearchIpCacheHit)/float64(routingtable.SearchIpCacheTotal))

// }

// func Clone(routingtable *RoutingTableLPCtrie) *RoutingTableLPCtrie {
// 	// 新しい Trie を初期化

// 	newTrie := routingtable.RoutingTableLPCtrie.Clone()

// 	if newTrie == nil {
// 		panic("Failed to clone Patricia Trie")
// 	}
// 	fmt.Println(newTrie)
// 	l, _ := lru.New[string, bool](256)
// 	s, _ := lru.New[string, Result](256)

// 	// 新しい RoutingTableLPCtrie を返す
// 	return &RoutingTableLPCtrie{
// 		RoutingTableLPCtrie: newTrie,
// 		IsLeafCache:              l,
// 		IsLeafCacheHit:           0, // キャッシュヒット数はリセット
// 		IsLeafCacheTotal:         0,
// 		SearchIpCache:            s,
// 		SearchIpCacheHit:         0,
// 		SearchIpCacheTotal:       0,
// 	}
// }

// /*func (routingtable *RoutingTableLPCtrie) CalTreeDepth() {
// 	hoge := func(prefix patricia.Prefix, item Item) error {
// 		temp := item.(Data)
// 		temp.Depth += 1
// 		routingtable.RoutingTableLPCtrie.Set(prefix, temp)
// 		return nil
// 	}
// 	storeans := func(prefix patricia.Prefix, item Item) error {
// 		routingtable.RoutingTableLPCtrie.VisitSubtree(prefix, hoge)
// 		return nil
// 	}

// 	routingtable.ResetTreeDepth()
// 	routingtable.RoutingTableLPCtrie.VisitSubtree(patricia.Prefix(""), storeans)
// }*/
