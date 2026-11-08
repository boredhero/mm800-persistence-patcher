# Backup, write, and recovery

## Make a full backup

1. Stop RGB-control software and unplug the MM800.
2. Hold the underside pinhole while reconnecting USB.
3. Identify the new `LPC1XXX IFLASH` / `CRP DISABLD` device using `lsblk`.
4. Mount it read-only with `udisksctl mount -o ro -b /dev/sdX`.
5. Copy `firmware.bin` off the device twice, compare SHA-256 hashes, and make
   both copies read-only. A full backup is 131,072 bytes.
6. Unmount with `udisksctl unmount -b /dev/sdX`.

The app-only `SageApp_v1.02.50.bin` is not a full backup and must not be
written at address zero.

## Write or restore an image

Use a fresh pinhole session and the guarded script:

```sh
MM800_ISP_WRITE=YES tools/isp_write_verified.sh \
  /dev/sdX image.bin <expected-sha256>
```

The script checks the device label/model, source image size/hash, and the
ROM-created file size. It then overwrites the existing file in place with
`dd bs=512 conv=nocreat,notrunc,fsync`, syncs, unmounts, remounts read-only,
and requires exact readback hash and `cmp` matches.

Never delete, truncate, or recreate the ROM-created file on Linux. Do not
reboot after a failed readback. Restore the verified original backup with the
same procedure and verify again.

## Verify normal operation

Only after exact readback, unplug and reconnect without the pinhole. Check
enumeration, stock lighting behavior, live RGB, and the embedded build record.
An updater reporting success is not proof of installed bytes; use readback.

## Recovery status

The original full backup was restored and verified byte-for-byte using this
procedure during development, and stock USB operation was confirmed. That is
evidence for the reviewed device and procedure, not a guarantee for every
host, image, or future attempt.
