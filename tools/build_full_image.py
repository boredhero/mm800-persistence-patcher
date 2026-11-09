#!/usr/bin/env python3
import hashlib
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
BACKUP = Path.cwd() / "mm800-full-backup-01.bin"
APPLICATION = BUILD / "SageApp_v1.02.50-eeprom-persistence.bin"
OUTPUT = BUILD / "MM800-full-eeprom-persistence-ISP.bin"
EXPECTED_APPLICATION_HASH = "d07ac4094736cdc7b24946e9dc01f7d97c3aeafa39a448b0ce71a78d1c209c26"

backup = BACKUP.read_bytes()
application = APPLICATION.read_bytes()
print(f"backup_sha256={hashlib.sha256(backup).hexdigest()}")
assert hashlib.sha256(application).hexdigest() == EXPECTED_APPLICATION_HASH
assert len(backup) == 0x20000
assert len(application) <= 0x7000

image = bytearray(backup)
for offset in (0x2000, 0x9000):
    image[offset:offset + 0x7000] = application + b"\xff" * (0x7000 - len(application))

for offset in (0, 0x2000, 0x9000):
    vectors = struct.unpack_from("<8I", image, offset)
    assert sum(vectors) & 0xFFFFFFFF == 0

assert image[:0x2000] == backup[:0x2000]
assert image[0x2000:0x2000 + len(application)] == application
assert image[0x9000:0x9000 + len(application)] == application
OUTPUT.write_bytes(image)
print(f"built={OUTPUT}")
print(f"size={len(image)}")
print(f"sha256={hashlib.sha256(image).hexdigest()}")
print("bootloader=original verified backup")
print("active_and_staging=hash-stamped candidate")
