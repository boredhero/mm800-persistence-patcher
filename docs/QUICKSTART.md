# Beginner quickstart

This is the guided, full-ISP workflow. You do not need to know how firmware
works, and you do not need to delete or rename anything on the recovery drive.

## 1. Install the tools

You need Python 3, Clang/lld with Cortex-M0 support, `llvm-objcopy`, and Linux
`udisksctl`, `lsblk`, and `findmnt`. All Python code uses the standard library;
no virtual environment is required. See `dependencies.md` for install commands.

### Ubuntu or Debian

```sh
sudo apt update
sudo apt install clang lld llvm python3 udisks2 util-linux
```

### Arch Linux or Manjaro

```sh
sudo pacman -S --needed clang lld llvm python udisks2 util-linux
```

These packages provide Python 3, Clang/lld, `llvm-objcopy`, `udisksctl`,
`lsblk`, and `findmnt`. You can also run
`python3 tools/check_dependencies.py` to check what is missing.

You also need the MM800 and its underside pinhole button.

## 2. Run the wizard

From the directory containing the cloned repository:

```sh
python3 mm800-persistence-patcher/tools/mm800_patch_and_flash.py
```

For a different output directory:

```sh
python3 mm800-persistence-patcher/tools/mm800_patch_and_flash.py \
  --output-dir my-mm800-backup
```

The output directory must be new. It will contain the original backup and the
generated image; keep it and do not upload it.

## 3. Follow the prompts

1. Unplug the MM800.
2. Hold the pinhole with a paperclip while plugging it back in.
3. When `CRP DISABLD` appears, press Enter in the wizard.
4. The wizard mounts the drive read-only and copies `firmware.bin` twice. It
   checks that both copies match.
5. It verifies that your backup contains the supported stock application and
   builds the patched full image.
6. Read the image hash. If you want to proceed, type `FLASH` exactly.
7. The wizard writes the image in place with `nocreat,notrunc,fsync` and
   requires exact readback verification.
8. Unplug and reconnect without the pinhole. Press Enter to check the embedded
   build record.

If verification fails, do not reboot. Use the original backup in the output
directory with the same in-place recovery procedure. See
`backup-and-recovery.md`.

## 4. Choose colors

From the repository directory:

```sh
python3 tools/mm800_persistence_tool.py set-rgb 00ff00
python3 tools/mm800_persistence_tool.py save --approve-eeprom-write
python3 tools/mm800_persistence_tool.py get-saved
```

`00ff00` is green. Try `0000ff` for blue or `ffffff` for white. Each zone can
also have a different color. The tool auto-locates the MM800 control interface.

Before the first save, back up EEPROM:

```sh
python3 tools/mm800_persistence_tool.py dump-eeprom ../eeprom-before.bin
```

The save command writes the current profile and checks every RGB byte. Live
brightness remains separate: levels 0–8 are live and levels 0–3 can be saved.
The 75% renderer cap is preserved.

## Restore the original firmware

If the modified firmware causes trouble, restore the original stock backup:

```sh
python3 tools/mm800_restore.py --backup ../mm800-work/mm800-full-backup-01.bin
```

Enter pinhole mode again and type `RESTORE` when asked. The restore tool
checks the backup, writes it in place, and verifies the readback. Do not use an
app-only image for this.

## Important warnings

- Only the exact stock application hash in `SAFETY.md` is supported.
- Never write the app-only file into the recovery drive.
- Never delete or truncate the recovery drive's `firmware.bin` on Linux.
- Building does not flash automatically, and saving a profile requires separate
  approval.
- This is unofficial and experimental. There is no guarantee of recovery.
