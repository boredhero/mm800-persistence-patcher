# Custom animation validation

## Tested firmware identity

- Application SHA-256: `ccd97e8400f626c91f3818ab6a409b8138e871243e157750c85bfec47775c68c`
- Embedded build hash: `99d3b2d602e5e7c692b7e9eb82e6b67ea5af4033b2e9ce186ab17f6805f36c0d`
- Full ISP SHA-256 using the preserved original backup: `867ac7ccd9a4e0cfb3b3fbe1033e5d8609ae4795dd60adc18ebfc98f047512a0`
- Original full backup: `a7dcb5367383c18d6d3df6afaeff282e77aacaf47cd6fbb9193e080c83919aae`
- Firmware patch release: 7

The candidate is preserved outside the repository at:

```text
/home/noah/Downloads/MM800-firmware/analysis/custom-animation-candidate-v7-iap-cache/
```

The full 131,072-byte ISP write matched the candidate exactly on readback. The
normal application interface confirmed the saved custom recipe and responsive
playback after normal reconnection.

## Offline coverage

All 54 applicable source/host/repository checks and all 35 final-binary firmware
checks pass. A clean source-only run discovers 89 tests and reports 35 skips when
firmware paths are not supplied. Covered behavior:

- Dictionary raw/palette and delta raw/palette upload and playback.
- Brightness-envelope upload, boot restoration, loop restart, and per-zone gain.
- All 176 frames of the 14-track, 1,040-byte fireflies recipe, including loop restart.
- Zero EEPROM reads during steady-state envelope playback.
- Fail-closed rejection of 154-keyframe and 16-color envelope records.
- Correct descending-fade rounding and the `65535^2` combined-gain divisor.
- USB data-call length initialization and word-aligned EEPROM source buffers.
- Exact committed recipe/readback and versioned capability query.
- Inactive-bank writes, upload abort, interrupted upload recovery, and stock RGB takeover.
- Existing static profiles, built-in effects, brightness commands, and recovery baseline.
- Actual initial MSP, bounded 1,504-byte patch-state reservation, and instruction-limit failures.
- JSON schema, optimizer, palette boundaries, corruption, fixed-point math, and deterministic fireflies.
- Exact purple-recipe output over 100 loops, one EEPROM read per changed delta frame,
  no reads on held frames, and interrupt masking at every playback IAP entry.
- Partial-delta preservation of unchanged zones with deliberately poisoned stack memory.
- Failed frame reads preserving the last good output and subsequent USB/RGB control.

Codec 3 preloads at most 153 keyframes, 15 track states, and 15 base colors into
reserved RAM. It does not read EEPROM during normal playback after initializing
the track tables. Dictionary and delta codecs cache up to 256 palette colors in
the same union and use bounded block reads. The storage overlay does not increase
the patch reservation or reduce either format's limits.

For the 1,412-byte purple delta-palette recipe, release 6 required 1,909 EEPROM
reads and approximately 761,000 emulated ARM instructions during boot validation,
then 31 reads per changed frame. Release 7 requires 110 boot reads, 208,980
instructions, and one read per changed frame. ROM execution time is not included
in those instruction counts.

## Release 6 stall investigation

After several days of purple playback, release 6 became dark and stopped answering
all patched USB queries. Normal power cycles did not recover it. Two full-ISP
backups matched each other and the release-6 image exactly, ruling out flash
corruption in the sampled image. Restoring stock firmware immediately restored
lighting.

A diagnostic firmware build skipped custom-animation restoration without changing
EEPROM. It successfully dumped the preserved 4,032-byte readable EEPROM region.
The dump SHA-256 is
`ab03c50956ec91a5c515e88085358905732f05b34176270fec54768f8a710863`.
Both custom banks contained valid, checksummed copies of the exact 1,412-byte
purple recipe, at generations 5 and 6. Saved-data corruption was therefore not
present in this incident.

These observations establish a release-6 execution defect, but do not prove that
EEPROM latency, reentrancy, watchdog behavior, or a nonreturning ROM call was the
sole trigger. Release 7 addresses the demonstrated read amplification and IAP
serialization defects and preserves the last good frame on a returned read error.

## Hardware results

Release 7 restored the existing custom generation 6 without rewriting it. The
user visually confirmed purple playback after reconnection and again after a later
power cycle. Device queries reported `state=2`, `valid=1`, codec 2, `size=1412`,
`generation=6`, and `status=0`. RGB reads one second apart showed correct advancing
frames. Stock animation takeover and live brightness also responded; the saved
EEPROM profile remained unchanged.

Earlier hardware testing restored custom generation 2, a 1,040-byte
brightness-envelope animation, after full-ISP firmware replacement and normal
reconnection. A complete 32-query sample over 6.92 seconds observed up to four
simultaneously lit zones, fourteen distinct zone positions, and responsive USB RGB
reads. Live brightness, ordinary RGB takeover, and power-cycle restoration of the
smaller two-track example were also verified.

## Remaining limits

This is targeted hardware validation, not proof of every animation or lifecycle
path. Electrical timing, physical zone adjacency, worst-case interrupt nesting,
and USB ROM stack usage remain unproven. Suspend/resume, finite end behavior,
malformed-input handling, and stock-driver burst behavior have offline coverage
but were not all retested on this hardware. Physical adjacency was intentionally
left unconstrained in the four-zone example because no verified physical map is
available. Emulator results alone are not hardware validation.

ROM/IAP calls remain synchronous. Release 7 serializes them and greatly reduces
their number, but a call that never returns would still stall the CPU. A supervised
watchdog with boot-loop-safe fallback is possible future defense-in-depth, but is
not implemented or claimed by this release. Long-term release-7 stability still
requires a hardware soak test.
