// shared/shared.go
package memorytrace

import (
	"fmt"
	"os"
	"sync"
)

// グローバルな共有変数
var (
	CycleCount uint64
	DRAMAccesses []*DRAMAccess
	mu            sync.Mutex // 排他制御のためのMutex
)

type DRAMAccess struct {
	Timestamp uint64
	Address   uintptr
	Type 	string
}

func NewDRAMAccess(timestamp uint64, address uintptr) *DRAMAccess {
	return &DRAMAccess{
		Timestamp: timestamp,
		Address:   address,
		Type: "R",
	}
}

func AddDRAMAccess(access *DRAMAccess) {
	mu.Lock()
	defer mu.Unlock()
	DRAMAccesses = append(DRAMAccesses, access)
}

// 共有変数を安全に操作するための関数
func IncrementCycleCounter() {
	mu.Lock()
	defer mu.Unlock()
	CycleCount++
}

func GetCycleCounter() uint64 {
	mu.Lock()
	defer mu.Unlock()
	return CycleCount
}



// DRAMAccessesをファイルに書き込む
func WriteDRAMAccessesToFile(filename string) error {
	mu.Lock()
	defer mu.Unlock()

	file, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("ファイル作成エラー: %w", err)
	}
	defer file.Close()

	// ファイルに書き込む
	for _, access := range DRAMAccesses {
		// _, err := fmt.Fprintf(file, "%d 0x%08x R\n", access.Timestamp, access.Address)
		_, err := fmt.Fprintf(file, "0x%08x R\n", access.Address)
		if err != nil {
			return fmt.Errorf("書き込みエラー: %w", err)
		}
	}
	return nil
}
