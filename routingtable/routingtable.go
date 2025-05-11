package routingtable

import (
	"bufio"
	"errors"
	"fmt"
	"math/rand"
	"os"
	"strconv"
	"strings"
	"test-module/ipaddress"
	"test-module/lpctrie"

	lru "github.com/hashicorp/golang-lru/v2"
	"github.com/tsuji1/go-patricia/patricia"
)

// RoutingTablePatriciaTrie は、ルーティングテーブルのためのPatricia Trieを保持する構造体です。
type RoutingTablePatriciaTrie struct {
	RoutingTablePatriciaTrie *patricia.Trie
	IsLeafCache              *lru.Cache[string, bool]
	IsLeafCacheHit           int
	IsLeafCacheTotal         int
	SearchIpCache            *lru.Cache[string, Result]
	SearchIpCacheHit         int
	SearchIpCacheTotal       int
	LpcTrie                  *lpctrie.Trie
}

// Data は、ルーティング情報を深さとネクストホップで保持するデータ構造です。
type Data struct {
	Depth   uint64
	NextHop string
}

type Result struct {
	hitted []string
	items  []patricia.Item
}

// ReturnIPsInRule は、指定されたプレフィックスに含まれるすべてのIPアドレスを返します。
func (routingtable *RoutingTablePatriciaTrie) ReturnIPsInRule(prefix patricia.Prefix) []string {
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

// EnumerateSubPrefixes は、指定されたプレフィックスに含まれるすべてのプレフィクスを返します。
func (routingtable *RoutingTablePatriciaTrie) EnumerateSubPrefixes(prefix patricia.Prefix,srcRefbit uint, upperRefbit uint) (ans []string) {

	prefix_length := uint(len(prefix))
	fillLength := upperRefbit - prefix_length

	suffixLength := 32 - upperRefbit
	// baseip fillip suffixip(これはいらない)

	baseIp := ipaddress.NewIPaddress(string(prefix))
	baseIpUint := baseIp.Uint32()
	// baseIp を

	var i uint

	// baseipをupperRefbitまでシフトして
	// fillLength(個)を考慮してIPアドレスを生成する
	// 最後にシフトを戻す
	baseIpUint = baseIpUint >> suffixLength

	for i = 0; i < (1 << fillLength) ; i++ {
		cacheIp := baseIpUint + uint32(i)
		cacheIp = cacheIp << uint32(suffixLength)
		cacheIpAddress := ipaddress.NewIPaddress(cacheIp)
		ans = append(ans, cacheIpAddress.String())
	}

	return ans
}

func (routingtable *RoutingTablePatriciaTrie) GroupChildPrefixesByRefBits(prefix string, srcRefbit uint, upperRefbits []uint) (ans [][]string) {

	ans = make([][]string, len(upperRefbits))
	tmpPrefix := ipaddress.NewIPaddress(prefix).String()
	_ = tmpPrefix


	countchild := func(p patricia.Prefix, i patricia.Item) error {
		if prefix != string(p) {
			p_length := uint(len(p))
			// upperRefbitsを逆順で処理する
			for i := len(upperRefbits) - 1; i >= 0; i-- {
				upperRefbit := upperRefbits[i]
				// 正確には，3相とかある場合はupperRefbitは消していくべき？違うか，17のルールは18に入れればいいし，19のルールは24に入れればいいだけのことか
				if p_length <= upperRefbit {
					cache_prefix_list := routingtable.EnumerateSubPrefixes(p, srcRefbit,upperRefbit)
					ans[i] = append(ans[i], cache_prefix_list...)
					tmp := ipaddress.NewIPaddress(string(p)).String()
					_ = tmp

					break
				}
				return errors.New("prefix length is greater than upperRefbit")
			}
		}
		return nil
	}

	routingtable.RoutingTablePatriciaTrie.VisitSubtree(patricia.Prefix(prefix), countchild)

	return ans
}

// CountIPsInChildrenRule は、指定されたIPアドレスと参照ビットに一致するルールの子ノードに含まれるIPアドレスの数を返します。
var ErrStopWalk = errors.New("patricia: stop walk")  // 独自 sentinel
func (routingtable *RoutingTablePatriciaTrie) CountMatchingSubtreeRules(ip ipaddress.IPaddress, srcRefbit uint, upperRefbits []uint, limit int) (ans uint, prefix string) {
	path, _, leftover := routingtable.RoutingTablePatriciaTrie.FindSubtreePath(patricia.Prefix(ip.MaskedBitString(int(srcRefbit))))
	prefix = ""
	for _, node := range path {
		prefix = prefix + string(node.GetPrefix())
	}
	// p はleftoverが末尾についているはずなので消したい
	prefix = prefix[:len(prefix)-len(leftover)]

	ans = 0
	countchild := func(p patricia.Prefix, i patricia.Item) error {
		if prefix != string(p) {
			ans += routingtable.CountFilledRule(p, srcRefbit, upperRefbits)
		}
		if ans > uint(limit) {
			return ErrStopWalk
		}
		return nil
	}

	routingtable.RoutingTablePatriciaTrie.VisitSubtree(patricia.Prefix(prefix), countchild)
	if ans > 0 && len(upperRefbits) == 0 {
		// something wrong
		ans = 4294967295
		return
	}
	return
}

func (routingtable *RoutingTablePatriciaTrie) CountFilledRule(prefix patricia.Prefix, srcRefbit uint, upperRefbits []uint) (ans uint) {
	prefix_length := uint(len(prefix))

	ans = 1

	// upperRefbits をrange
	for i := len(upperRefbits) - 1; i >= 0; i-- {
		upperRefbit := upperRefbits[i]
		if upperRefbit >= prefix_length {
			ans = ans << (upperRefbit - prefix_length)
			break
		}
		return 4294967295
	}
	return

}

// CountIPsInRule は、指定されたプレフィックスに含まれるIPアドレスの数を返します。
// 例えば、/24のプレフィックスに含まれるIPアドレスの数は256です。
func (routingtable *RoutingTablePatriciaTrie) CountIPsInRule(prefix patricia.Prefix) uint32 {
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

// IsLeaf は、指定されたIPアドレスと参照ビットに一致するルールがリーフノードかどうかをチェックします。
// リーフノードである場合にtrueを返却します。
func (routingtable *RoutingTablePatriciaTrie) IsLeaf(ip ipaddress.IPaddress, refbits int) bool {
	// 指定されたIPアドレスと参照ビットに一致する最長一致を検索します
	var hitted string
	var maskip = ip.MaskedBitString(refbits)
	routingtable.IsLeafCacheTotal++
	s, ok := routingtable.IsLeafCache.Get(maskip)
	if ok {
		routingtable.IsLeafCacheHit++
		return s
	}

	hitted, _ = routingtable.SearchLongestIP(ip, refbits)

	hasChildren := false

	// 検索結果の長さが参照ビットと一致する場合
	if len(hitted) == refbits {
		// サブツリーを訪問し、子ノードの数をカウントします
		// println("hitted : ", hitted)
		hitted_0 := hitted + "0"
		hitted_1 := hitted + "1"
		hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(patricia.Prefix(hitted_0))
		hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(patricia.Prefix(hitted_1)) || hasChildren
	} else {
		// 一時的なデータを作成し、ツリーに挿入します

		test_node_ip := ip.MaskedBitString(refbits)
		test_node_ip_0 := test_node_ip + "0" // MatchSubtreeは自身もマッチしてしまうので、子ノードを探すために+1したIPを作成
		test_node_ip_1 := test_node_ip + "1"
		var temp Data
		if !routingtable.RoutingTablePatriciaTrie.Match(patricia.Prefix(test_node_ip)) {
			routingtable.RoutingTablePatriciaTrie.Insert(patricia.Prefix(test_node_ip), temp)
			// サブツリーを訪問し、子ノードの数をカウントします
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(patricia.Prefix(test_node_ip_0))
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(patricia.Prefix(test_node_ip_1)) || hasChildren

			// 一時的に挿入したデータを削除します
			routingtable.RoutingTablePatriciaTrie.Delete(patricia.Prefix(test_node_ip))
		} else {
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(patricia.Prefix(test_node_ip_0))
			hasChildren = routingtable.RoutingTablePatriciaTrie.MatchSubtree(patricia.Prefix(test_node_ip_1)) || hasChildren
		}
	}
	routingtable.IsLeafCache.Add(maskip, !hasChildren)
	return !hasChildren // childrenがないということはリーフノード
}

// IsShorter は、指定されたIPアドレスと参照ビットに一致するルールが指定された長さより短いかどうかをチェックします。
func (routingtable *RoutingTablePatriciaTrie) IsShorter(ip ipaddress.IPaddress, refbits int, length int) bool {
	hitted, _ := routingtable.SearchLongestIP(ip, refbits)

	// len(hitted) != 0 &&
	if len(hitted) <= length {
		return true
	} else {
		return false
	}

}

// SearchIP は、指定されたIPアドレスと参照ビットに一致するすべてのプレフィックスとアイテムを検索します。
func (routingtable *RoutingTablePatriciaTrie) SearchIP(ip ipaddress.IPaddress, refbits int) ([]string, []patricia.Item) {
	var maskip = ip.MaskedBitString(refbits)
	// fmt.Println(ipaddress.BitStringToIP(maskip))
	routingtable.SearchIpCacheTotal++
	s, ok := routingtable.SearchIpCache.Get(maskip)
	if ok {
		routingtable.SearchIpCacheHit++
		return s.hitted, s.items
	}

	var hitted []string       // ヒットしたプレフィックスを格納 "101110"など
	var items []patricia.Item // nexthop とdepth を格納

	storeans := func(prefix patricia.Prefix, item patricia.Item) error {
		hitted = append(hitted, string(prefix))
		items = append(items, item)
		return nil
	}
	routingtable.RoutingTablePatriciaTrie.VisitPrefixes(patricia.Prefix(ip.MaskedBitString(refbits)), storeans)
	// routingtable.SearchIpCache.Add(maskip, temp)

	return hitted, items
}

// SearchLongestIP は、指定されたIPアドレスと参照ビットに一致する最も長いプレフィックスとアイテムを検索します。
func (routingtable *RoutingTablePatriciaTrie) SearchLongestIP(ip ipaddress.IPaddress, refbits int) (string, patricia.Item) {
	hitted, hoge := routingtable.SearchIP(ip, refbits) //hogeはdatas
	return hitted[len(hitted)-1], hoge[len(hoge)-1]
}

// ResetTreeDepth は、Patricia Trie内のすべてのノードの深さをリセットします。
func (routingtable *RoutingTablePatriciaTrie) ResetTreeDepth() {
	storeans := func(prefix patricia.Prefix, item patricia.Item) error {
		temp := item.(Data)
		temp.Depth = 0
		routingtable.RoutingTablePatriciaTrie.Set(prefix, temp)
		return nil
	}

	routingtable.RoutingTablePatriciaTrie.VisitSubtree(patricia.Prefix(""), storeans)
}

// ReadRule は、ファイルからルーティングルールを読み取り、Patricia Trieに挿入します。
func (routingtable *RoutingTablePatriciaTrie) ReadRule(fp *os.File) {
	scanner := bufio.NewScanner(fp)
	// refbits := 3
	for scanner.Scan() {
		slice := strings.Split(scanner.Text(), " ")

		ip := ipaddress.NewIPaddress(slice[0])
		i, _ := strconv.Atoi(slice[1])

		var item Data
		item.NextHop = slice[2]
		fibalias := &lpctrie.FibAlias{FaSlen: uint8(i)}

		lpctrie.FibInsert(routingtable.LpcTrie, lpctrie.Key(ip.Uint32()), fibalias)
		// routingtable.RoutingTablePatriciaTrie.Insert(patricia.Prefix(ip.MaskedBitString(refbits)), nil)
		routingtable.RoutingTablePatriciaTrie.Insert(patricia.Prefix(ip.MaskedBitString(i)), item)
	}
}

func (routingtable *RoutingTablePatriciaTrie) GetDepth(dstIP uint32) int {
	return lpctrie.GetDepth(routingtable.LpcTrie, lpctrie.Key(dstIP))
}

// NewRoutingTablePatriciaTrie は、Patricia Trieを用いた新しいルーティングテーブルを初期化します。
func NewRoutingTablePatriciaTrie() *RoutingTablePatriciaTrie {
	trie := patricia.NewTrie(patricia.MaxPrefixPerNode(33), patricia.MaxChildrenPerSparseNode(257))
	l, _ := lru.New[string, bool](2048)
	s, _ := lru.New[string, Result](2048)
	lpctrie := lpctrie.NewTrie()

	return &RoutingTablePatriciaTrie{
		RoutingTablePatriciaTrie: trie,
		IsLeafCache:              l,
		IsLeafCacheHit:           0,
		IsLeafCacheTotal:         0,
		SearchIpCache:            s,
		SearchIpCacheHit:         0,
		SearchIpCacheTotal:       0,
		LpcTrie:                  lpctrie,
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

// func GetRandomDstIP() ipaddress.IPaddress {

// 	// 乱数生成(全くランダムではない)
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

func GetRandomDstIP() ipaddress.IPaddress {
	// 0-255の範囲でランダムに4つのオクテットを作成
	octets := make([]string, 4)
	for i := 0; i < 4; i++ {
		octets[i] = strconv.Itoa(rand.Intn(254) + 1) // 1〜254
	}
	strIP := strings.Join(octets, ".")
	ip := ipaddress.NewIPaddress(strIP)
	return ip
}

func (routingtable *RoutingTablePatriciaTrie) StatDetail() {
	fmt.Println("IsLeafCacheHit : ", float64(routingtable.IsLeafCacheHit)/float64(routingtable.IsLeafCacheTotal))
	fmt.Println("SearchIpCacheHit : ", float64(routingtable.SearchIpCacheHit)/float64(routingtable.SearchIpCacheTotal))

}

func Clone(routingtable *RoutingTablePatriciaTrie) *RoutingTablePatriciaTrie {
	// 新しい Trie を初期化

	newTrie := routingtable.RoutingTablePatriciaTrie.Clone()

	if newTrie == nil {
		panic("Failed to clone Patricia Trie")
	}
	fmt.Println(newTrie)
	l, _ := lru.New[string, bool](256)
	s, _ := lru.New[string, Result](256)

	// 新しい RoutingTablePatriciaTrie を返す
	return &RoutingTablePatriciaTrie{
		RoutingTablePatriciaTrie: newTrie,
		IsLeafCache:              l,
		IsLeafCacheHit:           0, // キャッシュヒット数はリセット
		IsLeafCacheTotal:         0,
		SearchIpCache:            s,
		SearchIpCacheHit:         0,
		SearchIpCacheTotal:       0,
	}
}

/*func (routingtable *RoutingTablePatriciaTrie) CalTreeDepth() {
	hoge := func(prefix patricia.Prefix, item Item) error {
		temp := item.(Data)
		temp.Depth += 1
		routingtable.RoutingTablePatriciaTrie.Set(prefix, temp)
		return nil
	}
	storeans := func(prefix patricia.Prefix, item Item) error {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(prefix, hoge)
		return nil
	}

	routingtable.ResetTreeDepth()
	routingtable.RoutingTablePatriciaTrie.VisitSubtree(patricia.Prefix(""), storeans)
}*/
