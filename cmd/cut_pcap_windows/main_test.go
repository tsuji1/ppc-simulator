package main

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"testing"
	"time"
)

// makePcap は ns 分解能・little endian の pcap を作る。各 packet の中身は 1 byte（index）。
func makePcap(tsNs []int64) []byte {
	var b bytes.Buffer
	hdr := make([]byte, 24)
	binary.LittleEndian.PutUint32(hdr, 0xa1b23c4d)
	b.Write(hdr)
	for i, ts := range tsNs {
		rec := make([]byte, 16)
		binary.LittleEndian.PutUint32(rec[0:], uint32(ts/1e9))
		binary.LittleEndian.PutUint32(rec[4:], uint32(ts%1e9))
		binary.LittleEndian.PutUint32(rec[8:], 1)
		binary.LittleEndian.PutUint32(rec[12:], 1)
		b.Write(rec)
		b.WriteByte(byte(i))
	}
	return b.Bytes()
}

// payloads は書き出された pcap から packet の中身（index）を取り出す。
func payloads(t *testing.T, data []byte) []byte {
	t.Helper()
	if len(data) < 24 {
		t.Fatalf("header がない")
	}
	var out []byte
	for p := 24; p < len(data); p += 17 {
		out = append(out, data[p+16])
	}
	return out
}

func TestCutWindows(t *testing.T) {
	base := int64(1_000_000_000) * 1000
	// 0s, 0.5s, 1s, 5s, 9.9s, 10s, 10.5s, 25s（ここで止まる）, 26s（読まれない）
	ts := []int64{base, base + 5e8, base + 1e9, base + 5e9, base + 99e8, base + 10e9, base + 105e8, base + 25e9, base + 26e9}
	bufs := []*bytes.Buffer{{}, {}}
	windows := []*window{
		{startNs: base, endNs: base + 1e9},         // [0s,1s) → 0, 1
		{startNs: base + 99e8, endNs: base + 11e9}, // [9.9s,11s) → 4, 5, 6
	}
	for i := range windows {
		windows[i].w = bufio.NewWriter(bufs[i])
	}
	var doneOrder []int64
	res, err := cut(bytes.NewReader(makePcap(ts)), windows, func(hdr []byte) error {
		for _, w := range windows {
			w.w.Write(hdr)
		}
		return nil
	}, func(w *window) error {
		doneOrder = append(doneOrder, w.startNs)
		return w.w.Flush()
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.read != 8 || res.truncated {
		t.Errorf("read=%d truncated=%v、最後の窓の終わりを越えた最初の packet（8 個目）で止まるはず", res.read, res.truncated)
	}
	if len(doneOrder) != 2 || doneOrder[0] != base || doneOrder[1] != base+99e8 {
		t.Errorf("onDone の順: %v", doneOrder)
	}
	want := [][]byte{{0, 1}, {4, 5, 6}}
	for i, w := range windows {
		if !w.done {
			t.Errorf("窓 %d が done でない", i)
		}
		got := payloads(t, bufs[i].Bytes())
		if !bytes.Equal(got, want[i]) {
			t.Errorf("窓 %d: got %v want %v", i, got, want[i])
		}
		if w.written != int64(len(want[i])) {
			t.Errorf("窓 %d: written=%d", i, w.written)
		}
	}
	if windows[1].firstNs != base+99e8 || windows[1].lastNs != base+105e8 {
		t.Errorf("窓 1 の first/last: %d %d", windows[1].firstNs, windows[1].lastNs)
	}
}

// gz が途中で切れていたとき（packet の途中で入力が尽きる）、終わった窓だけ done になり、エラーにはしない。
func TestCutTruncatedInput(t *testing.T) {
	base := int64(1_000_000_000) * 1000
	// 0s, 1.5s, 2.5s, 3.5s の 4 packet。最後の packet の中身を切り落とす
	data := makePcap([]int64{base, base + 15e8, base + 25e8, base + 35e8})
	data = data[:len(data)-1]
	bufs := []*bytes.Buffer{{}, {}}
	windows := []*window{
		{startNs: base, endNs: base + 1e9},       // 1.5s の packet で終わる → done
		{startNs: base + 2e9, endNs: base + 5e9}, // 終わる前に入力が切れる → done にならない
	}
	for i := range windows {
		windows[i].w = bufio.NewWriter(bufs[i])
	}
	var done int
	res, err := cut(bytes.NewReader(data), windows, func(hdr []byte) error { return nil }, func(w *window) error {
		done++
		return nil
	})
	if err != nil {
		t.Fatalf("切れた入力でエラーにしない: %v", err)
	}
	if !res.truncated || res.read != 3 || res.lastTsNs != base+25e8 {
		t.Errorf("res=%+v", res)
	}
	if !windows[0].done || windows[1].done || done != 1 {
		t.Errorf("done: %v %v (onDone %d 回)", windows[0].done, windows[1].done, done)
	}
	if windows[1].written != 1 {
		t.Errorf("窓 1 の written=%d", windows[1].written)
	}
}

// 窓の終わりより前で入力が普通に終わった（EOF）ときは truncated にしない。
func TestCutCleanEOF(t *testing.T) {
	base := int64(1_000_000_000) * 1000
	windows := []*window{{startNs: base, endNs: base + 10e9, w: bufio.NewWriter(&bytes.Buffer{})}}
	res, err := cut(bytes.NewReader(makePcap([]int64{base, base + 1e9})), windows,
		func([]byte) error { return nil }, func(*window) error { return nil })
	if err != nil || res.truncated || res.read != 2 || windows[0].done {
		t.Errorf("res=%+v err=%v done=%v", res, err, windows[0].done)
	}
}

func TestParseOffsets(t *testing.T) {
	got, err := parseOffsets("20m, 0m,10m")
	if err != nil {
		t.Fatal(err)
	}
	want := []time.Duration{0, 10 * time.Minute, 20 * time.Minute}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v want %v", got, want)
		}
	}
	if _, err := parseOffsets("0m,0s"); err == nil {
		t.Error("重複を拒否するはず")
	}
	if _, err := parseOffsets(""); err == nil {
		t.Error("空を拒否するはず")
	}
}

func TestParseHeaderRejectsPcapng(t *testing.T) {
	hdr := make([]byte, 24)
	binary.LittleEndian.PutUint32(hdr, 0x0a0d0d0a)
	if _, err := parseHeader(hdr); err == nil {
		t.Error("pcapng を拒否するはず")
	}
}
