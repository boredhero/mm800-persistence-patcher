# Custom animation candidate: offline validation

## Candidate identity

- Application SHA-256: `d80cf5ab6815d97fba0b7a349aee09e64bad3a5d205f69c71166c8616e617f61`
- Embedded build hash: `f250836b3fa1a864fab2c3ab899ba2ae2f23ec52b27f19b52a2b5f10f5b0ca65`
- Full ISP SHA-256 using the preserved original backup: `e0872e34ce1a990b863f74a821786575450217e010f295e763a7c781c38f4676`
- Original full backup: `a7dcb5367383c18d6d3df6afaeff282e77aacaf47cd6fbb9193e080c83919aae`

The candidate is preserved outside the repository at:

```text
/home/noah/Downloads/MM800-firmware/analysis/custom-animation-candidate-v3/
```

No hardware installation or validation has occurred for this custom-animation
candidate. These hashes identify an offline build, not a hardware-tested release.

## Offline coverage

All 82 tests pass, including 4 final-binary custom firmware tests and the previous
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
