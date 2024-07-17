# ipaddress.go

このコードは、Patricia Trie（パトリシアトライ）を使用してIPアドレスのルーティングテーブルを実装しています。以下に主要な部分とその機能について説明します。

### パッケージとインポート

```go
package routingtable

import (
	. "github.com/tchap/go-patricia/patricia"
	"fmt"
	"strconv"
	"strings"
	"os"
	"bufio"
	"test-module/ipaddress"
)
```

- `github.com/tchap/go-patricia/patricia` パッケージをインポートし、Patricia Trie を使用しています。
- `test-module/ipaddress` はカスタムモジュールで、IPアドレスの操作を行います。

### データ構造

#### `RoutingTablePatriciaTrie` 構造体

```go
type RoutingTablePatriciaTrie struct{
	RoutingTablePatriciaTrie *Trie
}
```

- Patricia Trie を保持する構造体です。

#### `Data` 構造体

```go
type Data struct{
	Depth uint64
	nexthop string
}
```

- ルーティング情報を保持するためのデータ構造体です。`Depth` はノードの深さを表し、`nexthop` は次のホップ（ルーター）を表します。

### メソッド

#### `PrintMatchRulesInfo`

```go
func (routingtable *RoutingTablePatriciaTrie) PrintMatchRulesInfo(ip ipaddress.IPaddress, refbits int) {
	hitted, _ := routingtable.SearchIP(ip, refbits)
	ans := "["
	for _, p := range(hitted) {
		ans += strconv.Itoa(len(p))
		ans += " "
	}
	ans += "],"
	ans += strconv.Itoa(int(routingtable.CountIPsInChildrenRule(ip, len(hitted[len( hitted)-1 ]))) ) // Longest Match Rule's children
	ans += ","
	ans += strconv.Itoa(int(routingtable.CountIPsInChildrenRule(ip, 24) )) // /24ni cache suru noni need IPs
	fmt.Println(ans)
}
```

- 指定されたIPアドレスに一致するルールの情報を出力します。`SearchIP` メソッドを使用して一致するルールを検索し、その結果をフォーマットして出力します。

#### `ReturnIPsInRule`

```go
func (routingtable *RoutingTablePatriciaTrie) ReturnIPsInRule(prefix Prefix) []string{
	num_IPs := routingtable.CountIPsInRule(prefix)
	temp := ipaddress.NewIPaddress(string(prefix))
	start := temp.Uint32()
	var ans []string
	var i uint32
	for i=0; i<num_IPs; i++{
		temp.SetIP(start+i)
		ans = append(ans, temp.String())
	}
	return ans
}
```

- 指定されたプレフィックスに含まれるIPアドレスをすべて返します。

#### `CountIPsInRule`

```go
func (routingtable *RoutingTablePatriciaTrie) CountIPsInRule(prefix Prefix) uint32{
	prefix_length := len(prefix)
	var ans uint32
	ans = 1
	for i:=0; i<32-prefix_length; i++ {
		ans *= 2
	}
	if ans==0 {return 4294967295}
	return ans
}
```

- 指定されたプレフィックスに含まれるIPアドレスの数を返します。

#### `ReturnIPsInChildrenRule`

```go
func (routingtable *RoutingTablePatriciaTrie) ReturnIPsInChildrenRule(ip ipaddress.IPaddress, refbits int) []string{
	hitted, data := routingtable.SearchLongestIP(ip, refbits)
	depth := data.(Data).Depth
	var ans []string
	countchild := func(prefix Prefix, item Item) error {
		if item.(Data).Depth == depth + 1{
			ans = append(ans, routingtable.ReturnIPsInRule(prefix)...)}
		return nil
	}
	
	if len(hitted) == refbits {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(hitted), countchild)
	}else{
		var temp Data
		routingtable.RoutingTablePatriciaTrie.Insert(Prefix( ip.MaskedBitString(refbits) ), temp)
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix( ip.MaskedBitString(refbits) ), countchild)
		routingtable.RoutingTablePatriciaTrie.Delete(Prefix( ip.MaskedBitString(refbits) ))
	}

	return ans
}
```

- 指定されたIPアドレスに一致するルールの子ノードに含まれるIPアドレスをすべて返します。

#### `CountIPsInChildrenRule`

```go
func (routingtable *RoutingTablePatriciaTrie) CountIPsInChildrenRule(ip ipaddress.IPaddress, refbits int) uint32{
	hitted, data := routingtable.SearchLongestIP(ip, refbits)
	depth := data.(Data).Depth
	var ans uint32
	countchild := func(prefix Prefix, item Item) error {
		if item.(Data).Depth == depth + 1{
			ans += routingtable.CountIPsInRule(prefix)}
			return nil
	}
	
	if len(hitted) == refbits {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(hitted), countchild)
	}else{
		var temp Data
		routingtable.RoutingTablePatriciaTrie.Insert(Prefix( ip.MaskedBitString(refbits) ), temp)
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix( ip.MaskedBitString(refbits) ), countchild)
		routingtable.RoutingTablePatriciaTrie.Delete(Prefix( ip.MaskedBitString(refbits) ))
	}

	return ans
}
```

- 指定されたIPアドレスに一致するルールの子ノードに含まれるIPアドレスの数を返します。

#### `IsLeaf`

```go
func (routingtable *RoutingTablePatriciaTrie) IsLeaf(ip ipaddress.IPaddress, refbits int) bool{
	hitted, _ := routingtable.SearchLongestIP(ip, refbits)
	children := -1
	countchild := func(prefix Prefix, item Item) error {
		children += 1
		return nil
	}
	
	if len(hitted) == refbits {
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(hitted), countchild)
	}else{
		var temp Data
		routingtable.RoutingTablePatriciaTrie.Insert(Prefix( ip.MaskedBitString(refbits) ), temp)
		routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix( ip.MaskedBitString(refbits) ), countchild)
		routingtable.RoutingTablePatriciaTrie.Delete(Prefix( ip.MaskedBitString(refbits) ))
	}

	if children == 0 {
		return true}
	if 1 <= children {
		return false}
	panic("Isleaf")
}
```

- 指定されたIPアドレスに一致するルールがリーフノード（葉ノード）かどうかを確認します。

#### `IsShorter`

```go
func (routingtable *RoutingTablePatriciaTrie) IsShorter(ip ipaddress.IPaddress, refbits int, length int) bool{
	hitted, _ := routingtable.SearchLongestIP(ip, refbits)
	if len(hitted) <= length {
		return true
	}else{
		return false
	}
}
```

- 指定されたIPアドレスに一致するルールが指定された長さより短いかどうかを確認します。

#### `SearchIP`

```go
func (routingtable *RoutingTablePatriciaTrie) SearchIP(ip ipaddress.IPaddress, refbits int) ([]string, []Item){
	var hitted []string
	var items []Item
	storeans := func(prefix Prefix, item Item) error {
		hitted = append(hitted, string(prefix))
		items = append(items, item)
		return nil
	}

	routingtable.RoutingTablePatriciaTrie.VisitPrefixes(Prefix(ip.MaskedBitString(refbits)), storeans)
	return hitted, items
}
```

- 指定されたIPアドレスに一致するすべてのプレフィックスとそのアイテムを検索します。

#### `SearchLongestIP`

```go
func (routingtable *RoutingTablePatriciaTrie) SearchLongestIP(ip ipaddress.IPaddress, refbits int) (string, Item){
	hitted, hoge := routingtable.SearchIP(ip, refbits)
	return hitted[len(hitted)-1], hoge[len(hoge)-1]
}
```

- 指定されたIPアドレスに一致する最も長いプレフィックスとそのアイテムを検索します。

#### `ResetTreeDepth`

```go
func (routingtable *RoutingTablePatriciaTrie) ResetTreeDepth() {
	storeans := func(prefix Prefix, item Item) error {
		temp := item.(Data)
		temp.Depth = 0
		routingtable.RoutingTablePatriciaTrie.Set(prefix, temp)
		return nil
	}

	routingtable.RoutingTablePatriciaTrie.VisitSubtree(Prefix(""), storeans)
}
```

- すべてのノードの深さをリセットします。

#### `ReadRule`

```go
func (routingtable *RoutingTablePatriciaTrie) ReadRule(fp *os.File) {
	scanner := bufio.NewScanner(fp)

	for scanner.Scan() {
		slice := strings.Split(scanner.Text(),

 " ")

		ip := ipaddress.NewIPaddress(slice[0])
		i, _ := strconv.Atoi(slice[1])

		a := ip.MaskedBitString(i)
		var item Data
		item.nexthop = slice[2]

		/////// need to fix

		if len(a) <= 16{
			item.Depth = 2
		}else if len(a) <= 24{
			item.Depth = 3
		}else if len(a) <= 32{
			item.Depth = 4
		}

		//////

		routingtable.RoutingTablePatriciaTrie.Insert(Prefix( ip.MaskedBitString(i) ), item)
	}
}
```

- ルールをファイルから読み取り、ルーティングテーブルに挿入します。

### コンストラクタ

#### `NewRoutingTablePatriciaTrie`

```go
func NewRoutingTablePatriciaTrie() *RoutingTablePatriciaTrie {
	trie := NewTrie()
	trie = NewTrie(MaxPrefixPerNode(33), MaxChildrenPerSparseNode(257))

	return &RoutingTablePatriciaTrie{
		RoutingTablePatriciaTrie: trie,
	}
}
```

- 新しいルーティングテーブルを初期化します。

### テスト用関数

#### `p`

```go
func p (hoge interface{}){
	fmt.Println(hoge)
}
```

- デバッグ用に任意のデータを出力します。

## 注意点

- 一部のコード（例えば `ReadRule` の `Depth` の設定部分）にはコメントで「need to fix」と書かれており、修正が必要です。
- `panic("Isleaf")` はエラーハンドリングの改善が必要です。

このコードはPatricia Trieを使って効率的にIPルーティングテーブルを管理するための基本的な実装を提供していますが、いくつかの部分は改善が必要です。
