# Custom animation candidate: offline validation

## Candidate identity

- Application SHA-256: `ffd05cb3f1b58280a79801844d75e9334b48435b46bae468572e1330a88728c6`
- Embedded build hash: `5b30348a8218754d290f69fa2b9382715e580deef74c695d0732847738775452`
- Full ISP SHA-256 using the preserved original backup: `7c5a6ccd626002cb7a20bafa9e54714528cc3531fed5d01bb952e1569b9dfdde`
- Original full backup: `a7dcb5367383c18d6d3df6afaeff282e77aacaf47cd6fbb9193e080c83919aae`

The candidate is preserved outside the repository at:

```text
/home/noah/Downloads/MM800-firmware/analysis/custom-animation-candidate-v3/
```

No hardware installation or validation has occurred for this custom-animation
candidate. These hashes identify an offline build, not a hardware-tested release.

## Offline coverage

All 83 tests pass, including 5 final-binary custom firmware tests and the previous
animation/host suites. Covered behavior:

- Dictionary raw/palette and delta raw/palette upload and playback.
- Brightness-envelope upload, boot restoration, loop restart, and per-zone gain.
- Exact committed recipe/readback and versioned capability query.
- Inactive-bank writes, upload abort, interrupted upload recovery, and stock RGB takeover.
- Existing static profiles, built-in effects, brightness commands, and recovery baseline.
- Actual initial MSP and instruction-limit failures.
- JSON schema, optimizer, palette boundaries, corruption, fixed-point math, and deterministic fireflies.

The decoder reads EEPROM incrementally; it does not allocate an entire animation
in RAM. The patch-state reservation is bounded to 512 bytes.

## Hardware gate

Before calling the candidate hardware-tested, verify full-ISP readback and the
embedded hash, then test JSON install, playback timing, loop boundaries, finite
ends, power-loss restoration, stock-driver bursts, brightness, reconnect,
suspend/resume, and firmware-upgrade data preservation. Actual USB ROM stack
usage, electrical timing, physical adjacency, and worst-case interrupt nesting
remain unproven. Emulator results are not hardware validation.
