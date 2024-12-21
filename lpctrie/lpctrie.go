package lpctrie

import (
	"math/bits"
	"test-module/memorytrace"
	"unsafe"

	"github.com/shuc324/gopush-cluster/hlist"
)

// Key represents the type of the key.
type Key uint32

// Constants for thresholds.
const (
	InflateThresholdRoot = 30
	InflateThreshold     = 50
	HalveThresholdRoot   = 15
	HalveThreshold       = 25
	KeyLength            = 32
	MaxWork          = 10
	MaxStatDepth    = 32
	KeyMax               =  ^Key(0)
	MemoryLatency		=  50
)


// Node is an interface for Tnode and LeafNode.
type Node interface{}

type FibInfo struct {
    FibHash       *hlist.Element   // ハッシュリスト: ルーティングテーブルのハッシュエントリ
    FibLHash      *hlist.Element   // ハッシュリスト: ローカルルート専用のハッシュエントリ
    NhList        *hlist.Head    // リストヘッド: ネクストホップリストを管理
    // FibNet        *Net         // ネットワーク情報へのポインタ
    FibTreeRef    int32        // ツリー参照カウント（RCU用）
    FibClntRef    int32        // クライアント参照カウント
    FibFlags      uint32       // ルーティングエントリのフラグ
    FibDead       bool         // エントリが無効（削除済み）かどうか
    FibProtocol   uint8        // プロトコル（例: 静的ルート、RIP、OSPFなど）
    FibScope      uint8        // スコープ（ルートが適用される範囲）
    FibType       uint8        // ルートの種類（例: unicast, local, broadcast）
    FibPrefSrc    uint32       // プリファードソースアドレス
    FibTbID       uint32       // ルーティングテーブルの識別子
    FibPriority   uint32       // ルートの優先度（メトリクス）
    // FibMetrics    *DstMetrics  // メトリクス情報（例: MTU、RTT）
    FibNhs        int          // ネクストホップの数
    FibNhIsV6     bool         // ネクストホップが IPv6 アドレスかどうか
    NhUpdated     bool         // ネクストホップが更新されたかどうか
    PfsrcRemoved  bool         // プリファードソースが削除されたかどうか
    // Nh            *NextHop     // ネクストホップ情報へのポインタ
    // FibNh         []*FibNH     // ネクストホップ情報の配列
}
type FibAlias struct {
    FaList        *hlist.Element  // ハッシュリストのノード: 同じプレフィックスを持つルートエントリをリストとして管理
    FaInfo        *FibInfo    // ルーティング情報へのポインタ: ネクストホップやデバイス情報などの詳細情報
    FaDscp        uint8    // DSCP（DiffServ Code Point）値: トラフィックの優先度やクラス分けを表す値
    FaType        uint8       // ルートの種類: 通常のルート、ブラックホールルート、ローカルルートなどを指定
    FaState       uint8       // ルートの状態: アクティブかどうか、フラグなどの状態情報
    FaSlen        uint8       // プレフィックスの長さ（サフィックス長）: ルートのビットマスク長（例: /24 の場合は 24）
    TbID          uint32      // ルーティングテーブルID: ルートが属するテーブルの識別子
    FaDefault     int16       // デフォルトルートのフラグ: このルートがデフォルトルートかどうかを示す（-1 の場合はデフォルトではない）
    Offload       uint8       // ハードウェアオフロードフラグ: ルートがハードウェアにオフロードされているかどうか
    Trap          uint8       // トラップフラグ: パケットをユーザースペースに送る必要がある場合のフラグ
    OffloadFailed uint8       // オフロード失敗フラグ: ハードウェアオフロードが失敗した場合のフラグ
}


// KeyVector represents a node in the trie
type KeyVector struct {
    Key   Key         // t_key in C
    Pos   uint8          // Position, corresponding to `unsigned char`
    Bits  uint8          // Number of bits, corresponding to `unsigned char`
    Slen  uint8          // Suffix length
    Leaf  *hlist.Hlist     // List pointer for leaf nodes
    TNode []*KeyVector   // Child nodes for internal nodes
	TnodeInfo *TNode // 上のTNodeにアクセスするためのポインタこれは実装はない＞
}

// TNode represents a parent node in the trie
type TNode struct {
    EmptyChildren  uint32      // Corresponding to t_key in C
    FullChildren   uint32      // Corresponding to t_key in C
    Parent         *KeyVector  // Parent node pointer
    KV             []*KeyVector // Flexible array of KeyVector nodes
}

// TrieUseStats represents the usage statistics of a trie.
type TrieUseStats struct {
    Gets                  uint32 // ノード検索の試行回数
    Backtrack             uint32 // バックトラックした回数
    SemanticMatchPassed   uint32 // セマンティックマッチに成功した回数
    SemanticMatchMiss     uint32 // セマンティックマッチに失敗した回数
    NullNodeHit           uint32 // null ノードにヒットした回数
    ResizeNodeSkipped     uint32 // ノードのリサイズがスキップされた回数
}

// TrieStat represents the statistics of a trie structure.
type TrieStat struct {
    TotDepth     uint32    // トライ全体の深さ
    MaxDepth     uint32    // トライの最大深さ
    TNodes       uint32    // tnode（中間ノード）の数
    Leaves       uint32    // 葉ノードの数
    NullPointers uint32    // null ポインタの数
    Prefixes     uint32    // プレフィックスの数
    NodeSizes    [MaxStatDepth]uint32 // 各深さごとのノードサイズ
}


// Trie represents the root of a trie structure.
type Trie struct {
    KV    *KeyVector       // トライのルートノード
    Stats *TrieUseStats    // 使用統計情報（オプション）
}

func tnInfo(kv *KeyVector) *TNode {
    return kv.TnodeInfo
}


// Get the parent of the given TNode.
func nodeParent(tn *KeyVector) *KeyVector {
    if tn.TnodeInfo != nil {
        return tn.TnodeInfo.Parent
    }
    return nil
}


// nodeSetParent sets the parent node for the given KeyVector
func nodeSetParent(n *KeyVector, tp *KeyVector) {
    if n != nil {
        n.TnodeInfo.Parent = tp
    }
}


// Get the child node at the given index.
func getChild(tn *KeyVector, i uint32) *KeyVector {
    if i < uint32(len(tn.TNode)) {
        return tn.TNode[i]
    }
    return nil
}


// nodeInitParent initializes the parent node (similar to NODE_INIT_PARENT)
func nodeInitParent(n *KeyVector, p *KeyVector) {
	n.TnodeInfo.Parent = p
}

// childLength calculates the number of children in this node
// childLength calculates the number of children for a given node.
// If the node is a leaf, it returns 0, meaning no children are accessible.
func childLength(kv *KeyVector) uint32 {
    if kv == nil {
        return 0
    }
    return (1 << kv.Bits) & ^uint32(1)
}

// getCIndex calculates the index based on key and KeyVector
func getCIndex(key Key, kv *KeyVector) uint32 {
    return uint32((key ^ kv.Key) >> kv.Pos)
}

// getIndex calculates the index for the child
func getIndex(key Key, kv *KeyVector) uint32  {
	    if kv == nil {
        panic("KeyVector is nil in getIndex")
    }
    index := key ^ kv.Key

    // Simulating BITS_PER_LONG and KEYLENGTH checks
    bitsPerLong := uint8(64) // Assume 64 bits for a uint64
    keyLength := uint8(64)  // Assume 64 bits for key length

    if bitsPerLong <= keyLength && keyLength == kv.Pos {
        return 0
    }

    return uint32(index >> kv.Pos)
}
// getIndex calculates the index of the key in the node's children.
// func getIndex(key Key, kv *Tnode) uint64 {
// 	index := key ^ kv.key

// 	// Handle edge cases for KEYLENGTH and position.
// 	if  KeyLength == kv.pos {
// 		return 0
// 	}
// 	return uint64(index >> kv.pos)
// }


// emptyChildInc increments the count of empty children for the node.
// If the count overflows (becomes 0), it increments the full children count.
func emptyChildInc(n *KeyVector) {
    if n == nil || n.TnodeInfo == nil {
		panic("emptyChildInc: Node or TNodeInfo is nil")
    }

    parent := n.TnodeInfo
    parent.EmptyChildren++

    // オーバーフロー（EmptyChildren が 0 に戻った場合）をチェック
    if parent.EmptyChildren == 0 {
        parent.FullChildren++
    }
}

// emptyChildDec decrements the count of empty children for the node.
// If the count underflows (becomes 0), it decrements the full children count.
func emptyChildDec(n *KeyVector) {
    if n == nil || n.TnodeInfo == nil {
panic("emptyChildDec: Node or TNodeInfo is nil")
    }

    parent := n.TnodeInfo

    // アンダーフローをチェック
    if parent.EmptyChildren == 0 {
        parent.FullChildren--
    }

    parent.EmptyChildren--
}



// leafNew initializes a new leaf node and links it to a fib alias
func leafNew(key Key, fa *FibAlias) *KeyVector {
    if fa == nil {
        return nil
    }

    // Allocate a new KeyVector and TNode
    tnode := &TNode{}
    l := &KeyVector{
        Key:      key,
        Pos:      0,
        Bits:     0,
        Slen:     fa.FaSlen,
		Leaf:     hlist.New().Init(),
        TnodeInfo: tnode, // 親ノード情報
    }

    // Initialize leaf and link it to fib alias
	l.Leaf.PushFront(fa.FaList)
    return l
}


// tnodeNew creates a new tnode with the given parameters
func tnodeNew(key Key, pos uint8, bits uint8) *KeyVector {
	shift := pos + bits

	// 条件チェック: bits や pos の値が有効か
	if bits == 0 || shift > KeyLength { // Assuming KEYLENGTH = 64 for uint64
		// fmt.Printf("Invalid bits or position: bits=%d, pos=%d\n", bits, pos)
		panic("Invalid bits or position") // BUG_ON に相当
	}
	tnode := &TNode{}
	// KeyVector の作成
	tn := &KeyVector{
		Pos: pos,
		Bits: bits,
		Slen: pos,
		TnodeInfo: tnode, // TNode をリンク
	}
	tn.TNode = make([]*KeyVector, 1<<bits) // 子ノードのスライスを初期化


	// full_children または empty_children を設定
	if bits == KeyLength { // Assuming KEYLENGTH = 64
		tnode.FullChildren = 1
	} else {
		tnode.EmptyChildren = 1 << bits
	}


	if shift < KeyLength {
		key = (key >> uint(shift)) << uint(shift)
	} else {
		key = 0
	}

	
	tn.Key = key
	return tn
}


// putChildは指定された位置に子ノードを追加し、メタデータを更新します
func putChild(tn *KeyVector, i uint32, n *KeyVector) {
	if tn == nil {
		return
	}

	// 現在の子ノードを取得
	chi := getChild(tn, i)

	// インデックスが範囲外の場合はエラー
	if i >= childLength(tn) {
		// fmt.Printf("Index out of range i=%d,tn=%v \n",i,tn)
		panic("インデックスが範囲外です") // C の BUG_ON 相当
	}

	// 空の子ノードのカウントを更新
	if n == nil && chi != nil {
		emptyChildInc(tn)
	} else if n != nil && chi == nil {
		emptyChildDec(tn)
	}

	// 完全な子ノードのカウントを更新
	wasFull := tnodeFull(tn, chi)
	isFull := tnodeFull(tn, n)

	if wasFull && !isFull {
		tn.TnodeInfo.FullChildren--
	} else if !wasFull && isFull {
		tn.TnodeInfo.FullChildren++
	}

	// サフィックス長を更新
	if n != nil && tn.Slen < n.Slen {
		tn.Slen = n.Slen
	}

	// 指定された位置に子ノードを追加
	if i < uint32(len(tn.TNode)){ 
		tn.TNode[i] = n
		
	} else {
		// スライスを拡張してインデックスを確保
		// newChildren := make([]*KeyVector, i+1)
		// copy(newChildren, tn.TNode)
		// newChildren[i] = n
		// tn.TNode = newChildren
		
		// fmt.Printf("Index out of range i=%d,tn=%v \n",i,tn)

		panic("インデックスが範囲外です") // C の BUG_ON 相当
	}
}


// tnode 'n' が "full"（完全）かどうかを確認します。つまり、それが内部ノードであり、スキップされたビットがない状態であることを意味します。詳細については、dyntree 論文の6ページを参照してください。
func tnodeFull(tn, n *KeyVector ) bool {
    // Check if the child is full
    return n != nil &&
        (n.Pos+n.Bits == tn.Pos) &&
		isTNode(n)
}



// updateChildren updates the parent reference for all children of a node.
func updateChildren(tn *KeyVector) {
	for i := childLength(tn); i >0 ; {
		i -= 1
		child := getChild(tn, i)
		if child == nil {
			continue
		}

		// If the child already points to this parent, recurse.
		if nodeParent(child) == tn {
			updateChildren(child)
		} else {
			// Otherwise, update the parent reference.
			nodeSetParent(child, tn)
		}
	}
}


// 条件マクロをGoで再現
func isTrie(n *KeyVector) bool {
	return n != nil && n.Pos >= KeyLength 
}

func isTNode(n *KeyVector) bool {
	return n != nil && n.Bits > 0
}

func isLeaf(n *KeyVector) bool {
	return n != nil && n.Bits == 0
}

// putChildRootはトライのルートノードまたは通常ノードに子ノードを設定します
func putChildRoot(tp *KeyVector, key Key, n *KeyVector) {
	if isTrie(tp) {
		// fmt.Printf("Root node is  trie: %v\n", tp)
		// ルートノードの場合、インデックス0に設定
		tp.TNode[0] = n
	} else {
		// 通常ノードの場合、キーからインデックスを計算して設定
		index :=  getIndex(key, tp)
		putChild(tp, index, n)
	}
}


// NewTrie initializes and returns a new trie.
func NewTrie() *Trie {
    kv := &KeyVector{
        Key:  0,
        Pos:  32, // ルートノードのposはKeyLength
        Bits: 1,         // デフォルトでbitsは0
		Slen: 0,
    }
	kv.Leaf =  hlist.New().Init()
    
    kv.TNode = make([]*KeyVector, 2) // ルートノードのTNodeスライスを初期化
    return &Trie{KV: kv}
}

func tnodeFree(tn *KeyVector) {
	
	if tn == nil {
		return
	}

	tn.TNode = nil
	tn.Leaf = nil
	tn.TnodeInfo = nil

}

// replaceは古いノードを新しいノードに置き換えます
func Replace(t *Trie, oldTNode, tn *KeyVector) *KeyVector {
	// if t == nil || oldTNode == nil || tn == nil {
	// 	return nil
	// }
	// fmt.Println("In replace")

	// 親ノードを取得
	
	tp := nodeParent(oldTNode) 

	// 新しいノードの親を設定し、親ノードの子として登録
	nodeInitParent(tn, tp)
	putChildRoot(tp, tn.Key, tn)

	// 子ノードの親ポインタを更新
	updateChildren(tn)

	// 古いノードを削除（tnode_free相当）

	tnodeFree(oldTNode)

	// 子ノードのリサイズ処理
	for i := childLength(tn) ; i> 0; {
		i -= 1
		inode := getChild(tn, i)
		if(tnodeFull(tn, inode)){
			tn= Resize(t, inode)
		}
	}

	return tp;
}




// inflateは古いノードを展開し、新しいノードに置き換えます
func Inflate(t *Trie, oldTNode *KeyVector) *KeyVector {
	// fmt.Println("In inflate")
	if oldTNode == nil {
		return nil
	}

	// 新しいノードを作成
	tn := tnodeNew(oldTNode.Key, oldTNode.Pos-1, oldTNode.Bits+1)
	if tn == nil {
		// fmt.Println("ノード作成に失敗しました")
		return nil
	}

	// 古いノードの初期化（削除準備）
	// oldTNode.TNode = nil
	// oldTNode.Leaf = nil
	// oldTNode.TnodeInfo = nil

	// 古いノードの子ノードを処理
	 /* クラスター内のすべてのポインタを構成します。この場合、
 * 割り当てられたノードから既存の tnode を指すすべてのポインタと、
 * 割り当てられたノード間のリンクを表します。
 */

	for i,m := childLength(oldTNode),1<<tn.Pos; i>0 ; {
		i-=1
		inode := getChild(oldTNode, i)
		// 空の子ノードはスキップ
		if inode == nil {
			continue
		}

		// 葉ノードまたはスキップされたビットを持つ内部ノード
		if !tnodeFull(oldTNode, inode) {
			index := getIndex(inode.Key, tn)
			putChild(tn, index, inode)
			continue
		}
		
		if(inode.Bits == 1){
			putChild(tn,2 *i +1,getChild(inode,1));
			putChild(tn,2 *i,getChild(inode,0));
			continue
		}
		
		/* このノード 'inode' を 2 つの新しいノード 'node0' と 'node1' に置き換えます。
 * それぞれ元の子ノードの半分を持ちます。この 2 つの新しいノードは、
 * キー内で現在の位置から 1 ビット下の位置を持つことになります。
 * これにより、それぞれのキーの「重要な部分」
 * （このファイルの冒頭近くで説明しています）が 1 ビットだけ異なります。
 * node0 のキーではこのビットは "0" になり、node1 のキーでは "1" になります。
 * キー位置を 1 ステップ下げるため、現在の位置（tn->pos）にあるビットが
 * node0 と node1 のキーの違いを生み出すことになります。
 * そこで、この 2 つの新しいキーにそのビットを合成します。
 */

		// 新しいノードを2つ作成し、子ノードを分割して割り当て
		node1 := tnodeNew(inode.Key|Key(m),inode.Pos, inode.Bits-1)
		node0 := tnodeNew(inode.Key, inode.Pos, inode.Bits-1)

		if node0 == nil || node1 == nil {
			// fmt.Println("メモリ不足でノード作成に失敗しました")
			return nil
		}

		// 子ノードを分配
		k := childLength(inode)
		for j := k / 2; j > 0;  {
			j-=1
			k-=1
			putChild(node1, j, getChild(inode,k))
			putChild(node0, j, getChild(inode,j))
			j-=1
			k-=1
			        putChild(node1, j, getChild(inode, k)) // node1 に次の k 番目の子を追加
        putChild(node0, j, getChild(inode, j)) // node0 に次の j 番目の子を追加
		}

		// 新しいノードを親ノードにリンク
		nodeInitParent(node1,tn)
		nodeInitParent(node0,tn)

		// 親ノードの子として登録
		putChild(tn, 2*i+1, node1)
		putChild(tn, 2*i, node0)
	}

	// 古いノードを新しいノードに置き換える
	return Replace(t, oldTNode, tn)
}


func Halve(t *Trie, oldtnode *KeyVector) *KeyVector {
	// fmt.Println("In halve")

	tn := tnodeNew(oldtnode.Key, oldtnode.Pos+1, oldtnode.Bits-1)


	// クラスター内のすべてのポインタをまとめる。この場合、割り当てられたノードから
	// 既存のtnodeを指すすべてのポインタと、割り当てられたノード間のリンクを表す。
	for i := childLength(oldtnode); i > 0; {
		i--
		node1 := getChild(oldtnode, i)
		i--
		node0 := getChild(oldtnode, i)
		var inode *KeyVector

		// 子のうち少なくとも1つが空の場合
		if node1 == nil || node0 == nil {
			putChild(tn, i/2, func() *KeyVector {
				if node1 != nil {
					return node1
				}
				return node0
			}())
			continue
		}
		if oldtnode == nil {
			panic("ノードが見つかりません")
		}

		// 2つの非空の子
		inode = tnodeNew(node0.Key, oldtnode.Pos, 1)
		if inode == nil {
			panic("ノード作成に失敗しました")
		}

		// nodeから出るポインタを初期化
		putChild(inode, 1, node1)
		putChild(inode, 0, node0)
		nodeInitParent(inode, tn)

		// 親からnodeへのリンク
		putChild(tn, i/2, inode)
	}

	// このノード内外の親ポインタを設定
	return Replace(t, oldtnode, tn)

}



func Collapse(t *Trie, oldtnode *KeyVector) *KeyVector {
	// fmt.Println("In collapse")
	var n *KeyVector 
	var tp *KeyVector

	n = nil
	// tnodeを走査して、まだ存在する可能性のある1つの子を探す
	for i := childLength(oldtnode); i > 0 && n == nil ;{
		i-=1
		n = getChild(oldtnode, i)
	}

	// 1レベル圧縮
	tp = nodeParent(oldtnode)
	putChildRoot(tp, oldtnode.Key, n)
	nodeSetParent(n, tp)

	// 不要になったノードを削除
	oldtnode = nil

	return tp
}


func UpdateSuffix(tn *KeyVector) uint8 {
	slen := tn.Pos
	var stride, i uint32
	var slenMax uint8

	/* ベクトル0のみが tn->pos + tn->bits 以上の接尾辞長を持つことができる。
	 * 2番目に高いノードは、最大で tn->pos + tn->bits - 1 の接尾辞長を持つ。
	 */
	slenMax = min(tn.Pos+tn.Bits-1, tn.Slen)

	/* 子ノードのリストを検索し、現在持っているものよりも長い接尾辞を持つ
	 * ノードを探す。このため、strideを2から始める。strideが1の場合は、
	 * tn->posと等しい接尾辞長を持つノードを表すからである。
	 */
	for i, stride = 0, 2; i < childLength(tn); i += stride {
		n := getChild(tn, i)

		if n == nil || n.Slen <= slen {
			continue
		}

		/* 新しい値に基づいてstrideとslenを更新 */
		stride <<= (n.Slen - slen)
		slen = n.Slen
		i &= ^(stride - 1)

		/* 最大値に達した場合は検索を停止 */
		if slen >= slenMax {
			break
		}
	}

	tn.Slen = slen

	return slen
}




/* 「動的圧縮トライの実装」 (Implementing a dynamic compressed trie)  
 * ヘルシンキ工科大学のStefan Nilsson氏とNokia TelecommunicationsのMatti Tikkanen氏による論文、  
 * 6ページ目より：  
 * 「ノードは、*拡張された*ノード内の非空の子の比率が 'high' 以上である場合に倍増される。」  
 *
 * ここでの 'high' は変数 'inflate_threshold' に相当します。  
 * これはパーセンテージで表現されているため、child_length() に掛け合わせます。  
 * さらに、配列が inflate() によって倍増されるため、左辺を 100 で掛け算する代わりに 50 を掛けます（パーセンテージを扱う都合上）。  
 *
 * 左辺の式は少し奇妙に見えるかもしれません：  
 * `child_length(tn) - tn->empty_children` は現在のノード内の非ヌルの子の数です。  
 * `tn->full_children` は「完全な」子の数、つまりスキップ値が 0 の非ヌルな tnode を指します。  
 * これらのすべては、結果として得られる拡張された tnode において倍増されるため、ここで単にもう一回分カウントしています。  
 *
 * より明確な表現としては次のように書くことができます：  
 *
 * ```c
 * to_be_doubled = tn->full_children;
 * not_to_be_doubled = child_length(tn) - tn->empty_children - tn->full_children;
 *
 * new_child_length = child_length(tn) * 2;
 *
 * new_fill_factor = 100 * (not_to_be_doubled + 2 * to_be_doubled) / new_child_length;
 * if (new_fill_factor >= inflate_threshold)
 * ```
 *
 * ・・・という感じですが、これは while () ループを複雑にしてしまいます。
 *
 * ともかく、次のような式になります：  
 * `100 * (not_to_be_doubled + 2 * to_be_doubled) / new_child_length >= inflate_threshold`  
 *
 * 割り算を避けます：  
 * `100 * (not_to_be_doubled + 2 * to_be_doubled) >= inflate_threshold * new_child_length`  
 *
 * `not_to_be_doubled` と `to_be_doubled` を展開して短縮化すると：  
 * `100 * (child_length(tn) - tn->empty_children + tn->full_children) >= inflate_threshold * new_child_length`  
 *
 * `new_child_length` を展開すると：  
 * `100 * (child_length(tn) - tn->empty_children + tn->full_children) >= inflate_threshold * child_length(tn) * 2`  
 *
 * 再び短縮すると：  
 * `50 * (tn->full_children + child_length(tn) - tn->empty_children) >= inflate_threshold * child_length(tn)`  
 *
 */  



 // shouldInflate: ノードを膨張させる必要があるか確認
func shouldInflate(tp, tn *KeyVector) bool {
	used := childLength(tn)
	threshold := used

	// ルートノードを大きく保つ
	if isTrie(tp) {
		threshold *= InflateThresholdRoot
	} else {
		threshold *= InflateThreshold
	}
	used -= tnInfo(tn).EmptyChildren
	used += tnInfo(tn).FullChildren

	// bits == KEYLENGTHの場合、pos = 0 となり、以下で失敗する
	return (used > 1) && tn.Pos > 0 && ((50 * used) >= threshold)
}

// shouldHalve: ノードを半減させる必要があるか確認
func shouldHalve(tp, tn *KeyVector) bool {
	used := childLength(tn)
	threshold := used

	// ルートノードを大きく保つ
	if isTrie(tp) {
		threshold *= HalveThresholdRoot
	} else {
		threshold *= HalveThreshold
	}
	used -= tnInfo(tn).EmptyChildren

	// bits == KEYLENGTHの場合、使用率は100%となり、以下で失敗する
	return (used > 1) && (tn.Bits > 1) && ((100 * used) < threshold)
}

// shouldCollapse: ノードを崩壊させる必要があるか確認
func shouldCollapse(tn *KeyVector) bool {
	used := childLength(tn)
	used -= tnInfo(tn).EmptyChildren

	// bits == KEYLENGTHの場合を考慮
	if tn.Bits == KeyLength && tnInfo(tn).FullChildren > 0 {
		used -= uint32(KeyMax)
}

	// 子が1つまたは存在しない場合、トライから削除する時期
	return used < 2
}


func Resize(t *Trie, tn *KeyVector) *KeyVector {
	stats := t.Stats	
	tp := nodeParent(tn)
	
	cindex := getIndex(tn.Key, tp)
	maxWork := MaxWork

	// tnode_resize内でのデバッグ情報出力
	// fmt.Printf("In tnode_resize %p inflate_threshold=%d threshold=%d\n", tn, InflateThreshold, HalveThreshold)

	/* 親からのポインタを介してtnodeを追跡。
	 * これにより、RCUが完全に機能し、我々が干渉することを防ぐ。
	 */
	if tn != getChild(tp, cindex) {
		// fmt.Printf("tn=%v, parent=%v, child=%v\n", tn, tp, getChild(tp, cindex))
		// fmt.Printf("Key=%32b, Pos=%d, Bits=%d, Slen=%d\n", tn.Key, tn.Pos, tn.Bits, tn.Slen)
		panic("BUG: tn does not match parent child")
	}

	/* 非空ノードの数が閾値を超える限り、ノードを倍増 */
	for shouldInflate(tp, tn) && maxWork > 0 {
		tp = Inflate(t, tn)
		if tp == nil {
			// CONFIG_IP_FIB_TRIE_STATS が有効な場合の統計更新
			stats.ResizeNodeSkipped++
			// 実装依存のため省略可能
			break
		}
		maxWork--
		tn = getChild(tp, cindex)
	}
	// fmt.Println("after inflate")
	// DebugPrint(t)

	/* inflateが失敗した場合、親を更新 */
	tp = nodeParent(tn)

	/* 少なくとも1回inflateが実行された場合、親を返す */
	if maxWork != MaxWork {
		return tp
	}

	/* このノードの空の子の数が閾値を超える限り、ノードを半減 */
	for shouldHalve(tp, tn) && maxWork > 0 {
		tp = Halve(t, tn)
		if tp == nil {
			// CONFIG_IP_FIB_TRIE_STATS が有効な場合の統計更新
			stats.ResizeNodeSkipped++
			// 実装依存のため省略可能
			break
		}
		maxWork--
		tn = getChild(tp, cindex)
	}
	// fmt.Println("after halve")
	// DebugPrint(t)

	/* 子が1つだけ残っている場合 */
	if shouldCollapse(tn) {
		return Collapse(t, tn)
	}

	/* halveが失敗した場合、親を返す */
	return nodeParent(tn)
}


// nodePullSuffix: ノードの接尾辞を引き下げる
func nodePullSuffix(tn *KeyVector, slen uint8) {
	nodeSlen := tn.Slen

	for (nodeSlen > tn.Pos) && (nodeSlen > slen) {
		slen = UpdateSuffix(tn)
		if nodeSlen == slen {
			break
		}

		tn = nodeParent(tn)
		nodeSlen = tn.Slen
	}
}

// nodePushSuffix: ノードの接尾辞を押し上げる
func nodePushSuffix(tn *KeyVector, slen uint8) {
	if tn == nil {
		panic("ノードがnilです")
	}
	// fmt.Println("In nodePushSuffix")
	for tn != nil && tn.Slen < slen {
		// fmt.Printf("tn.Slen=%d slen=%d\n", tn.Slen, slen)
		tn.Slen = slen
		tn = nodeParent(tn)
	}
}



func FibFindNode(t *Trie, tp **KeyVector, key Key) *KeyVector {
	var pn, n *KeyVector = nil, t.KV
	var index uint32 = 0

	for {
		pn = n
		n = getChild(n, index)

		if n == nil {
			break
		}

		index = getCIndex(key, n)

		/* この部分のコードは少々トリッキーですが、複数のチェックを
		 * 1つのチェックにまとめています。prefixは、prefixにcindex内の
		 * ビット分の0を加えたものです。indexはkeyとこの値の差です。
		 * これにより、以下のデータを導出できます。
		 *   if (index >= (1ul << bits))
		 *     skipビットに不一致があり失敗したことを示します。
		 *   else
		 *     値がcindexであることがわかります。
		 *
		 * bits == KEYLENGTHの場合でも、このチェックは安全です。
		 * 理由は、32ビットのノードを割り当てるのは、long型が32ビットより
		 * 大きい場合に限られるからです。
		 */
		if index >= (1 << n.Bits) {
			n = nil
			break
		}

		// 完全一致のリーフまたはNULLが見つかるまで検索を続ける
		if !isTNode(n) {
			break
		}
	}

	*tp = pn

	return n
}


// trieRebalance: トライを再バランスする
func trieRebalance(t *Trie, tn *KeyVector) {

	for !isTrie(tn) {
		// fmt.Printf("In trieRebalance %v,resizeCount=%d\n", tn,resizeCount)
		tn = Resize(t, tn)
	}
}

// fibInsertNode: トライにノードを挿入
func FibInsertNode(t *Trie, tp *KeyVector, new *FibAlias, key Key) int {
	l := leafNew(key, new)

	// fmt.Printf("In FibInsertNode %v\n", l)
	if l == nil {
		// 新しいリーフの作成に失敗
		panic("メモリ不足")
	}

	// 親ノードから子ノードを取得
	n := getChild(tp, getIndex(key, tp))

	/* ケース2: nがLEAFまたはTNODEで、キーが一致しない場合
	 *
	 *  新しいtnodeをここに追加
	 *  最初のtnodeには特別な処理が必要
	 *  ケース3として扱う準備をする
	 */
	if n != nil {
		npos := fls(uint32(key^n.Key))
		tn := tnodeNew(key,npos , 1)
		if tn == nil {
			// 新しいtnodeの作成に失敗
			panic("メモリ不足")
		}

		// ノードからのルートを初期化
		nodeInitParent(tn, tp)
		putChild(tn, getIndex(key, tn)^1, n)

		// ノードへのルートを追加開始
		putChildRoot(tp, key, tn)
		nodeSetParent(n, tn)

		// 親ノードにリーフを挿入する空きスロットを作成
		tp = tn
	}

	/* ケース3: nがNULLの場合、新しいリーフを挿入するだけ */
	nodePushSuffix(tp, new.FaSlen)
	nodeInitParent(l, tp)
	putChildRoot(tp, key, l)
	// fmt.Printf("In FibInsertNode tp = %v\n", tp)
	// DebugPrint(t)
	trieRebalance(t, tp)

	return 0
}


// // DebugPrint prints the trie structure (for debugging purposes).
func  DebugPrint(t *Trie) {
	var printNode func(node *KeyVector, depth int)
	printNode = func(node *KeyVector, depth int) {
		if node == nil {
			return
		}

		prefix := ""
		for i := 0; i < depth; i++ {
			prefix += "  "
		}

		// fmt.Printf("%sNode: Key=%32b, Pos=%d, Bits=%d, Slen=%d\n",
			// prefix, node.Key, node.Pos, node.Bits, node.Slen)
		for _, child := range node.TNode {
			printNode(child, depth+1)
		}
	}

	printNode(t.KV, 0)
}


// fls: 与えられた整数の中で最上位のセットされたビットの位置を返す
// 戻り値: ビット位置（1ベース）。セットされたビットがない場合は0。
func fls(value uint32) uint8 {
	if value == 0 {
		return 0
	}
	// bits.Lenは1ベースのビット長を返すため、そのまま利用
	return uint8(bits.Len(uint(value)))-1 
}



func FibInsert(t *Trie, key Key, fa *FibAlias) int {
	var tp *KeyVector
	l := FibFindNode(t, &tp, key)
	if l != nil {
		// キーがすでに存在する
		return -1
	}
	return FibInsertNode(t, tp, fa, key)
}

// アクセスする回数としている。root の深さを1としている。
func GetDepth(t *Trie, key Key) int {
	var tp *KeyVector
	l := FibFindNode(t, &tp, key)
	if(l == nil){
		l=tp
	}
	depth := 0
	addingcycle := uint64(1)
	nowCycle := memorytrace.GetCycleCounter()
	for {
		if l == nil {
			break
		}
		l = nodeParent(l)
		if(l != nil){
		cycle := nowCycle+addingcycle+MemoryLatency
		dramAccess := memorytrace.NewDRAMAccess(cycle,uintptr(unsafe.Pointer(l)))
		_ = dramAccess
		// memorytrace.AddDRAMAccess(dramAccess)
		}
		depth += 1
	}
	return depth 
}
