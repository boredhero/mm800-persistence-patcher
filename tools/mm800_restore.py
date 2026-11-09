#!/usr/bin/env python3
import argparse
import hashlib
import os
import subprocess
from pathlib import Path

from check_dependencies import require_dependencies
from mm800_patch_and_flash import ROOT, STOCK_SHA256, find_recovery_device, run

FULL_SIZE = 131072
APP_OFFSET = 0x2000
APP_SIZE = 0x2190


def validate_stock_backup(path):
    data = path.read_bytes()
    if len(data) != FULL_SIZE:
        raise RuntimeError("backup is not a complete 128 KiB image")
    application = data[APP_OFFSET:APP_OFFSET + APP_SIZE]
    if hashlib.sha256(application).hexdigest() != STOCK_SHA256:
        raise RuntimeError("backup does not contain the supported stock application")
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Restore a stock MM800 full backup with readback verification")
    parser.add_argument("--backup", required=True, help="path to mm800-full-backup-01.bin")
    args = parser.parse_args()
    require_dependencies()
    backup = Path(args.backup).resolve()
    backup_hash = validate_stock_backup(backup)
    print(f"Stock backup: {backup}\nSHA-256: {backup_hash}")

    input("Unplug the MM800, hold the pinhole, reconnect it, then press Enter when CRP DISABLD appears...")
    device = find_recovery_device()
    print(f"Found recovery device: {device}")
    confirmation = input("Type RESTORE to write the original stock backup, or anything else to stop: ")
    if confirmation != "RESTORE":
        print("Stopped without writing firmware.")
        return
    environment = os.environ.copy()
    environment["MM800_ISP_WRITE"] = "YES"
    run([
        str(ROOT / "tools" / "isp_write_verified.sh"),
        device,
        str(backup),
        backup_hash,
    ], env=environment)
    print("Stock backup restored and verified. Unplug and reconnect without the pinhole.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        raise SystemExit(f"Stopped: {error}\nDo not reboot after an unverified or failed write.")
