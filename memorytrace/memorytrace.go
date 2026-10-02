package memorytrace

import (
	"encoding/csv"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"sync"
)

type DRAMAccess struct {
	Timestamp   uint64
	Sequence    uint64
	Address     uint64
	Type        string
	Source      string
	CacheHit    bool
	MissType    string
	SrcIP       uint32
	DstIP       uint32
	Proto       string
	SrcPort     uint16
	DstPort     uint16
	IsLeafIndex int8
}

func NewDRAMAccess(timestamp uint64, address uintptr) *DRAMAccess {
	return &DRAMAccess{
		Timestamp: timestamp,
		Address:   uint64(address),
		Type:      "R",
	}
}

type TraceStats struct {
	Accesses   uint64
	Reads      uint64
	Writes     uint64
	Hits       uint64
	Misses     uint64
	FirstCycle uint64
	LastCycle  uint64
}

// Tracer holds DRAM access traces for a single simulation.
type Tracer struct {
	mu             sync.Mutex
	CycleCount     uint64
	DRAMAccesses   []*DRAMAccess
	RecordInMemory bool
	enabled        bool
	nextSequence   uint64
	stats          TraceStats
	csvFile        *os.File
	csvWriter      *csv.Writer
}

// NewTracer creates a new Tracer instance.
func NewTracer() *Tracer {
	return &Tracer{
		DRAMAccesses:   make([]*DRAMAccess, 0),
		RecordInMemory: true,
	}
}

// OpenCSV enables streaming request-level DRAM accesses to filename.
func (t *Tracer) OpenCSV(filename string) error {
	if filename == "" {
		return fmt.Errorf("memory trace filename is empty")
	}
	if err := os.MkdirAll(filepath.Dir(filename), 0755); err != nil {
		return fmt.Errorf("create memory trace directory: %w", err)
	}

	file, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("create memory trace csv: %w", err)
	}

	writer := csv.NewWriter(file)
	if err := writer.Write([]string{
		"cycle",
		"sequence",
		"op",
		"address",
		"cache_hit",
		"miss_type",
		"source",
		"src_ip",
		"dst_ip",
		"proto",
		"src_port",
		"dst_port",
		"is_leaf_index",
	}); err != nil {
		file.Close()
		return fmt.Errorf("write memory trace header: %w", err)
	}

	t.mu.Lock()
	if t.csvWriter != nil {
		t.csvWriter.Flush()
	}
	if t.csvFile != nil {
		t.csvFile.Close()
	}
	t.csvFile = file
	t.csvWriter = writer
	t.enabled = true
	t.RecordInMemory = false
	t.mu.Unlock()

	return nil
}

// AddDRAMAccess records a DRAM access to the tracer.
func (t *Tracer) AddDRAMAccess(access *DRAMAccess) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.addDRAMAccessLocked(access)
}

func (t *Tracer) addDRAMAccessLocked(access *DRAMAccess) {
	if access == nil {
		return
	}
	if access.Type == "" {
		access.Type = "R"
	}
	if access.Sequence == 0 {
		t.nextSequence++
		access.Sequence = t.nextSequence
	} else if access.Sequence > t.nextSequence {
		t.nextSequence = access.Sequence
	}

	t.updateStatsLocked(access)

	if t.RecordInMemory {
		t.DRAMAccesses = append(t.DRAMAccesses, access)
	}
	if t.csvWriter != nil {
		_ = t.csvWriter.Write([]string{
			strconv.FormatUint(access.Timestamp, 10),
			strconv.FormatUint(access.Sequence, 10),
			access.Type,
			fmt.Sprintf("0x%016x", access.Address),
			strconv.FormatBool(access.CacheHit),
			access.MissType,
			access.Source,
			strconv.FormatUint(uint64(access.SrcIP), 10),
			strconv.FormatUint(uint64(access.DstIP), 10),
			access.Proto,
			strconv.FormatUint(uint64(access.SrcPort), 10),
			strconv.FormatUint(uint64(access.DstPort), 10),
			strconv.FormatInt(int64(access.IsLeafIndex), 10),
		})
	}
}

func (t *Tracer) updateStatsLocked(access *DRAMAccess) {
	t.stats.Accesses++
	switch access.Type {
	case "W", "WR", "write":
		t.stats.Writes++
	default:
		t.stats.Reads++
	}
	if access.CacheHit {
		t.stats.Hits++
	} else {
		t.stats.Misses++
	}
	if t.stats.FirstCycle == 0 || access.Timestamp < t.stats.FirstCycle {
		t.stats.FirstCycle = access.Timestamp
	}
	if access.Timestamp > t.stats.LastCycle {
		t.stats.LastCycle = access.Timestamp
	}
}

// IncrementCycleCounter increments the cycle counter in the tracer.
func (t *Tracer) IncrementCycleCounter() uint64 {
	t.mu.Lock()
	t.CycleCount++
	cycle := t.CycleCount
	t.mu.Unlock()
	return cycle
}

// GetCycleCounter returns the current cycle counter.
func (t *Tracer) GetCycleCounter() uint64 {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.CycleCount
}

// Enabled reports whether streaming or in-memory recording is explicitly enabled.
func (t *Tracer) Enabled() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.enabled
}

// EnableInMemory enables request recording without a CSV output file.
func (t *Tracer) EnableInMemory() {
	t.mu.Lock()
	t.enabled = true
	t.RecordInMemory = true
	t.mu.Unlock()
}

// Stats returns a snapshot of request trace counters.
func (t *Tracer) Stats() TraceStats {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.stats
}

// Close flushes and closes the CSV stream if one is open.
func (t *Tracer) Close() error {
	t.mu.Lock()
	writer := t.csvWriter
	file := t.csvFile
	t.csvWriter = nil
	t.csvFile = nil
	t.enabled = false
	t.mu.Unlock()

	if writer != nil {
		writer.Flush()
		if err := writer.Error(); err != nil {
			if file != nil {
				file.Close()
			}
			return fmt.Errorf("flush memory trace csv: %w", err)
		}
	}
	if file != nil {
		if err := file.Close(); err != nil {
			return fmt.Errorf("close memory trace csv: %w", err)
		}
	}
	return nil
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
		accessType := access.Type
		if accessType == "" {
			accessType = "R"
		}
		_, err := fmt.Fprintf(file, "0x%08x %s\n", access.Address, accessType)
		if err != nil {
			return fmt.Errorf("書き込みエラー: %w", err)
		}
	}
	return nil
}

// WriteDRAMAccessesCSV writes recorded in-memory accesses as request-level CSV.
func (t *Tracer) WriteDRAMAccessesCSV(filename string) error {
	t.mu.Lock()
	accesses := make([]*DRAMAccess, len(t.DRAMAccesses))
	copy(accesses, t.DRAMAccesses)
	t.mu.Unlock()

	if err := os.MkdirAll(filepath.Dir(filename), 0755); err != nil {
		return fmt.Errorf("create memory trace directory: %w", err)
	}
	file, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("ファイル作成エラー: %w", err)
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	if err := writer.Write([]string{
		"cycle",
		"sequence",
		"op",
		"address",
		"cache_hit",
		"miss_type",
		"source",
		"src_ip",
		"dst_ip",
		"proto",
		"src_port",
		"dst_port",
		"is_leaf_index",
	}); err != nil {
		return fmt.Errorf("write memory trace header: %w", err)
	}
	for _, access := range accesses {
		if access.Type == "" {
			access.Type = "R"
		}
		if err := writer.Write([]string{
			strconv.FormatUint(access.Timestamp, 10),
			strconv.FormatUint(access.Sequence, 10),
			access.Type,
			fmt.Sprintf("0x%016x", access.Address),
			strconv.FormatBool(access.CacheHit),
			access.MissType,
			access.Source,
			strconv.FormatUint(uint64(access.SrcIP), 10),
			strconv.FormatUint(uint64(access.DstIP), 10),
			access.Proto,
			strconv.FormatUint(uint64(access.SrcPort), 10),
			strconv.FormatUint(uint64(access.DstPort), 10),
			strconv.FormatInt(int64(access.IsLeafIndex), 10),
		}); err != nil {
			return fmt.Errorf("write memory trace row: %w", err)
		}
	}
	if err := writer.Error(); err != nil {
		return fmt.Errorf("flush memory trace csv: %w", err)
	}
	return nil
}

// Reset clears all recorded information in the tracer.
func (t *Tracer) Reset() {
	_ = t.Close()
	t.mu.Lock()
	t.DRAMAccesses = nil
	t.CycleCount = 0
	t.nextSequence = 0
	t.stats = TraceStats{}
	t.mu.Unlock()
}

// A default tracer for backward compatibility.
var defaultTracer = NewTracer()

func DefaultTracer() *Tracer { return defaultTracer }

// Wrapper functions using the default tracer.
func AddDRAMAccess(access *DRAMAccess) { defaultTracer.AddDRAMAccess(access) }
func IncrementCycleCounter() uint64    { return defaultTracer.IncrementCycleCounter() }
func GetCycleCounter() uint64          { return defaultTracer.GetCycleCounter() }
func WriteDRAMAccessesToFile(filename string) error {
	return defaultTracer.WriteDRAMAccessesToFile(filename)
}
func WriteDRAMAccessesCSV(filename string) error {
	return defaultTracer.WriteDRAMAccessesCSV(filename)
}
func Reset() { defaultTracer.Reset() }
