#!/usr/bin/env python3
import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from check_dependencies import require_dependencies

ROOT = Path(__file__).resolve().parents[1]
STOCK_SHA256 = "5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa"
FULL_SIZE = 131072
APP_OFFSET = 0x2000
APP_SIZE = 0x2190


def run(args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, timeout=60)


def mountpoint(device):
    result = subprocess.check_output(["findmnt", "-S", device, "-n", "-o", "TARGET"], text=True)
    return result.strip()


def find_recovery_device():
    output = subprocess.check_output(
        ["lsblk", "-o", "PATH,SIZE,FSTYPE,LABEL,MODEL,TRAN"], text=True
    )
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0].startswith("/dev/") and "CRP DISABLD" in line and "LPC1XXX IFLASH" in line:
            return fields[0]
    raise RuntimeError("CRP DISABLD was not found. Unplug, hold the pinhole, reconnect, then try again.")


def backup_device(workdir, device):
    run(["udisksctl", "mount", "-o", "ro", "-b", device])
    try:
        source = Path(mountpoint(device)) / "firmware.bin"
        if source.stat().st_size != FULL_SIZE:
            raise RuntimeError(f"unexpected firmware.bin size: {source.stat().st_size}")
        first = workdir / "mm800-full-backup-01.bin"
        second = workdir / "mm800-full-backup-02.bin"
        shutil.copyfile(source, first)
        shutil.copyfile(source, second)
    finally:
        run(["udisksctl", "unmount", "-b", device])

    first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
    second_hash = hashlib.sha256(second.read_bytes()).hexdigest()
    if first_hash != second_hash:
        raise RuntimeError("backup copies differ; do not flash")
    for path in (first, second):
        os.chmod(path, 0o444)
    return first_hash


def extract_stock(workdir):
    backup = (workdir / "mm800-full-backup-01.bin").read_bytes()
    if len(backup) != FULL_SIZE:
        raise RuntimeError("full backup has the wrong size")
    application = backup[APP_OFFSET:APP_OFFSET + APP_SIZE]
    if len(application) != APP_SIZE:
        raise RuntimeError("stock application is truncated")
    if hashlib.sha256(application).hexdigest() != STOCK_SHA256:
        raise RuntimeError("this backup does not contain the supported stock 1.02.50 application")
    output = workdir / "SageApp_v1.02.50.bin"
    output.write_bytes(application)


def main():
    parser = argparse.ArgumentParser(
        description="Guided MM800 full-backup, build, and verified ISP write workflow"
    )
    parser.add_argument(
        "--output-dir",
        default="mm800-work",
        help="new directory for backups and generated images (must not already exist)",
    )
    args = parser.parse_args()
    require_dependencies()
    workdir = Path(args.output_dir).resolve()
    if workdir.exists():
        raise RuntimeError(f"refusing to reuse or overwrite {workdir}; choose a new directory")
    workdir.mkdir(parents=True)

    print(
        "MM800 full-backup and patch wizard\n"
        "This makes a full backup, checks it, builds the patched image, and asks\n"
        "before writing. Nothing is downloaded from the internet.\n"
    )
    input("Unplug the MM800, hold its underside pinhole, reconnect it, then press Enter when CRP DISABLD appears...")
    device = find_recovery_device()
    print(f"Found recovery device: {device}")

    backup_hash = backup_device(workdir, device)
    print(f"Full backup saved to {workdir / 'mm800-full-backup-01.bin'}")
    print(f"Second copy saved to {workdir / 'mm800-full-backup-02.bin'}")
    print(f"Full backup SHA-256: {backup_hash}")
    extract_stock(workdir)
    print("Stock application 1.02.50 verified.")

    run(["python3", str(ROOT / "tools" / "build_patched_application.py")], cwd=workdir)
    run(["python3", str(ROOT / "tools" / "build_full_image.py")], cwd=workdir)
    full_image = ROOT / "tools" / "build" / "MM800-full-eeprom-persistence-ISP.bin"
    image_hash = hashlib.sha256(full_image.read_bytes()).hexdigest()
    print(f"Full ISP image SHA-256: {image_hash}")

    print(
        "\nThe next step writes the complete 128 KiB image to your MM800.\n"
        "The original full backup is preserved in the output directory. If anything\n"
        "goes wrong, restore that backup with the same in-place procedure."
    )
    confirmation = input("Type FLASH to authorize this write, or anything else to stop: ")
    if confirmation != "FLASH":
        print("Stopped without writing firmware.")
        return

    environment = os.environ.copy()
    environment["MM800_ISP_WRITE"] = "YES"
    run([
        str(ROOT / "tools" / "isp_write_verified.sh"),
        device,
        str(full_image),
        image_hash,
    ], env=environment)
    print("Readback verified. Unplug and reconnect the MM800 without the pinhole.")
    input("Press Enter after it has reconnected...")
    run(["python3", str(ROOT / "tools" / "mm800_persistence_tool.py", "iap-debug")])
    print(f"Build and backup files are in {workdir}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        raise SystemExit(f"Stopped: {error}\nDo not reboot after an unverified or failed write.")
