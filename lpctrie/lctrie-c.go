package lpctrie

/*
#cgo CFLAGS: -I${SRCDIR}/../c/include
#cgo LDFLAGS: -L${SRCDIR}/../c -llctrie -Wl,-rpath=${SRCDIR}/../c

#include "lctrie.h"

// Declare the function if it's not in the header
void init_lctrie(void);
*/
import "C"

//reconfigreするとc側のinterfaceが自動生成される。

type LctrieC *C.struct_lctrie

func InitLctrie() LctrieC {
	// Initialize the C library for lctrie
	return C.lctrie_new()
}

func LctrieFree(trie *C.struct_lctrie) {
	// Free the C lctrie structure
	C.lctrie_free(trie)
}
func LctrieInsert(trie *C.struct_lctrie, prefix uint32, plen uint8, custom_id uint32) {
	// Insert a key-value pair into the lctrie
	C.lctrie_insert(trie, C.uint32_t(prefix), C.uint8_t(plen), C.uint32_t(custom_id))
}

func lctrieLookup(trie *C.struct_lctrie, addr uint32) (uint8, uint32, uint32, bool) {
	// Lookup a key in the lctrie
	res := C.lctrie_lookup(trie, C.uint32_t(addr))
	prefixlen := uint8(res.prefixlen)
	custom_id := uint32(res.custom_id)
	prefix := uint32(res.prefix)
	found := bool(res.found)

	return prefixlen, custom_id, prefix, found
}
