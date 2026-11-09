#!/usr/bin/env python3
import hashlib
import struct
import subprocess
from pathlib import Path

from firmware_version import load_firmware_version

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "src"
STOCK = Path.cwd() / "SageApp_v1.02.50.bin"
BUILD = ROOT / "build"
STOCK_SHA256 = "5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa"
PATCH_BASE = 0x4190


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def thumb_bl(source, target):
    offset = target - (source + 4)
    assert offset >= 0 and offset < 0x1000000 and offset % 2 == 0
    first = 0xF000 | ((offset >> 12) & 0x3FF)
    second = 0xF800 | ((offset >> 1) & 0x7FF)
    return struct.pack("<HH", first, second)


def thumb_b(source, target, condition=None):
    offset = target - (source + 4)
    assert offset % 2 == 0
    immediate = offset >> 1
    if condition is None:
        assert -0x800 <= immediate < 0x800
        return struct.pack("<H", 0xE000 | (immediate & 0x7FF))
    assert -0x80 <= immediate < 0x80
    return struct.pack("<H", 0xD000 | (condition << 8) | (immediate & 0xFF))


def symbols(elf):
    output = subprocess.check_output(["llvm-nm", "-n", str(elf)], text=True)
    result = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 3:
            result[fields[2]] = int(fields[0], 16)
    return result


def main():
    stock = STOCK.read_bytes()
    assert hashlib.sha256(stock).hexdigest() == STOCK_SHA256, "stock image changed"
    BUILD.mkdir(exist_ok=True)

    common = [
        "clang", "--target=armv6m-none-eabi", "-mcpu=cortex-m0", "-mthumb",
        "-Os", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
        "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-Wall", "-Wextra", "-Werror",
    ]
    run(*common, "-c", str(SOURCE / "persistence.c"), "-o", str(BUILD / "persistence.o"))
    run("clang", "--target=armv6m-none-eabi", "-mcpu=cortex-m0", "-mthumb", "-c", str(SOURCE / "persistence_hooks.s"), "-o", str(BUILD / "hooks.o"))
    run(
        "ld.lld", "-T", str(SOURCE / "persistence.ld"), "--Map", str(BUILD / "persistence.map"),
        "-o", str(BUILD / "persistence.elf"), str(BUILD / "persistence.o"), str(BUILD / "hooks.o"),
    )
    run("llvm-objcopy", "-O", "binary", str(BUILD / "persistence.elf"), str(BUILD / "persistence.bin"))

    names = symbols(BUILD / "persistence.elf")
    required = {"boot_restore", "dispatch_set_hook", "dispatch_get_hook", "save_current", "get_saved_response", "get_current_response", "get_profile_response", "set_effect_recipe", "set_stock_mode", "set_live_color", "usb_configured", "lighting_state_guard", "callback_zero_guard", "callback_two_guard", "lighting_poll_guard", "set_direct_mode"}
    assert required <= names.keys(), f"missing symbols: {required - names.keys()}"
    undefined = subprocess.check_output(["llvm-nm", "-u", str(BUILD / "persistence.elf")], text=True).strip()
    assert not undefined, f"undefined symbols: {undefined}"

    appended = (BUILD / "persistence.bin").read_bytes()
    assert appended, "empty patch"
    assert names["boot_restore"] == PATCH_BASE, "linked boot address changed"
    candidate = bytearray(stock)
    assert len(candidate) + 0x2000 == PATCH_BASE, "stock end does not match linked patch base"
    candidate.extend(appended)
    candidate.extend(b"\xff" * ((4 - len(candidate) % 4) % 4))
    assert len(candidate) <= 0x7000, "candidate exceeds MM800 application slot"

    patches = [
        (0x3A8C, thumb_bl(0x3A8C, names["boot_restore"])),
        (0x3AAE, thumb_bl(0x3AAE, names["lighting_state_guard"])),
        (0x35E6, thumb_bl(0x35E6, names["lighting_poll_guard"])),
        (0x2BC4, thumb_bl(0x2BC4, names["lighting_state_guard"])),
        (0x30CA, thumb_bl(0x30CA, names["dispatch_set_hook"])),
        (0x30CE, thumb_b(0x30CE, 0x30E6, condition=0xC)),
        (0x30D0, thumb_b(0x30D0, 0x30D2)),
        (0x313C, thumb_bl(0x313C, names["set_live_color"])),
        (0x31FC, thumb_bl(0x31FC, names["dispatch_get_hook"])),
        (0x3200, thumb_b(0x3200, 0x32FA)),
    ]
    for address, encoded in patches:
        offset = address - 0x2000
        candidate[offset:offset + len(encoded)] = encoded

    candidate[0x3AE0 - 0x2000:0x3AE4 - 0x2000] = struct.pack("<I", names["callback_two_guard"] | 1)
    candidate[0x3AE8 - 0x2000:0x3AEC - 0x2000] = struct.pack("<I", names["callback_zero_guard"] | 1)
    candidate[0x3AE4 - 0x2000:0x3AE8 - 0x2000] = struct.pack("<I", names["usb_configured"] | 1)
    candidate[0x2C84 - 0x2000:0x2C88 - 0x2000] = struct.pack("<I", 750)
    candidate[0x106:0x108] = struct.pack("<H", 0x0103)
    assert len(candidate) <= 0x2F00, "code overlaps fixed build-info address"
    candidate.extend(b"\xff" * (0x2F00 - len(candidate)))
    candidate.extend(b"MM8BUILD" + bytes(32) + struct.pack("<II", 0x0103, 0))
    embedded_hash = hashlib.sha256(candidate).digest()
    expected_hash = load_firmware_version()["embedded_build_hash"]
    assert embedded_hash.hex() == expected_hash, f"firmware build changed to {embedded_hash.hex()}; update version.yml with a new release and hash"
    candidate[0x2F08:0x2F28] = embedded_hash
    assert len(candidate) <= 0x7000, "candidate exceeds MM800 application slot"

    output = BUILD / "SageApp_v1.02.50-eeprom-persistence.bin"
    output.write_bytes(candidate)
    metadata = BUILD / "addresses.txt"
    metadata.write_text("".join(f"{name}=0x{names[name]:08x}\n" for name in sorted(required)))
    print(f"built={output}")
    print(f"size={len(candidate)}")
    print(f"embedded_build_hash={embedded_hash.hex()}")
    print(f"sha256={hashlib.sha256(candidate).hexdigest()}")
    print(metadata.read_text(), end="")


if __name__ == "__main__":
    main()
