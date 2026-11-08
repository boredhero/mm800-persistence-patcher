#!/usr/bin/env python3
import shutil
from pathlib import Path

REQUIRED = [
    "python3",
    "clang",
    "ld.lld",
    "llvm-objcopy",
    "llvm-nm",
    "udisksctl",
    "lsblk",
    "findmnt",
]

INSTALL = {
    "debian": "sudo apt update && sudo apt install clang lld llvm python3 udisks2 util-linux",
    "fedora": "sudo dnf install clang lld llvm python3 udisks2 util-linux",
    "arch": "sudo pacman -S clang lld llvm python udisks2 util-linux",
}


def distro_family():
    try:
        text = Path("/etc/os-release").read_text().lower()
    except OSError:
        return "debian"
    if "fedora" in text or "rhel" in text or "centos" in text:
        return "fedora"
    if "arch" in text or "manjaro" in text:
        return "arch"
    return "debian"


def main():
    print("Checking required commands:\n")
    missing = []
    for command in REQUIRED:
        present = shutil.which(command)
        print(f"{command:16} {present or 'MISSING'}")
        if not present:
            missing.append(command)
    if not missing:
        print("\nAll required commands are available.")
        return
    family = distro_family()
    print(f"\nMissing: {', '.join(missing)}")
    print(f"Suggested install command for this system ({family}):\n{INSTALL[family]}")
    print("\nReview that command with your administrator before running it.")


if __name__ == "__main__":
    main()
