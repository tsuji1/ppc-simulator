package lpctrie

// import (
// 	"fmt"
// )

// // キーの型（IPv4アドレスを想定）
// type Key uint32

// const (
// 	KEYLENGTH         = 32 // キーのビット数
// 	MAXBITS           = 16 // ノードの最大ビット数
// 	INFLATE_THRESHOLD = 50 // インフレの閾値（パーセント）
// 	HALVE_THRESHOLD   = 25 // ハーフの閾値（パーセント）
// )

// // ノードのインターフェース
// type Node interface {
// 	IsLeaf() bool
// 	GetKey() Key
// 	GetPos() uint8
// 	GetBits() uint8
// 	SetParent(parent *Tnode)
// }

// // リーフノード
// type Leaf struct {
// 	key       Key
// 	prefixLen uint8 // プレフィックス長
// 	parent    *Tnode
// 	data      interface{}
// }

// func (l *Leaf) IsLeaf() bool {
// 	return true
// }

// func (l *Leaf) GetKey() Key {
// 	return l.key
// }

// func (l *Leaf) GetPos() uint8 {
// 	return 0
// }

// func (l *Leaf) GetBits() uint8 {
// 	return 0
// }

// func (l *Leaf) SetParent(parent *Tnode) {
// 	l.parent = parent
// }

// // 内部ノード（Tnode）
// type Tnode struct {
// 	key           Key
// 	pos           uint8
// 	bits          uint8
// 	parent        *Tnode
// 	children      []Node
// 	emptyChildren int
// 	fullChildren  int
// 	maxPrefixLen  uint8 // サブトリー内の最大プレフィックス長
// }

// func (t *Tnode) IsLeaf() bool {
// 	return false
// }

// func (t *Tnode) GetKey() Key {
// 	return t.key
// }

// func (t *Tnode) GetPos() uint8 {
// 	return t.pos
// }

// func (t *Tnode) GetBits() uint8 {
// 	return t.bits
// }

// func (t *Tnode) SetParent(parent *Tnode) {
// 	t.parent = parent
// }

// func NewLeaf(key Key, prefixLen uint8, data interface{}) *Leaf {
// 	return &Leaf{
// 		key:       key,
// 		prefixLen: prefixLen,
// 		data:      data,
// 	}
// }

// func NewTnode(key Key, pos, bits uint8) *Tnode {
// 	if bits > MAXBITS {
// 		bits = MAXBITS
// 	}
// 	size := 1 << bits
// 	return &Tnode{
// 		key:      key &^ ((1 << (KEYLENGTH - int(pos+bits))) - 1),
// 		pos:      pos,
// 		bits:     bits,
// 		children: make([]Node, size),
// 		// 初期状態ではすべての子が空
// 		emptyChildren: size,
// 	}
// }

// // Trie構造体
// type Trie struct {
// 	root *Tnode
// }

// func NewTrie() *Trie {
// 	return &Trie{
// 		root: NewTnode(0, 0, 0),
// 	}
// }

// // インデックスを取得するヘルパー関数
// func getIndex(key Key, node *Tnode) uint32 {
// 	if node.pos+node.bits > KEYLENGTH {
// 		return 0
// 	}
// 	shift := KEYLENGTH - (node.pos + node.bits)
// 	index := (key >> shift) & ((1 << node.bits) - 1)
// 	return uint32(index)
// }

// // Insert関数
// func (t *Trie) Insert(key Key, prefixLen uint8, data interface{}) {
// 	t.insertNode(t.root, key, prefixLen, data)
// }

// func (t *Trie) insertNode(node *Tnode, key Key, prefixLen uint8, data interface{}) {
// 	if node.bits == 0 {
// 		// 初回の挿入でルートノードを拡張
// 		node.bits = 1
// 		node.children = make([]Node, 2)
// 		node.emptyChildren = 2
// 	}

// 	index := getIndex(key, node)

// 	if int(index) >= len(node.children) {
// 		// インデックスが範囲外
// 		// これをソースでは考慮しているように見えなかったが？
// 		panic("index out of range")
// 	}

// 	child := node.children[index]

// 	if child == nil {
// 		// 子が存在しない場合、新しいリーフを挿入
// 		leaf := NewLeaf(key, prefixLen, data)
// 		leaf.SetParent(node)
// 		node.children[index] = leaf
// 		node.emptyChildren--
// 		if node.maxPrefixLen < prefixLen {
// 			node.maxPrefixLen = prefixLen
// 			t.updateMaxPrefixLen(node.parent, prefixLen)
// 		}
// 		t.resize(node)
// 	} else if child.IsLeaf() {
// 		existingLeaf := child.(*Leaf)
// 		if existingLeaf.key == key && existingLeaf.prefixLen == prefixLen {
// 			// キーとプレフィックス長が同じ場合、データを更新
// 			existingLeaf.data = data
// 		} else {
// 			// 新しいTnodeを作成して衝突を解決
// 			newPos := node.pos + node.bits
// 			maxBits := uint8(KEYLENGTH - int(newPos))
// 			var newBits uint8 = 1
// 			for newBits <= maxBits && newBits <= MAXBITS {
// 				existingBit := (existingLeaf.key >> (KEYLENGTH - int(newPos+newBits))) & 1
// 				newKeyBit := (key >> (KEYLENGTH - int(newPos+newBits))) & 1
// 				if existingBit != newKeyBit {
// 					break
// 				}
// 				newBits++
// 			}
// 			if newBits > MAXBITS {
// 				newBits = MAXBITS
// 			}

// 			newTnode := NewTnode(key, newPos, newBits)
// 			newTnode.SetParent(node)
// 			existingLeaf.SetParent(newTnode)
// 			existingIndex := getIndex(existingLeaf.key, newTnode)
// 			if int(existingIndex) >= len(newTnode.children) {
// 				// インデックスが範囲外の場合、bitsを調整
// 				newBits--
// 				newTnode = NewTnode(key, newPos, newBits)
// 				existingIndex = getIndex(existingLeaf.key, newTnode)
// 			}
// 			newTnode.children[existingIndex] = existingLeaf
// 			newTnode.emptyChildren--
// 			newTnode.maxPrefixLen = existingLeaf.prefixLen

// 			node.children[index] = newTnode
// 			node.fullChildren++
// 			if node.maxPrefixLen < prefixLen {
// 				node.maxPrefixLen = prefixLen
// 				t.updateMaxPrefixLen(node.parent, prefixLen)
// 			}
// 			t.insertNode(newTnode, key, prefixLen, data)
// 			t.resize(node)
// 		}
// 	} else {
// 		// 次のレベルに進む
// 		childTnode := child.(*Tnode)
// 		if childTnode.maxPrefixLen < prefixLen {
// 			childTnode.maxPrefixLen = prefixLen
// 			t.updateMaxPrefixLen(childTnode.parent, prefixLen)
// 		}
// 		t.insertNode(childTnode, key, prefixLen, data)
// 	}
// }

// // maxPrefixLenを上位ノードに伝搬するヘルパー関数
// func (t *Trie) updateMaxPrefixLen(node *Tnode, prefixLen uint8) {
// 	for node != nil && node.maxPrefixLen < prefixLen {
// 		node.maxPrefixLen = prefixLen
// 		node = node.parent
// 	}
// }

// // 最長一致検索を行うSearch関数
// func (t *Trie) Search(key Key) (interface{}, bool) {
// 	return t.searchNode(t.root, key, nil, 0)
// }

// func (t *Trie) searchNode(node *Tnode, key Key, bestMatch *Leaf, bestMatchLen uint8) (interface{}, bool) {
// 	if node == nil {
// 		if bestMatch != nil {
// 			return bestMatch.data, true
// 		}
// 		return nil, false
// 	}

// 	if node.maxPrefixLen <= bestMatchLen {
// 		// これ以上良いマッチはない
// 		if bestMatch != nil {
// 			return bestMatch.data, true
// 		}
// 		return nil, false
// 	}

// 	index := getIndex(key, node)
// 	if int(index) >= len(node.children) {
// 		if bestMatch != nil {
// 			return bestMatch.data, true
// 		}
// 		return nil, false
// 	}

// 	child := node.children[index]
// 	if child == nil {
// 		if bestMatch != nil {
// 			return bestMatch.data, true
// 		}
// 		return nil, false
// 	}

// 	if child.IsLeaf() {
// 		leaf := child.(*Leaf)
// 		if prefixMatch(leaf.key, leaf.prefixLen, key) && leaf.prefixLen > bestMatchLen {
// 			bestMatch = leaf
// 			bestMatchLen = leaf.prefixLen
// 		}
// 		return t.searchNode(nil, key, bestMatch, bestMatchLen)
// 	} else {
// 		childTnode := child.(*Tnode)
// 		return t.searchNode(childTnode, key, bestMatch, bestMatchLen)
// 	}
// }

// // プレフィックスがキーにマッチするかをチェックするヘルパー関数
// func prefixMatch(prefixKey Key, prefixLen uint8, key Key) bool {
// 	shift := KEYLENGTH - prefixLen
// 	return (prefixKey >> shift) == (key >> shift)
// }

// // Resize関数
// func (t *Trie) resize(node *Tnode) {
// 	if shouldInflate(node) {
// 		t.inflate(node)
// 	} else if shouldHalve(node) {
// 		t.halve(node)
// 	} else if shouldCollapse(node) {
// 		t.collapse(node)
// 	}
// }

// // Inflating条件をチェックする関数
// func shouldInflate(node *Tnode) bool {
// 	if node.bits == 0 || node.bits >= MAXBITS {
// 		return false
// 	}
// 	used := len(node.children) - node.emptyChildren + node.fullChildren
// 	threshold := len(node.children) * INFLATE_THRESHOLD / 100
// 	return used >= threshold
// }

// // Halving条件をチェックする関数
// func shouldHalve(node *Tnode) bool {
// 	if node.bits <= 1 {
// 		return false
// 	}
// 	used := len(node.children) - node.emptyChildren
// 	threshold := len(node.children) * HALVE_THRESHOLD / 100
// 	return used <= threshold
// }

// // Collapsing条件をチェックする関数
// func shouldCollapse(node *Tnode) bool {
// 	used := len(node.children) - node.emptyChildren
// 	return used <= 1 && node.parent != nil
// }

// // Inflate関数
// func (t *Trie) inflate(node *Tnode) {
// 	if node.bits >= MAXBITS {
// 		return
// 	}
// 	oldBits := node.bits
// 	newBits := oldBits + 1
// 	if newBits > MAXBITS {
// 		newBits = MAXBITS
// 	}
// 	newSize := 1 << newBits
// 	newChildren := make([]Node, newSize)
// 	for i, child := range node.children {
// 		if child == nil {
// 			continue
// 		}
// 		if child.IsLeaf() || child.(*Tnode).bits != node.bits {
// 			// 子を新しい位置に移動
// 			newIndex := i * 2
// 			if newIndex >= newSize {
// 				continue
// 			}
// 			newChildren[newIndex] = child
// 			child.SetParent(node)
// 		} else {
// 			// 子ノードを分割
// 			childTnode := child.(*Tnode)
// 			for j, grandChild := range childTnode.children {
// 				if grandChild == nil {
// 					continue
// 				}
// 				newIndex := (i << 1) | (j)
// 				if int(newIndex) >= newSize {
// 					continue
// 				}
// 				newChildren[newIndex] = grandChild
// 				grandChild.SetParent(node)
// 			}
// 		}
// 	}
// 	node.bits = newBits
// 	node.children = newChildren
// 	node.emptyChildren = newSize - (len(newChildren) - node.emptyChildren)
// 	// maxPrefixLenの更新
// 	node.maxPrefixLen = 0
// 	for _, child := range node.children {
// 		if child != nil {
// 			if child.IsLeaf() {
// 				leaf := child.(*Leaf)
// 				if node.maxPrefixLen < leaf.prefixLen {
// 					node.maxPrefixLen = leaf.prefixLen
// 				}
// 			} else {
// 				tnode := child.(*Tnode)
// 				if node.maxPrefixLen < tnode.maxPrefixLen {
// 					node.maxPrefixLen = tnode.maxPrefixLen
// 				}
// 			}
// 		}
// 	}
// }

// // Halve関数
// func (t *Trie) halve(node *Tnode) {
// 	if node.bits <= 1 {
// 		return
// 	}
// 	oldBits := node.bits
// 	newBits := oldBits - 1
// 	newSize := 1 << newBits
// 	newChildren := make([]Node, newSize)
// 	for i := range newChildren {
// 		leftIndex := i * 2
// 		rightIndex := leftIndex + 1
// 		var child Node
// 		if leftIndex < len(node.children) && node.children[leftIndex] != nil && (rightIndex >= len(node.children) || node.children[rightIndex] == nil) {
// 			child = node.children[leftIndex]
// 		} else if rightIndex < len(node.children) && node.children[rightIndex] != nil && (leftIndex >= len(node.children) || node.children[leftIndex] == nil) {
// 			child = node.children[rightIndex]
// 		} else if leftIndex < len(node.children) && rightIndex < len(node.children) && node.children[leftIndex] != nil && node.children[rightIndex] != nil {
// 			// 両方の子を持つ新しいTnodeを作成
// 			newChild := NewTnode(node.key, node.pos+1, 1)
// 			newChild.SetParent(node)
// 			newChild.children[0] = node.children[leftIndex]
// 			newChild.children[1] = node.children[rightIndex]
// 			node.children[leftIndex].SetParent(newChild)
// 			node.children[rightIndex].SetParent(newChild)
// 			newChild.emptyChildren = 0
// 			newChild.maxPrefixLen = 0
// 			// maxPrefixLenの更新
// 			for _, grandChild := range newChild.children {
// 				if grandChild != nil {
// 					if grandChild.IsLeaf() {
// 						leaf := grandChild.(*Leaf)
// 						if newChild.maxPrefixLen < leaf.prefixLen {
// 							newChild.maxPrefixLen = leaf.prefixLen
// 						}
// 					} else {
// 						tnode := grandChild.(*Tnode)
// 						if newChild.maxPrefixLen < tnode.maxPrefixLen {
// 							newChild.maxPrefixLen = tnode.maxPrefixLen
// 						}
// 					}
// 				}
// 			}
// 			child = newChild
// 		} else {
// 			// 両方の子がnil
// 			continue
// 		}
// 		newChildren[i] = child
// 		child.SetParent(node)
// 	}
// 	node.bits = newBits
// 	node.children = newChildren
// 	node.emptyChildren = newSize - (len(newChildren) - node.emptyChildren)
// 	// maxPrefixLenの更新
// 	node.maxPrefixLen = 0
// 	for _, child := range node.children {
// 		if child != nil {
// 			if child.IsLeaf() {
// 				leaf := child.(*Leaf)
// 				if node.maxPrefixLen < leaf.prefixLen {
// 					node.maxPrefixLen = leaf.prefixLen
// 				}
// 			} else {
// 				tnode := child.(*Tnode)
// 				if node.maxPrefixLen < tnode.maxPrefixLen {
// 					node.maxPrefixLen = tnode.maxPrefixLen
// 				}
// 			}
// 		}
// 	}
// }

// // Collapse関数
// func (t *Trie) collapse(node *Tnode) {
// 	// ノードを唯一の子で置き換える
// 	var onlyChild Node
// 	for _, child := range node.children {
// 		if child != nil {
// 			onlyChild = child
// 			break
// 		}
// 	}
// 	if onlyChild == nil {
// 		// 子がない場合、このノードを削除
// 		if node.parent != nil {
// 			index := getIndex(node.key, node.parent)
// 			if int(index) < len(node.parent.children) {
// 				node.parent.children[index] = nil
// 				node.parent.emptyChildren++
// 				// maxPrefixLenの更新
// 				t.updateMaxPrefixLenAfterDelete(node.parent)
// 			}
// 		} else {
// 			// ルートノード
// 			t.root = nil
// 		}
// 	} else {
// 		if node.parent != nil {
// 			index := getIndex(node.key, node.parent)
// 			if int(index) < len(node.parent.children) {
// 				node.parent.children[index] = onlyChild
// 				onlyChild.SetParent(node.parent)
// 				// maxPrefixLenの更新
// 				t.updateMaxPrefixLenAfterDelete(node.parent)
// 			}
// 		} else {
// 			// ルートノード
// 			if onlyChild.IsLeaf() {
// 				t.root = NewTnode(onlyChild.GetKey(), 0, 0)
// 				t.root.children = []Node{onlyChild}
// 				onlyChild.SetParent(t.root)
// 				t.root.maxPrefixLen = onlyChild.(*Leaf).prefixLen
// 			} else {
// 				t.root = onlyChild.(*Tnode)
// 				t.root.parent = nil
// 			}
// 		}
// 	}
// }

// // ノード削除後にmaxPrefixLenを更新するヘルパー関数
// func (t *Trie) updateMaxPrefixLenAfterDelete(node *Tnode) {
// 	oldMax := node.maxPrefixLen
// 	node.maxPrefixLen = 0
// 	for _, child := range node.children {
// 		if child != nil {
// 			if child.IsLeaf() {
// 				leaf := child.(*Leaf)
// 				if node.maxPrefixLen < leaf.prefixLen {
// 					node.maxPrefixLen = leaf.prefixLen
// 				}
// 			} else {
// 				tnode := child.(*Tnode)
// 				if node.maxPrefixLen < tnode.maxPrefixLen {
// 					node.maxPrefixLen = tnode.maxPrefixLen
// 				}
// 			}
// 		}
// 	}
// 	if node.parent != nil && node.parent.maxPrefixLen == oldMax {
// 		t.updateMaxPrefixLenAfterDelete(node.parent)
// 	}
// }

// // Delete関数
// func (t *Trie) Delete(key Key, prefixLen uint8) {
// 	t.deleteNode(t.root, key, prefixLen)
// }

// func (t *Trie) deleteNode(node *Tnode, key Key, prefixLen uint8) {
// 	if node == nil {
// 		return
// 	}

// 	index := getIndex(key, node)
// 	if int(index) >= len(node.children) {
// 		return
// 	}

// 	child := node.children[index]
// 	if child == nil {
// 		return
// 	}

// 	if child.IsLeaf() {
// 		leaf := child.(*Leaf)
// 		if leaf.key == key && leaf.prefixLen == prefixLen {
// 			node.children[index] = nil
// 			node.emptyChildren++
// 			// maxPrefixLenの更新
// 			t.updateMaxPrefixLenAfterDelete(node)
// 			t.resize(node)
// 		}
// 	} else {
// 		t.deleteNode(child.(*Tnode), key, prefixLen)
// 	}
// }

// // トライの構造を表示する関数（デバッグ用）
// func (t *Trie) PrintTrie() {
// 	t.printNode(t.root, 0)
// }

// func (t *Trie) printNode(node Node, level int) {
// 	if node == nil {
// 		return
// 	}
// 	indent := ""
// 	for i := 0; i < level; i++ {
// 		indent += "  "
// 	}
// 	if node.IsLeaf() {
// 		leaf := node.(*Leaf)
// 		fmt.Printf("%sLeaf: Key=%032b, PrefixLen=%d, Data=%v\n", indent, leaf.key, leaf.prefixLen, leaf.data)
// 	} else {
// 		tnode := node.(*Tnode)
// 		fmt.Printf("%sTnode: Key=%032b, Pos=%d, Bits=%d, MaxPrefixLen=%d\n", indent, tnode.key, tnode.pos, tnode.bits, tnode.maxPrefixLen)
// 		for i, child := range tnode.children {
// 			if child != nil {
// 				fmt.Printf("%s  Child %d:\n", indent, i)
// 				t.printNode(child, level+2)
// 			}
// 		}
// 	}
// }
