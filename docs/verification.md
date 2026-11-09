# Verification

## Offline checks

`tools/verify_image.py` checks:

- image length and SHA-256;
- the NXP first-eight-vector checksum;
- Thumb reset target within the application;
- USB vendor/product identity;
- embedded `MM8BUILD` hash, when present; and
- optional changed ranges against the original stock file.

These checks detect malformed or unintended changes. They are not a hardware
safety or signature verdict.

Run from the firmware directory:

```sh
python3 tools/verify_image.py \
  build/SageApp_v1.02.50-eeprom-persistence.bin --compare-stock
```

The builder also requires `boot_restore == 0x4190`, inserts code directly at
that linked base, pads only after the appended code, and rejects images larger
than the `0x7000` application slot.

## Test distinctions

- Structural verification is not hardware proof.
- CPU emulation exercises selected paths with mocked peripherals and is not a
  full device boot.
- An updater reporting success is not a readback.
- A backup existing is not a tested restore.
- One successful device/tester combination is not universal compatibility.

## Required hardware checks

Before calling a build hardware-tested, verify normal enumeration, factory
fallback, live RGB, read-only EEPROM backup, exact save/readback, power-cycle
restoration, A/B selection, invalid-record fallback, fail-closed read errors,
and stock restoration. Record the exact image hash and tested scope.

The public repository contains no firmware or generated artifacts. CI tests
only source and synthetic fixtures.

## Stock and backup hashes

- Stock application: `5917b0de570296ba2a80cf5aa67f5bf0ef3026685453eb070364f450c3ab65fa`
- Verified original full backup: `a7dcb5367383c18d6d3df6afaeff282e77aacaf47cd6fbb9193e080c83919aae`
- Final full ISP image: `bf9fe9c2bf134c7369990dc20e01e7c5eaae617944fc1e27dc51dfdcd55827c0`

The full backup is 131,072 bytes. The stock application is only a section of
it. The full ISP image preserves the original bootloader and places the patched
application in both application slots. Other users' full backups may differ in
hash, but the stock application hash must match exactly.
