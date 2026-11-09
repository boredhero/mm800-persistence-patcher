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
    "arch": "sudo pacman -Sy --needed clang lld llvm python udisks2 util-linux",
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


def require_dependencies():
    missing = [command for command in REQUIRED if not shutil.which(command)]
    if missing:
        family = distro_family()
        raise RuntimeError(
            f"missing required programs: {', '.join(missing)}\n"
            f"Install them with: {INSTALL[family]}"
        )


def main():
    print("Checking required commands:\n")
    for command in REQUIRED:
        present = shutil.which(command)
        print(f"{command:16} {present or 'MISSING'}")
    require_dependencies()
    print("\nAll required commands are available.")


if __name__ == "__main__":
    main()
