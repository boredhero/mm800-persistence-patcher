# Animation candidate: offline validation

## Status

Firmware patch release 2 has completed source review, deterministic builds, and
offline CPU tests. **It has not been installed or validated on hardware.** The
working static-only firmware and verified recovery image remain the baseline.
No device or EEPROM write is part of this validation.

Candidate identities:

- Application SHA-256: `07f6f7794f85ee88987de446da217209331d299ef9b80648b72b424a9a2d3e2a`
- Embedded build hash: `cbf2708b47654f3360f01bda87e62d0636d09e78e4e47890dea248b3a901f369`
- Full ISP SHA-256 using the preserved original backup: `a200ec325da9e2f86403151717663192ba6a353d6112a8285ebe6190b399c15e`
- Original full backup: `a7dcb5367383c18d6d3df6afaeff282e77aacaf47cd6fbb9193e080c83919aae`

The full image preserves the original bootloader and installs the same candidate
in both application slots. These hashes identify an offline candidate, not a
hardware-tested release.

## Offline evidence

The final patched binary passed 18 CPU test methods, including per-byte corrupted
record and interrupt-interleaving cases, plus 17 host-tool tests. Coverage includes:

- Final SET/GET dispatch and capability discovery.
- Identical preview/save parameters with only the persistence selector changed.
- No EEPROM writes for previews and bounded host polling through `BUSY` to an
  exact committed-recipe readback.
- An animation poll interrupted inside its stock RGB clear, followed by SET22:
  the interrupted poll finishes, then the queued main-loop takeover applies and
  remains stable. Immediate logical GET22 readback also matches the request.
- Configured and unconfigured resume callbacks, including preservation of the
  stock `context+0xed` condition and suspended brightness/state.
- Exact REA-derived representative frames and intended cycle behavior for all
  three presets; frozen output cannot satisfy these assertions.
- Moving-rainbow rollover at its exact 87-tick output boundary, including a
  counter seeded near the former 32-bit multiplication overflow.
- Deliberate instruction-limit exhaustion, which must fail rather than pass as a
  successful emulated return.
- V1 static compatibility, V1-to-V2 explicit-save migration, mixed versions,
  sequence rollover, and static brightness levels 0–3.
- Corrupted newest records at every byte, both-slot read errors, unsupported
  future records, failed writes, failed readback, and old-profile preservation.
- Power-cycle reconstruction and deterministic restart from committed recipes.
- Preview B without save followed by reboot into saved A.
- Suspend/resume, USB configure, deliberate host RGB takeover, and stock release.
- Stock live/persistent brightness dispatch and active LED renderer calls.
- Actual initial MSP `0x10000ac8`, packet address `0x1000041c`, and 265 bytes of
  linker-reserved patch RAM under a 384-byte assertion, including four ordered
  main-loop request slots.

Run the suite with explicit local artifact paths:

```sh
MM800_STOCK=/path/to/SageApp_v1.02.50.bin \
MM800_CANDIDATE=/path/to/SageApp_v1.02.50-eeprom-persistence.bin \
MM800_PATCH_ELF=/path/to/persistence.elf \
python3 -m unittest discover -s tests -p 'test_firmware_animation.py' -v
```

The stock image and generated binaries are intentionally not committed. CI runs
host and synthetic tests and skips this firmware suite without those paths.

## Remaining hardware gate

Before hardware validation or release, use a fresh pinhole session and the
verified full-image procedure. Check exact readback and the embedded build hash,
then test:

1. Existing V1 static restoration and all stock brightness levels.
2. Each animation preview with no EEPROM change, then exact save/readback.
3. Every saved animation after a full power cycle and on a host with no RGB
   software running.
4. Static and animation behavior through reconnect, suspend/resume, deliberate
   host RGB takeover, and stock release.
5. Rapid host takeover during active animations and repeated configured and
   unconfigured USB callbacks.
6. Failed-save behavior and restoration of the original full backup.

CPU emulation mocks IAP, USB, and LED-transfer peripherals. It does not establish
physical timing, electrical safety, full ROM USB stack usage, worst-case interrupt
nesting, or physical rainbow direction. Those remain hardware-validation and
analysis limits, not passed tests.
