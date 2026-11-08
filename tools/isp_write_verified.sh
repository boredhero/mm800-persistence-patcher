#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: MM800_ISP_WRITE=YES $0 /dev/sdX image.bin expected-sha256" >&2
    exit 2
fi

DEVICE=$1
IMAGE=$2
EXPECTED=$3
MOUNTED=0

cleanup() {
    if [[ $MOUNTED -eq 1 ]]; then
        udisksctl unmount -b "$DEVICE" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

[[ "${MM800_ISP_WRITE:-}" == "YES" ]] || { echo "set MM800_ISP_WRITE=YES to authorize the flash write" >&2; exit 3; }
[[ -b "$DEVICE" ]] || { echo "not a block device: $DEVICE" >&2; exit 4; }
[[ -f "$IMAGE" ]] || { echo "not a file: $IMAGE" >&2; exit 5; }
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]] || { echo "expected SHA-256 must be 64 lowercase hex characters" >&2; exit 6; }
[[ $(stat -c%s "$IMAGE") -eq 131072 ]] || { echo "image is not exactly 131072 bytes" >&2; exit 7; }
[[ $(sha256sum "$IMAGE" | awk '{print $1}') == "$EXPECTED" ]] || { echo "source image hash mismatch" >&2; exit 8; }
[[ $(lsblk -no LABEL "$DEVICE") == "CRP DISABLD" ]] || { echo "unexpected device label" >&2; exit 9; }
[[ $(lsblk -no MODEL "$DEVICE") == "LPC1XXX IFLASH" ]] || { echo "unexpected device model" >&2; exit 10; }

if findmnt -S "$DEVICE" >/dev/null; then
    udisksctl unmount -b "$DEVICE"
fi

udisksctl mount -o sync -b "$DEVICE"
MOUNTED=1
TARGET=$(findmnt -S "$DEVICE" -n -o TARGET)/firmware.bin
[[ -f "$TARGET" ]] || { echo "ROM-created firmware.bin is missing" >&2; exit 11; }
[[ $(stat -c%s "$TARGET") -eq 131072 ]] || { echo "unexpected on-device firmware.bin size" >&2; exit 12; }

dd if="$IMAGE" of="$TARGET" bs=512 conv=nocreat,notrunc,fsync status=none
sync
udisksctl unmount -b "$DEVICE"
MOUNTED=0

udisksctl mount -o ro -b "$DEVICE"
MOUNTED=1
TARGET=$(findmnt -S "$DEVICE" -n -o TARGET)/firmware.bin
READBACK=$(sha256sum "$TARGET" | awk '{print $1}')
[[ "$READBACK" == "$EXPECTED" ]] || { echo "readback hash mismatch: $READBACK; do not reboot" >&2; exit 13; }
cmp -- "$TARGET" "$IMAGE"
udisksctl unmount -b "$DEVICE"
MOUNTED=0
trap - EXIT
printf 'verified_readback=%s\n' "$READBACK"
