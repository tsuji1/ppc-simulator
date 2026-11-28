// cut_pcap_windows は標準入力の classic pcap を 1 回だけ読み、複数の時間窓
// [base+offset, base+offset+dur) に入る packet を窓ごとの pcap に書き出す。
// 最後の窓の終わり以降の packet が来たら読むのをやめるので、
// `pigz -dc big.pcap.gz | cut_pcap_windows ...` で gz の残りを展開しなくて済む。
//
// 使い方:
//
//	cut_pcap_windows -base 2025-03-20T13:00:00Z -offsets 0m,10m,20m -dur 10s -out DIR -prefix NAME
//
// 出力は DIR/NAME.t<offset の秒>s.pcap（例: NAME.t600s.pcap）。
// 窓ごとの packet 数・最初と最後の時刻を標準エラーと DIR/NAME.windows.tsv に書く。
// 窓は重なってもよい（重なった packet は両方に書く）。
package main

import (
	"bufio"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// window は 1 つの時間窓と、その出力先・集計。
type window struct {
	offset  time.Duration
	startNs int64
	endNs   int64
	path    string
	f       *os.File
	w       *bufio.Writer
	written int64
	firstNs int64
	lastNs  int64
}

// pcapFormat は global header から読んだ byte order と時刻の分解能。
type pcapFormat struct {
	bo         binary.ByteOrder
	fracPerSec int64
}

func parseHeader(hdr []byte) (pcapFormat, error) {
	switch {
	case binary.LittleEndian.Uint32(hdr) == 0xa1b2c3d4:
		return pcapFormat{binary.LittleEndian, 1e6}, nil
	case binary.LittleEndian.Uint32(hdr) == 0xa1b23c4d:
		return pcapFormat{binary.LittleEndian, 1e9}, nil
	case binary.BigEndian.Uint32(hdr) == 0xa1b2c3d4:
		return pcapFormat{binary.BigEndian, 1e6}, nil
	case binary.BigEndian.Uint32(hdr) == 0xa1b23c4d:
		return pcapFormat{binary.BigEndian, 1e9}, nil
	}
	return pcapFormat{}, errors.New("classic pcap ではない（pcapng は扱わない）")
}

// parseOffsets は "0m,10m,20m" のような offset の一覧を読み、昇順に並べる。
func parseOffsets(s string) ([]time.Duration, error) {
	var out []time.Duration
	for _, f := range strings.Split(s, ",") {
		f = strings.TrimSpace(f)
		if f == "" {
			continue
		}
		d, err := time.ParseDuration(f)
		if err != nil {
			return nil, fmt.Errorf("offset %q: %w", f, err)
		}
		if d < 0 {
			return nil, fmt.Errorf("offset %q が負", f)
		}
		out = append(out, d)
	}
	if len(out) == 0 {
		return nil, errors.New("offset が 1 つもない")
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	for i := 1; i < len(out); i++ {
		if out[i] == out[i-1] {
			return nil, fmt.Errorf("offset %s が重複", out[i])
		}
	}
	return out, nil
}

// cut は in の pcap を読み、windows の各窓に packet を書く。読んだ packet 数を返す。
// 書き込み先（windows[i].w）は呼び出し側が用意する。
func cut(in io.Reader, windows []*window, writeHeader func(hdr []byte) error) (int64, error) {
	hdr := make([]byte, 24)
	if _, err := io.ReadFull(in, hdr); err != nil {
		return 0, fmt.Errorf("global header を読めない: %w", err)
	}
	pf, err := parseHeader(hdr)
	if err != nil {
		return 0, err
	}
	if err := writeHeader(hdr); err != nil {
		return 0, err
	}
	var lastEnd int64
	for _, w := range windows {
		if w.endNs > lastEnd {
			lastEnd = w.endNs
		}
	}

	rec := make([]byte, 16)
	buf := make([]byte, 0, 1<<16)
	var read int64
	for {
		if _, err := io.ReadFull(in, rec); err != nil {
			if err == io.EOF {
				break
			}
			return read, fmt.Errorf("%d packet 目の record header を読めない: %w", read, err)
		}
		ts := int64(pf.bo.Uint32(rec[0:]))*1e9 + int64(pf.bo.Uint32(rec[4:]))*(1e9/pf.fracPerSec)
		incl := int(pf.bo.Uint32(rec[8:]))
		if cap(buf) < incl {
			buf = make([]byte, incl)
		}
		buf = buf[:incl]
		if _, err := io.ReadFull(in, buf); err != nil {
			return read, fmt.Errorf("%d packet 目を読めない: %w", read, err)
		}
		read++
		if ts >= lastEnd {
			break
		}
		for _, w := range windows {
			if ts < w.startNs || ts >= w.endNs {
				continue
			}
			if w.written == 0 {
				w.firstNs = ts
			}
			w.lastNs = ts
			if _, err := w.w.Write(rec); err != nil {
				return read, err
			}
			if _, err := w.w.Write(buf); err != nil {
				return read, err
			}
			w.written++
		}
	}
	return read, nil
}

func fmtNs(ns int64) string {
	if ns == 0 {
		return "-"
	}
	return time.Unix(0, ns).UTC().Format(time.RFC3339Nano)
}

func main() {
	baseStr := flag.String("base", "", "offset の基準時刻（UTC、RFC3339。例 2025-03-20T13:00:00Z）")
	offsetsStr := flag.String("offsets", "", "窓の開始の基準時刻からの offset（カンマ区切り、例 0m,10m,20m）")
	dur := flag.Duration("dur", 10*time.Second, "窓の長さ")
	outDir := flag.String("out", "", "出力 directory")
	prefix := flag.String("prefix", "", "出力ファイル名の先頭")
	flag.Parse()
	if *baseStr == "" || *offsetsStr == "" || *outDir == "" || *prefix == "" {
		fail("-base・-offsets・-out・-prefix は必須")
	}
	base, err := time.Parse(time.RFC3339Nano, *baseStr)
	if err != nil {
		fail("-base: %v", err)
	}
	offsets, err := parseOffsets(*offsetsStr)
	if err != nil {
		fail("-offsets: %v", err)
	}
	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		fail("%v", err)
	}

	var windows []*window
	for _, off := range offsets {
		s := base.Add(off).UnixNano()
		p := filepath.Join(*outDir, fmt.Sprintf("%s.t%ds.pcap", *prefix, int64(off/time.Second)))
		f, err := os.Create(p + ".part")
		if err != nil {
			fail("%v", err)
		}
		windows = append(windows, &window{offset: off, startNs: s, endNs: s + dur.Nanoseconds(), path: p, f: f, w: bufio.NewWriterSize(f, 16<<20)})
	}

	in := bufio.NewReaderSize(os.Stdin, 16<<20)
	read, err := cut(in, windows, func(hdr []byte) error {
		for _, w := range windows {
			if _, err := w.w.Write(hdr); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		fail("%v", err)
	}

	tsv, err := os.Create(filepath.Join(*outDir, *prefix+".windows.tsv"))
	if err != nil {
		fail("%v", err)
	}
	fmt.Fprintln(tsv, "file\toffset_s\twindow_start\twindow_end\tpackets\tfirst\tlast")
	for _, w := range windows {
		if err := w.w.Flush(); err != nil {
			fail("flush %s: %v", w.path, err)
		}
		if err := w.f.Close(); err != nil {
			fail("close %s: %v", w.path, err)
		}
		// 窓の終わりまで trace が続かなかった（途中で EOF）ときも書いた分は残すが、件数 0 は失敗にする
		if w.written == 0 {
			fail("窓 %s に packet が 1 つもない", fmtNs(w.startNs))
		}
		if err := os.Rename(w.path+".part", w.path); err != nil {
			fail("%v", err)
		}
		line := fmt.Sprintf("%s\t%d\t%s\t%s\t%d\t%s\t%s", filepath.Base(w.path), int64(w.offset/time.Second),
			fmtNs(w.startNs), fmtNs(w.endNs), w.written, fmtNs(w.firstNs), fmtNs(w.lastNs))
		fmt.Fprintln(tsv, line)
		fmt.Fprintln(os.Stderr, line)
	}
	if err := tsv.Close(); err != nil {
		fail("%v", err)
	}
	fmt.Fprintf(os.Stderr, "read=%d\n", read)
}

func fail(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "cut_pcap_windows: "+format+"\n", a...)
	os.Exit(1)
}
