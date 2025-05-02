以下は、提供されたGo言語のTrie構造体とそのメソッドに関するドキュメントの日本語訳です：
https://pkg.go.dev/github.com/tsuji1/go-patricia@v2.3.0+incompatible/patricia

https://github.com/tsuji1/go-patricia
---

### 関数

#### NewTrie
```go
func NewTrie(options ...Option) *Trie
```
Trieのコンストラクタ。

#### Clone
```go
func (trie *Trie) Clone() *Trie
```
既存のTrieのコピーを作成します。両方のTrieに保存されたアイテムは共有されます。

#### Delete
```go
func (trie *Trie) Delete(key Prefix) (deleted bool)
```
指定されたプレフィックスによって表されるアイテムを削除します。マッチングノードが見つかり削除された場合にtrueを返します。

#### DeleteSubtree
```go
func (trie *Trie) DeleteSubtree(prefix Prefix) (deleted bool)
```
プレフィックスに完全に一致するサブツリーを見つけて削除します。サブツリーが見つかり削除された場合にtrueを返します。

#### Get
```go
func (trie *Trie) Get(key Prefix) (item Item)
```
指定されたキーに位置するアイテムを返します。このメソッドはやや危険で、内部ノードに到達する可能性があります。内部ノードは実際にはユーザー定義の値を表していないことがあるためです。nilを有効な値として使用する場合、この問題を回避するためにnilインターフェイスを有効な値として使用しないことが推奨されます。任意の型のゼロ値を使用するだけでこの問題を防ぐことができます。

#### Insert
```go
func (trie *Trie) Insert(key Prefix, item Item) (inserted bool)
```
指定されたプレフィックスを使用して新しいアイテムをTrieに挿入します。既存のアイテムを置き換えません。既にアイテムが存在する場合、falseを返します。

#### Item
```go
func (trie *Trie) Item() Item
```
このTrieのルートに保存されているアイテムを返します。

#### Match
```go
func (trie *Trie) Match(prefix Prefix) (matchedExactly bool)
```
`Get(prefix) != nil`が返す結果を返します。Getメソッドと同様の警告が適用されます。

#### MatchSubtree
```go
func (trie *Trie) MatchSubtree(key Prefix) (matched bool)
```
キーを拡張するサブツリーが存在する場合にtrueを返します。つまり、キーをプレフィックスとして持つキーがTrieに存在する場合にtrueを返します。

#### Set
```go
func (trie *Trie) Set(key Prefix, item Item)
```
Insertとほぼ同じように動作しますが、常にアイテムを設定し、以前に挿入されたアイテムを置き換える可能性があります。

#### Visit
```go
func (trie *Trie) Visit(visitor VisitorFunc) error
```
アルファベット順に非nilアイテムを含むすべてのノードに対してvisitorを呼び出します。visitorからエラーが返された場合、関数は木の訪問を停止し、そのエラーを返します。ただし、特別なエラー - SkipSubtreeの場合を除きます。この場合、Visitは現在のノードが表すサブツリーをスキップし、他の場所で続行します。

#### VisitPrefixes
```go
func (trie *Trie) VisitPrefixes(key Prefix, visitor VisitorFunc) error
```
キーのプレフィックスを表すノードのみを訪問します。明らかに、visitorからSkipSubtreeを返すことはここでは意味がありません。

#### VisitSubtree
```go
func (trie *Trie) VisitSubtree(prefix Prefix, visitor VisitorFunc) error
```
Visitとほぼ同じように動作しますが、プレフィックスに一致するノードのみを訪問します。

### 型

#### VisitorFunc
```go
type VisitorFunc func(prefix Prefix, item Item) error
```
prefixとitemを引数に取り、エラーを返す関数型です。

---

これで、GoのTrie構造体とそのメソッドに関する日本語訳が完了です。
