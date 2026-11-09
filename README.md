# MM800 Persistence Firmware Patcher + Control Scripts

**Unofficial experimental firmware modification. Use at your own risk.**
This project can modify firmware and, after separate approval, write a
profile to EEPROM. Incorrect use could require low-level recovery. No warranty
or guarantee of recovery is provided. This project is not affiliated with or
supported by Corsair.

An MIT-licensed, source-only, local patcher and control tool for the Corsair
MM800 RGB Polaris. It adds saved static per-zone RGB and device-run animations
while preserving the stock brightness knob and manufacturer's 75% renderer cap.

**You normally flash the firmware only once.** After that, the control script
changes and saves colors and brightness without flashing. Reflash only when a
project update changes the firmware itself, not for ordinary control-script or
documentation updates.

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
sudo pacman -Sy --needed clang lld llvm python udisks2 util-linux
```

### 2. Clone the project and run the guided backup/build/flash workflow:

```sh
git clone https://github.com/boredhero/mm800-persistence-patcher.git
cd mm800-persistence-patcher
python3 tools/mm800_patch_and_flash.py --output-dir ../mm800-work
```

The wizard checks for required programs automatically and stops with an install
command if anything is missing. It will tell you when to unplug, hold the
pinhole, and reconnect. It prints the exact backup paths before asking you to
type `FLASH`. It then requires an exact readback match and checks the embedded
build record.

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

Set live brightness level 2, or save level 2 for future boots without changing
the current brightness:

```sh
python3 tools/mm800_persistence_tool.py brightness 2
python3 tools/mm800_persistence_tool.py brightness 2 --save
```

Live levels are 0–8; persistent levels are 0–3. These are integer driver
levels, not percentages.

Set a multicolor profile by entering one six-digit RGB color for each of the 15
zones, in order. This white-to-deep-purple gradient sets live colors and then
saves them:

```sh
python3 tools/mm800_persistence_tool.py set-zones ffffff f2e5ff e6ccff d9b3ff cc99ff bf80ff b366ff a64dff 9933ff 8c1aff 8000ff 6d00db 5a00b8 470094 180068
python3 tools/mm800_persistence_tool.py save --approve-eeprom-write
```

Preview device-run animations without writing EEPROM:

```sh
python3 tools/mm800_persistence_tool.py effect breathing 8000ff
python3 tools/mm800_persistence_tool.py effect breathing 8000ff --speed 2
python3 tools/mm800_persistence_tool.py effect rainbow --speed 0
python3 tools/mm800_persistence_tool.py effect moving-rainbow --speed 2
```

Add `--save` to any of those exact commands to save the same recipe and verify
its committed readback. For example:

```sh
python3 tools/mm800_persistence_tool.py effect breathing 8000ff --speed 2 --save
python3 tools/mm800_persistence_tool.py get-profile
```

Breathing supports speeds 1–2; both rainbow effects support 0–2. The broken
fast-breathing speed 0 preset is rejected. Use `capabilities` to check support
and `release` to return to stock animation without erasing the saved profile.
Uploaded frame sequences are not supported.

See `docs/QUICKSTART.md` for a beginner-friendly walkthrough and
`docs/backup-and-recovery.md` for the recovery procedure.

## Firmware updates

The control tool automatically compares the installed firmware's embedded build
ID with `version.yml` and warns when they differ. If an update is needed:

```sh
git fetch && git pull
python3 tools/mm800_patch_and_flash.py \
  --stock-backup ../mm800-work/mm800-full-backup-01.bin \
  --output-dir ../mm800-update
```

Use your original full stock backup and a new output directory. The wizard
verifies that backup, builds the updated full image, and asks before flashing.
You do not need to restore stock first. Keep the original backup afterward.

## Supported device and backup

Use a Corsair MM800 RGB Polaris, USB `1b1c:1b3b`, with stock firmware 1.02.50 (latest as of 11-08-2026).
The wizard backs up `firmware.bin`, verifies it, patches it locally, and writes
it back only after you approve. It also prints where your original backup is
stored so you can restore it later.

The original full backup and stock application are never included in this
repository. Exact hashes and the stock-layout details are in
`docs/verification.md` and `SAFETY.md`; you do not need to understand them to
use the wizard.

## Features

- Restore one static 15-zone RGB profile or device-run animation after power loss.
- Breathing, uniform rainbow, and moving rainbow at validated speed code 1.
- Identical animation parameters for preview and verified persistent save.
- Independent color per zone; multicolor static profiles are supported.
- Alternating A/B records for interrupted-save recovery and V1 static migration.
- Fail closed if either EEPROM slot cannot be read.
- Read-only EEPROM diagnostic backup.
- Stock live and persistent brightness levels remain separate from RGB/effects.
- Embedded build identity and structural verification.

The renderer's 750/1000 cap is preserved. Uploaded frame sequences and arbitrary
streamed-animation playback are not implemented. Animation persistence currently
has offline CPU-test coverage; see `docs/animation-validation.md` before hardware
validation.

## Requirements

- Python 3
- Clang/lld with Cortex-M0 support and `llvm-objcopy`
- Linux `udisksctl`, `lsblk`, and `findmnt` for the ISP workflow
- A user-supplied full backup from the exact supported MM800

The supported workflow is the pinhole full-backup and full-image write with
verified readback.

## Easiest path: guided backup, build, and flash

The wizard handles the complete pinhole workflow for you:

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
