package memorytrace

import (
	"fmt"
	"os"
	"sync"
)

type DRAMAccess struct {
	Timestamp uint64
	Address   uintptr
	Type      string
}

func NewDRAMAccess(timestamp uint64, address uintptr) *DRAMAccess {
	return &DRAMAccess{
		Timestamp: timestamp,
		Address:   address,
		Type:      "R",
	}
}

// Tracer holds DRAM access traces for a single simulation.
type Tracer struct {
	mu           sync.Mutex
	CycleCount   uint64
	DRAMAccesses []*DRAMAccess
}

// NewTracer creates a new Tracer instance.
func NewTracer() *Tracer {
	return &Tracer{DRAMAccesses: make([]*DRAMAccess, 0)}
}

// AddDRAMAccess records a DRAM access to the tracer.
func (t *Tracer) AddDRAMAccess(access *DRAMAccess) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.DRAMAccesses = append(t.DRAMAccesses, access)
}

// IncrementCycleCounter increments the cycle counter in the tracer.
func (t *Tracer) IncrementCycleCounter() {
	t.mu.Lock()
	t.CycleCount++
	t.mu.Unlock()
}

// GetCycleCounter returns the current cycle counter.
func (t *Tracer) GetCycleCounter() uint64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.CycleCount
}

// WriteDRAMAccessesToFile writes recorded DRAM accesses to a file.
func (t *Tracer) WriteDRAMAccessesToFile(filename string) error {
	t.mu.Lock()
	accesses := make([]*DRAMAccess, len(t.DRAMAccesses))
	copy(accesses, t.DRAMAccesses)
	t.mu.Unlock()

	file, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("ファイル作成エラー: %w", err)
	}
	defer file.Close()

	for _, access := range accesses {
		_, err := fmt.Fprintf(file, "0x%08x R\n", access.Address)
		if err != nil {
			return fmt.Errorf("書き込みエラー: %w", err)
		}
	}
	return nil
}

// Reset clears all recorded information in the tracer.
func (t *Tracer) Reset() {
	t.mu.Lock()
	t.DRAMAccesses = nil
	t.CycleCount = 0
	t.mu.Unlock()
}

// A default tracer for backward compatibility.
var defaultTracer = NewTracer()

func DefaultTracer() *Tracer { return defaultTracer }

// Wrapper functions using the default tracer.
func AddDRAMAccess(access *DRAMAccess) { defaultTracer.AddDRAMAccess(access) }
func IncrementCycleCounter()           { defaultTracer.IncrementCycleCounter() }
func GetCycleCounter() uint64          { return defaultTracer.GetCycleCounter() }
func WriteDRAMAccessesToFile(filename string) error {
	return defaultTracer.WriteDRAMAccessesToFile(filename)
}
func Reset() { defaultTracer.Reset() }
