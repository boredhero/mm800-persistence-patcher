# MM800 persistence patcher

**Unofficial experimental firmware modification. Use at your own risk.**
This project can modify firmware and, after separate approval, write a
profile to EEPROM. Incorrect use could require low-level recovery. No warranty
or guarantee of recovery is provided. This project is not affiliated with or
supported by Corsair.

An MIT-licensed, source-only, local patcher for the Corsair MM800 RGB Polaris.
It adds saved static per-zone RGB while preserving the stock brightness knob
and the manufacturer's 75% renderer cap.

## Quickstart

### 1. Install the programs this project needs

These commands install Python, the compiler, and the USB drive tools used by
the wizard.

Ubuntu or Debian:

```sh
sudo apt update
sudo apt install clang lld llvm python3 udisks2 util-linux
```

Arch Linux or Manjaro:

```sh
sudo pacman -S clang lld llvm python udisks2 util-linux
```

Check that everything is installed:

```sh
python3 tools/check_dependencies.py
```

### 2. Clone the project and run the guided backup/build/flash workflow:

```sh
git clone https://github.com/boredhero/mm800-persistence-patcher.git
cd mm800-persistence-patcher
python3 tools/mm800_patch_and_flash.py --output-dir ../mm800-work
```

The wizard will tell you when to unplug, hold the pinhole, and reconnect. It
prints the exact backup paths before asking you to type `FLASH`. It then
requires an exact readback match and checks the embedded build record.

Restore the original stock backup if needed:

```sh
python3 tools/mm800_restore.py --backup ../mm800-work/mm800-full-backup-01.bin
```

Set and save green after the modified firmware is running:

```sh
python3 tools/mm800_persistence_tool.py set-rgb 00ff00
python3 tools/mm800_persistence_tool.py save --approve-eeprom-write
python3 tools/mm800_persistence_tool.py get-saved
```

See `docs/QUICKSTART.md` for a beginner-friendly walkthrough and
`docs/backup-and-recovery.md` for the recovery procedure.

## Supported device and firmware

- USB: `1b1c:1b3b`
- Application: `SageApp_v1.02.50.bin`
- Length: 8,592 bytes
- SHA-256: `5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa`

All other versions are rejected. No firmware is included in this repository.
You must supply a full backup from your own MM800 and extract the stock
application locally. See `SAFETY.md`.

## Features

- Restore one static 15-zone RGB profile after power loss.
- Independent color per zone; multicolor profiles are supported.
- Alternating A/B records for interrupted-save recovery.
- Fail closed if either EEPROM slot cannot be read.
- Read-only EEPROM diagnostic backup.
- Stock live and persistent brightness levels remain separate from RGB.
- Embedded build identity and structural verification.

Static RGB only: animation metadata is not currently saved. The renderer's
750/1000 cap is preserved.

## Requirements

- Python 3
- Clang/lld with Cortex-M0 support and `llvm-objcopy`
- Linux `udisksctl`, `lsblk`, and `findmnt` for the ISP workflow
- A user-supplied full backup from the exact supported MM800

The supported update path is full ISP with a verified backup and readback.
The normal application-only updater was not reliable during testing.

## Easiest path: guided backup, build, and flash

The normal application-only updater was not reliable during testing, so the
supported workflow is full ISP with a verified backup and readback. The wizard
handles it for you:

```sh
python3 mm800-persistence-patcher/tools/mm800_patch_and_flash.py
```

It will:

1. Ask you to unplug and hold the pinhole while reconnecting.
2. Mount the recovery drive read-only and make two matching backups.
3. Verify stock 1.02.50 and build the full image locally.
4. Show the image hash and ask you to type `FLASH` before any write.
5. Require exact readback and then check the embedded build record.

The output directory defaults to `mm800-work` in the current directory and
must be new. Backups and generated images stay out of the repository. See
`docs/QUICKSTART.md` for a beginner-friendly walkthrough.

## Advanced: manual build

From the directory containing your stock application:

```sh
python3 ../mm800-persistence-patcher/tools/build_patched_application.py
python3 ../mm800-persistence-patcher/tools/verify_image.py \
  ../mm800-persistence-patcher/tools/build/SageApp_v1.02.50-eeprom-persistence.bin --compare-stock
```

For a full ISP image, place `mm800-full-backup-01.bin` in that directory and
run `python3 ../mm800-persistence-patcher/tools/build_full_image.py`.

For a manual full ISP write, use a fresh pinhole session and explicit approval:

```sh
MM800_ISP_WRITE=YES ../mm800-persistence-patcher/tools/isp_write_verified.sh \
  /dev/sdX ../mm800-persistence-patcher/tools/build/MM800-full-eeprom-persistence-ISP.bin <expected-sha256>
```

The script checks device identity, image size/hash, and the ROM-created file;
performs the in-place write; and requires an exact readback match. It never
deletes or truncates `firmware.bin`. Do not reboot after a mismatch—restore the
original backup with the same procedure.

## Profile control

The host tool auto-locates and caches the MM800 control interface:

```sh
python3 tools/mm800_persistence_tool.py get-current
python3 tools/mm800_persistence_tool.py set-rgb 00ff00
python3 tools/mm800_persistence_tool.py save --approve-eeprom-write
python3 tools/mm800_persistence_tool.py get-saved
```

Before the first save, back up EEPROM:

```sh
python3 tools/mm800_persistence_tool.py dump-eeprom ../eeprom-before.bin
```

Other diagnostics:

```sh
python3 tools/mm800_persistence_tool.py iap-debug
python3 tools/mm800_persistence_tool.py chip-info
```

An explicit `/dev/hidrawN` can replace auto discovery. The locator validates
cached identity and invalidates it after repeated communication failures.

## Verification and support

Read `docs/verification.md`, `docs/backup-and-recovery.md`, and
`docs/hardware-test-results.md` before treating any image as tested. Report
issues without attaching firmware or device backups; see `SECURITY.md`.

The MIT license covers only original project contributions, not Corsair
firmware or locally generated images containing it. See `NOTICE.md`.
