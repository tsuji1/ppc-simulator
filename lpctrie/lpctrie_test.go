package lpctrie_test

import (
	"fmt"
	"test-module/ipaddress"
    . "test-module/lpctrie"
	"testing"
)

func TestTrieOperations(t *testing.T) {
    trie := NewTrie()

    var l *KeyVector
    var tp *KeyVector

    key := Key(0x0A000001) // 10.0.0.1

    // まだ挿入前なのでFibFindNodeでは見つからないはず
    l = FibFindNode(trie, &tp, key)
    if l != nil {
        t.Errorf("Expected no node found, got one: %v", l)
    }

    a := &FibAlias{
        FaSlen: 24,
    }
    // 挿入
    inserted := FibInsert(trie,key,a)
    if inserted != 0 {
        t.Fatalf("Insert failed to create a leaf node")
    }

    // 再度検索
    l = FibFindNode(trie, &tp, key)
    if l == nil {
        t.Errorf("Expected to find inserted node, got nil")
    } else if l.Key != key {
        t.Errorf("Key mismatch: expected %v, got %v", key, l.Key)
    }
    depth := GetDepth(trie,key)

    if depth != 2{
        t.Errorf("Expected depth 1, got %d", depth)
    }
    DebugPrint(trie)
    // // 追加の挿入テスト
    // key2 := Key(0x0B000002) // 10.0.0.2
    // b := &FibAlias{
    //     FaSlen: 24,
    // }
    // l = FibFindNode(trie, &tp, key2)
    // if l != nil {
    //     t.Errorf("Expected no node found for key2, got %v", l)
    // }
    // FibInsertNode(trie,tp,b ,key2)
    // l2 := FibFindNode(trie, &tp, key2)
    // if l2 == nil || l2.Key != key2 {
    //     t.Errorf("Expected to find inserted node for key2=%08x, got %v",key2, l2)
    // }
    
    // key3 := Key(0x0C000003) //
    // c := &FibAlias{
    //     FaSlen: 24,
    // }
    
    // l = FibFindNode(trie, &tp, key3)
    // if l != nil {
    //     t.Errorf("Expected no node found for key3, got %v", l)
    // }
    // FibInsertNode(trie,tp,c ,key3)
    // l3 := FibFindNode(trie, &tp, key3)
    // if l3 == nil || l3.Key != key3 {
    //     t.Errorf("Expected to find inserted node for key3=%08x, got %v",key3, l3)
    // }
    
    
    // key4 := Key(0x0D000004) //
    
    // d := &FibAlias{
    //     FaSlen: 28,
    // }

    // l = FibFindNode(trie, &tp, key4)
    // if l != nil {
    //     t.Errorf("Expected no node found for key4, got %v", l)
    // }
    // FibInsertNode(trie,tp,d ,key4)
    // l4 := FibFindNode(trie, &tp, key4)
    // DebugPrint(trie)
    // if l4 == nil || l4.Key != key4 {
    //     t.Errorf("Expected to find inserted node for key4=%08x, got %v",key4, l4)
    // }


    // l3 = FibFindNode(trie, &tp, key3)
    // if l3 == nil || l3.Key != key3 {
    //     t.Errorf("Expected to find inserted node for key3=%08x, got %v",key3, l3)
    // }

    // l2 = FibFindNode(trie, &tp, key2)
    // if l2 == nil || l2.Key != key2 {
    //     t.Errorf("Expected to find inserted node for key2=%08x, got %v",key2, l2)
    // }
    
}

func TestFibRandomInsert(t *testing.T) {
    trie :=NewTrie()
    // insertedKeyList := make([]Key, 1000)
    var l *KeyVector
    var tp *KeyVector
    for i:=0; i<1000; i++ {
        key := Key(ipaddress.GetRandomIP().Uint32())
        randomSlen := ipaddress.GetRandomPrefix()
        randomuint32 := ipaddress.GetRandomIP().Uint32()
        alias := &FibAlias{
            FaSlen: randomSlen,
            TbID: randomuint32,
        }
        
        l = FibFindNode(trie, &tp, key)
        if l != nil {
            t.Errorf("Expected no node found, got one: %v", l)
        }
        fmt.Printf("Inserting key=%32b, slen=%d\n", key, randomSlen)
        fmt.Println("--------------------------------------------------------------------")
        // 挿入
        inserted := FibInsert(trie,key,alias)
        if inserted != 0 {
            t.Fatalf("Insert failed to create a leaf node")
        }

        // 再度検索
        l = FibFindNode(trie, &tp, key)
        if l == nil {
            t.Errorf("Expected to find inserted node, got nil")
        } else if l.Key != key {
            t.Errorf("Key mismatch: expected %v, got %v", key, l.Key)
        }else{ 
            fmt.Printf("Value type: %T\n", l.Leaf.Front().Value)

            resultTbID := l.Leaf.Front().Value.(*FibAlias).TbID
            if resultTbID != alias.TbID{
                t.Errorf("TbID mismatch: expected %v, got %v", alias.TbID, resultTbID)
            }

        }

        depth := GetDepth(trie,key)
        fmt.Println("Depth: ", depth)
    } 
}
// TestFibInsert tests the FibInsert function.
// func TestFibInsert(t *testing.T) {
// 	// Create a new root node.
// 	root := NewTnode(0, 5)

// 	// Create a trie with the root.
// 	trie := &Trie{root: root}
//     // Create aliases
//     alias1 := &FibAlias{faSlen: 24}
//     alias2 := &FibAlias{faSlen: 24}
//     alias3 := &FibAlias{faSlen: 24}

//     // Insert keys
//     err := FibInsert(trie, 0x0A000001, alias1) // 10.0.0.1
//     if err != nil {
//         t.Errorf("Error inserting key 0x0A000001: %v", err)
//     }

//     err = FibInsert(trie, 0x0A000002, alias2) // 10.0.0.2
//     if err != nil {
//         t.Errorf("Error inserting key 0x0A000002: %v", err)
//     }

//     err = FibInsert(trie, 0x0A000003, alias3) // 10.0.0.3
//     if err != nil {
//         t.Errorf("Error inserting key 0x0A000003: %v", err)
//     }
// 	PrintDebug(trie.root, 0)

//     // Verify that the keys are inserted
//     leaf1 := fibFindLeaf(trie, 0x0A000001)
//     if leaf1 == nil || leaf1.alias != alias1 {
//         t.Errorf("Key 0x0A000001 not found or alias mismatch")
//     }

//     leaf2 := fibFindLeaf(trie, 0x0A000002)
//     if leaf2 == nil || leaf2.alias != alias2 {
//         t.Errorf("Key 0x0A000002 not found or alias mismatch")
//     }

//     leaf3 := fibFindLeaf(trie, 0x0A000003)
//     if leaf3 == nil || leaf3.alias != alias3 {
//         t.Errorf("Key 0x0A000003 not found or alias mismatch")
//     }
// }

// // TestFibInsertDuplicate tests inserting duplicate keys.
// func TestFibInsertDuplicate(t *testing.T) {
//     trie := &Trie{}
//     alias1 := &FibAlias{faSlen: 24}
//     alias2 := &FibAlias{faSlen: 24}

//     // Insert a key
//     err := FibInsert(trie, 0x0A000001, alias1)
//     if err != nil {
//         t.Errorf("Error inserting key 0x0A000001: %v", err)
//     }

//     // Insert the same key with a different alias
//     err = FibInsert(trie, 0x0A000001, alias2)
//     if err != nil {
//         t.Errorf("Error inserting duplicate key 0x0A000001: %v", err)
//     }

//     // Verify that the alias is updated
//     leaf := fibFindLeaf(trie, 0x0A000001)
//     if leaf == nil || leaf.alias != alias2 {
//         t.Errorf("Alias for key 0x0A000001 not updated")
//     }
// }

// // TestFibFindLeafNode tests the fibFindLeafNode function.
// func TestFibFindLeafNode(t *testing.T) {
//     trie := &Trie{}
//     alias := &FibAlias{faSlen: 24}

//     // Insert a key
//     FibInsert(trie, 0x0A000001, alias)

//     // Search for the key
//     leaf := fibFindLeaf(trie, 0x0A000001)
//     if leaf == nil {
//         t.Errorf("Key 0x0A000001 not found")
//     } else if leaf.alias != alias {
//         t.Errorf("Alias mismatch for key 0x0A000001")
//     }

//     // Search for a non-existent key
//     leaf = fibFindLeaf(trie, 0x0A000002)
//     if leaf != nil {
//         t.Errorf("Non-existent key 0x0A000002 found")
//     }
// }

// // TestTrieStructure tests the internal structure of the trie.
// func TestTrieStructure(t *testing.T) {
//     trie := &Trie{}
//     aliases := []*FibAlias{
//         {faSlen: 24},
//         {faSlen: 24},
//         {faSlen: 24},
//     }
//     keys := []Key{
//         0x0A000001, // 10.0.0.1
//         0x0A0000FF, // 10.0.0.255
//         0x0A000F00, // 10.0.15.0
//     }

//     // Insert keys
//     for i, key := range keys {
//         err := FibInsert(trie, key, aliases[i])
//         if err != nil {
//             t.Errorf("Error inserting key %v: %v", key, err)
//         }
//     }

//     // Verify the trie structure (this is a placeholder for actual structure checks)
//     // In a real test, you would check the properties of the trie nodes to ensure correctness
//     if trie.root == nil {
//         t.Errorf("Trie root is nil after insertions")
//     } else if len(trie.root.children) == 0 {
//         t.Errorf("Trie root has no children after insertions")
//     }
// }

// // TestFibInsertLargeDataset tests inserting a large number of keys.
// func TestFibInsertLargeDataset(t *testing.T) {
//     trie := &Trie{}
//     numKeys := 1000

//     // Insert a large number of keys
//     for i := 0; i < numKeys; i++ {
//         key := Key(0x0A000000 + i) // 10.0.0.0 + i
//         alias := &FibAlias{faSlen: 24}
//         err := FibInsertNode(trie, trie.root, alias,key)
//         if err != nil {
//             t.Errorf("Error inserting key %v: %v", key, err)
//         }
//     }

//     // Verify that all keys are inserted
//     for i := 0; i < numKeys; i++ {
//         key := Key(0x0A000000 + i)
//         leaf := fibFindLeaf(trie, key)
//         if leaf == nil {
//             t.Errorf("Key %v not found in trie", key)
//         }
//     }
// }
