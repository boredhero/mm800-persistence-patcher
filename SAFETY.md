# Safety

**Unofficial experimental firmware modification. Use at your own risk.**

This project can modify device firmware and, only after separate approval,
write lighting profiles to EEPROM. Incorrect use, an unsupported hardware
revision, a failed update, or a software defect could leave the device
unusable or require low-level recovery. No warranty is provided. A backup and
a matching checksum do not guarantee successful recovery. This project is not
affiliated with or supported by Corsair.

## Supported input only

- Device: Corsair MM800 RGB Polaris, USB `1b1c:1b3b`
- Stock application: `SageApp_v1.02.50.bin`
- Length: 8,592 bytes (`0x2190`)
- SHA-256: `5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa`

Every other application version or hash is rejected. If you have an older
version, use Corsair's official process to reach 1.02.50 and create a fresh
backup. If Corsair offers a newer version, do not assume it is supported.

## Required boundaries

- Keep the original full backup and stock application unchanged and outside
  the repository.
- Build and flash are separate commands with separate confirmations.
- A build never flashes automatically.
- Flashing requires explicit `MM800_ISP_WRITE=YES` for the provided ISP script,
  or the corresponding deliberate action in the normal application updater.
- The first profile save requires a separate `--approve-eeprom-write`.
- Never select a device merely because it is the first Corsair or HID device.
- Stop on read errors, write errors, unsupported versions, short reads,
  verification failures, and ambiguous device selection.

## Full backup and recovery

A full MM800 backup is 131,072 bytes. Preserve two identical copies outside
the repository and record their hashes. An app-only image is not a full backup
and must not be written at flash address zero.

On Linux, do not delete, truncate, or recreate the ROM-created `firmware.bin`.
Overwrite it in place using 512-byte writes with `conv=nocreat,notrunc,fsync`,
a synchronous mount, `sync`, and full readback verification. If verification
fails, do not reboot; restore the verified original backup using the same
method.

## Brightness and profile storage

The renderer's stock 750/1000 intensity cap is preserved. Do not raise it
without a separate safety review. Live RGB updates remain RAM-only. Saving a
profile uses alternating A/B EEPROM records and must be verified byte-for-byte.
Saving is aborted if either slot cannot be read.

The current profile stores static RGB only. Animation metadata is outside the
current save format. Stock brightness levels are separate: live levels 0–8 and
persistent levels 0–3; these are integer driver levels, not percentages.

See `docs/backup-and-recovery.md` and `docs/verification.md` for the exact
procedures and remaining limitations.
