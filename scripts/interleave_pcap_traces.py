#!/usr/bin/env python3
"""Create one PCAP by interleaving packet chunks from several classic PCAPs.

Packet order within each source is preserved.  Source chunks are emitted in a
seeded, shuffled round-robin, so each active trace contributes one chunk per
round without placing the three complete traces back-to-back.
"""

from __future__ import annotations

import argparse
import os
import random
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


MAGIC_FORMATS = {
    b"\xd4\xc3\xb2\xa1": ("<", "usec"),
    b"\xa1\xb2\xc3\xd4": (">", "usec"),
    b"\x4d\x3c\xb2\xa1": ("<", "nsec"),
    b"\xa1\xb2\x3c\x4d": (">", "nsec"),
}
GLOBAL_HEADER_SIZE = 24
RECORD_HEADER_SIZE = 16


@dataclass
class PcapReader:
    path: Path
    stream: BinaryIO
    endian: str
    precision: str
    snaplen: int
    linktype: int
    packet_count: int = 0

    @classmethod
    def open(cls, path: Path) -> "PcapReader":
        stream = path.open("rb")
        header = stream.read(GLOBAL_HEADER_SIZE)
        if len(header) != GLOBAL_HEADER_SIZE:
            stream.close()
            raise ValueError(f"{path}: truncated PCAP global header")
        fmt = MAGIC_FORMATS.get(header[:4])
        if fmt is None:
            stream.close()
            raise ValueError(f"{path}: unsupported PCAP magic (classic PCAP required)")
        endian, precision = fmt
        major, minor, _thiszone, _sigfigs, snaplen, linktype = struct.unpack(
            endian + "HHIIII", header[4:GLOBAL_HEADER_SIZE]
        )
        if (major, minor) != (2, 4):
            stream.close()
            raise ValueError(f"{path}: unsupported PCAP version {major}.{minor}")
        return cls(path, stream, endian, precision, snaplen, linktype)

    def read_chunk(self, packet_limit: int) -> list[bytes]:
        records: list[bytes] = []
        for _ in range(packet_limit):
            header = self.stream.read(RECORD_HEADER_SIZE)
            if not header:
                break
            if len(header) != RECORD_HEADER_SIZE:
                raise ValueError(f"{self.path}: truncated packet header")
            _seconds, fraction, captured_len, _original_len = struct.unpack(
                self.endian + "IIII", header
            )
            fraction_limit = 1_000_000 if self.precision == "usec" else 1_000_000_000
            if fraction >= fraction_limit:
                raise ValueError(f"{self.path}: invalid packet timestamp fraction {fraction}")
            if captured_len > self.snaplen:
                raise ValueError(
                    f"{self.path}: captured packet length {captured_len} exceeds snaplen {self.snaplen}"
                )
            packet = self.stream.read(captured_len)
            if len(packet) != captured_len:
                raise ValueError(f"{self.path}: truncated packet data")
            records.append(header + packet)
            self.packet_count += 1
        return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interleave classic PCAPs by bounded packet chunks while preserving "
            "the packet order within each source."
        )
    )
    parser.add_argument("--trace", action="append", required=True, type=Path,
                        help="input PCAP; repeat once per source trace")
    parser.add_argument("--output", required=True, type=Path, help="combined output PCAP")
    parser.add_argument("--chunk-packets", type=int, default=4096,
                        help="packets from each source per round (default: 4096)")
    parser.add_argument("--max-packets", type=int, default=0,
                        help="maximum total output packets; zero means no limit")
    parser.add_argument("--seed", type=int, default=20260929,
                        help="seed used to shuffle source order each round")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if len(args.trace) < 2:
        raise SystemExit("at least two --trace inputs are required")
    if args.chunk_packets <= 0:
        raise SystemExit("--chunk-packets must be greater than zero")
    if args.max_packets < 0:
        raise SystemExit("--max-packets cannot be negative")

    input_paths = [path.resolve() for path in args.trace]
    output_path = args.output.resolve()
    if output_path in input_paths:
        raise SystemExit("--output must not overwrite an input trace")
    for path in input_paths:
        if not path.is_file():
            raise SystemExit(f"input trace not found: {path}")

    readers: list[PcapReader] = []
    temp_path: Path | None = None
    try:
        readers = [PcapReader.open(path) for path in input_paths]
        reference = readers[0]
        for reader in readers[1:]:
            if reader.linktype != reference.linktype:
                raise ValueError(
                    f"incompatible link types: {reference.path}={reference.linktype}, "
                    f"{reader.path}={reader.linktype}"
                )
            if reader.endian != reference.endian or reader.precision != reference.precision:
                raise ValueError(
                    "input PCAPs use different byte order or timestamp precision; "
                    "convert them to a common format first"
                )
            if reader.snaplen != reference.snaplen:
                raise ValueError(
                    f"incompatible snap lengths: {reference.path}={reference.snaplen}, "
                    f"{reader.path}={reader.snaplen}"
                )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=output_path.name + ".", suffix=".tmp",
            dir=output_path.parent, delete=False
        ) as out:
            temp_path = Path(out.name)
            with reference.path.open("rb") as source:
                out.write(source.read(GLOBAL_HEADER_SIZE))
            rng = random.Random(args.seed)
            active = list(range(len(readers)))
            total_packets = 0
            while active and (args.max_packets == 0 or total_packets < args.max_packets):
                rng.shuffle(active)
                finished: list[int] = []
                for index in active:
                    if args.max_packets and total_packets >= args.max_packets:
                        break
                    remaining = (args.max_packets - total_packets) if args.max_packets else args.chunk_packets
                    records = readers[index].read_chunk(min(args.chunk_packets, remaining))
                    if records:
                        out.writelines(records)
                        total_packets += len(records)
                    else:
                        finished.append(index)
                if finished:
                    finished_set = set(finished)
                    active = [index for index in active if index not in finished_set]
            out.flush()
            os.fsync(out.fileno())

        os.chmod(temp_path, 0o644)
        os.replace(temp_path, output_path)
        temp_path = None
        print(f"output: {output_path}")
        print(f"packet order: shuffled round-robin, {args.chunk_packets} packets/source/round")
        if args.max_packets:
            print(f"packet limit: {args.max_packets}")
        print(f"seed: {args.seed}")
        print(f"total packets: {total_packets}")
        for reader in readers:
            print(f"{reader.path}: {reader.packet_count} packets")
    finally:
        for reader in readers:
            reader.stream.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
