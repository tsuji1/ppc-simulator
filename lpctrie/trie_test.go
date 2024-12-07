package lpctrie_test

// import (
// 	"fmt"
// 	"test-module/lpctrie"
// 	"testing"

// 	"github.com/stretchr/testify/assert"
// )

// func TestTrieInsertAndSearch(t *testing.T) {
// 	trie := lpctrie.NewTrie()

// 	// サンプルデータ
// 	key1 := lpctrie.Key(0b11001010001010101111000011110000)
// 	prefixLen1 := uint8(24)
// 	data1 := "Node1"

// 	key2 := lpctrie.Key(0b10001010001010101111000000000000)
// 	prefixLen2 := uint8(16)
// 	data2 := "Node2"

// 	// Insert
// 	trie.Insert(key1, prefixLen1, data1)
// 	trie.PrintTrie()
// 	fmt.Println("----------------------")
// 	trie.Insert(key2, prefixLen2, data2)
// 	trie.PrintTrie()
// 	fmt.Println("----------------------")

// 	// Search
// 	result1, found1 := trie.Search(key1)
// 	assert.True(t, found1, "Key1 should be found")
// 	assert.Equal(t, data1, result1, "Key1 data should match")

// 	result2, found2 := trie.Search(key2)
// 	assert.True(t, found2, "Key2 should be found")
// 	assert.Equal(t, data2, result2, "Key2 data should match")
// }

// func TestTrieDelete(t *testing.T) {
// 	trie := lpctrie.NewTrie()

// 	// サンプルデータ
// 	key := lpctrie.Key(0b11001010001010101111000011110000)
// 	prefixLen := uint8(24)
// 	data := "Node1"

// 	// Insert
// 	trie.Insert(key, prefixLen, data)

// 	// Search before delete
// 	result, found := trie.Search(key)
// 	assert.True(t, found, "Key should be found before delete")
// 	assert.Equal(t, data, result, "Data should match before delete")

// 	// Delete
// 	trie.Delete(key, prefixLen)

// 	// Search after delete
// 	result, found = trie.Search(key)
// 	assert.False(t, found, "Key should not be found after delete")
// 	assert.Nil(t, result, "Result should be nil after delete")
// }

// func TestTrieCollision(t *testing.T) {
// 	trie := lpctrie.NewTrie()

// 	// サンプルデータ（衝突ケース）
// 	key1 := lpctrie.Key(0b11001010001010101111000011110000)
// 	prefixLen1 := uint8(24)
// 	data1 := "Node1"

// 	key2 := lpctrie.Key(0b11001010001010101111000011110001)
// 	prefixLen2 := uint8(24)
// 	data2 := "Node2"

// 	// Insert both keys
// 	trie.Insert(key1, prefixLen1, data1)
// 	trie.Insert(key2, prefixLen2, data2)

// 	// Verify both keys
// 	result1, found1 := trie.Search(key1)
// 	assert.True(t, found1, "Key1 should be found")
// 	assert.Equal(t, data1, result1, "Key1 data should match")

// 	result2, found2 := trie.Search(key2)
// 	assert.True(t, found2, "Key2 should be found")
// 	assert.Equal(t, data2, result2, "Key2 data should match")
// }

// func TestTriePrint(t *testing.T) {
// 	trie := lpctrie.NewTrie()

// 	// サンプルデータ
// 	key := lpctrie.Key(0b11001010001010101111000011110000)
// 	prefixLen := uint8(24)
// 	data := "Node1"

// 	// Insert
// 	trie.Insert(key, prefixLen, data)

// 	// Print
// 	// trie.PrintTrie() // 手動で確認が必要な部分
// }

// func TestTrieResizeOperations(t *testing.T) {
// 	trie := lpctrie.NewTrie()

// 	// ノードを追加して動的リサイズを確認
// 	for i := uint32(0); i < 16; i++ {
// 		key := lpctrie.Key(i << 28) // 上位ビットを変更
// 		trie.Insert(key, 4, i)
// 	}

// 	// リサイズの動作を目視確認
// 	// trie.PrintTrie()
// }
