#!/usr/bin/env python3
import argparse
import hashlib
import struct
from pathlib import Path

STOCK_SHA256 = "5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa"
STOCK_SIZE = 0x2190
FLASH_BASE = 0x2000
STAGING_START = 0x9000


def changed_ranges(original, candidate):
    ranges = []
    start = None
    for index in range(max(len(original), len(candidate))):
        old = original[index] if index < len(original) else None
        new = candidate[index] if index < len(candidate) else None
        if old != new and start is None:
            start = index
        elif old == new and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, max(len(original), len(candidate))))
    return ranges


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--require-stock", action="store_true")
    parser.add_argument("--compare-stock", action="store_true")
    args = parser.parse_args()

    data = args.image.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    print(f"path={args.image}")
    print(f"size={len(data)} (0x{len(data):x})")
    print(f"sha256={digest}")

    assert len(data) >= 0x110, "image is too short for vectors and metadata"
    assert len(data) <= STAGING_START - FLASH_BASE, "image overlaps stock staging area"
    vectors = struct.unpack_from("<8I", data, 0)
    checksum = sum(vectors) & 0xFFFFFFFF
    print(f"initial_sp=0x{vectors[0]:08x}")
    print(f"reset=0x{vectors[1]:08x}")
    print(f"lpc_vector_sum=0x{checksum:08x}")
    assert checksum == 0, "LPC vector checksum is invalid"
    assert vectors[1] & 1, "reset vector is not Thumb"
    reset_offset = (vectors[1] & ~1) - FLASH_BASE
    assert 0 <= reset_offset < len(data), "reset vector is outside the image"

    vendor, product, version = struct.unpack_from("<HHH", data, 0x102)
    print(f"vendor=0x{vendor:04x} product=0x{product:04x} version=0x{version:04x}")
    assert (vendor, product) == (0x1B1C, 0x1B3B), "wrong device identity"

    if len(data) >= 0x5F30 and data[0x5F00:0x5F08] == b"MM8BUILD":
        embedded = data[0x5F08:0x5F28]
        verification = bytearray(data)
        verification[0x5F08:0x5F28] = bytes(32)
        computed = hashlib.sha256(verification).digest()
        print(f"embedded_build_hash={embedded.hex()}")
        print(f"computed_build_hash={computed.hex()}")
        assert embedded == computed, "embedded build hash is invalid"

    if args.require_stock:
        assert len(data) == STOCK_SIZE, "stock size changed"
        assert digest == STOCK_SHA256, "stock digest changed"
        print("stock_identity=match")

    if args.compare_stock:
        stock_path = Path.cwd() / "SageApp_v1.02.50.bin"
        stock = stock_path.read_bytes()
        assert hashlib.sha256(stock).hexdigest() == STOCK_SHA256, "original stock file changed"
        ranges = changed_ranges(stock, data)
        print(f"changed_ranges={len(ranges)}")
        for start, end in ranges:
            print(f"  file 0x{start:x}..0x{end - 1:x}; flash 0x{start + FLASH_BASE:x}..0x{end - 1 + FLASH_BASE:x}")

    print("structural_checks=pass (not a hardware-safety or signature verdict)")


if __name__ == "__main__":
    main()
