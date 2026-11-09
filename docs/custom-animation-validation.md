# Custom animation validation

## Tested firmware identity

- Application SHA-256: `732fd06bca1237e5878c6de4cb0989b1596856b8609bf114ec67637f1e40dedd`
- Embedded build hash: `2fdd9f17c820db213cceb9feb84736f47fa1bec1a9499c354940577064e93b4c`
- Full ISP SHA-256 using the preserved original backup: `6e144157c0ec3c8bc7c10995cc2cbe41938c8fbe428c44fdd4a2751c5d048d6c`
- Original full backup: `a7dcb5367383c18d6d3df6afaeff282e77aacaf47cd6fbb9193e080c83919aae`
- Firmware patch release: 6

The candidate is preserved outside the repository at:

```text
/home/noah/Downloads/MM800-firmware/analysis/custom-animation-candidate-v6-ram-cache/
```

The full 131,072-byte ISP write matched the candidate exactly on readback. The
normal application interface confirmed the embedded build hash above.

## Offline coverage

All 86 checks pass, including eight final-binary custom firmware tests and the
previous animation/host suites. Covered behavior:

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
- Actual initial MSP, bounded 1,503-byte patch-state reservation, and instruction-limit failures.
- JSON schema, optimizer, palette boundaries, corruption, fixed-point math, and deterministic fireflies.

Codec 3 preloads at most 153 keyframes, 15 track states, and 15 base colors into
reserved RAM. It does not read EEPROM during normal playback after initializing
the track tables. Dictionary and delta codecs retain incremental EEPROM decoding.

## Hardware results

The real MM800 restored custom generation 2, a 1,040-byte brightness-envelope
animation, after full-ISP firmware replacement and normal reconnection. No host
animation upload was needed after reconnecting.

A complete 32-query sample over 6.92 seconds observed:

- Up to four simultaneously lit zones.
- Fourteen distinct zone positions.
- Responsive USB RGB reads throughout the cycle.
- `state=2`, `valid=1`, `size=1040`, `generation=2`, and `status=0` afterward.
- Advertised envelope limits of 153 keyframes and 15 colors.

The user also visually confirmed the animation. Earlier hardware testing verified
live brightness commands, ordinary RGB takeover, and power-cycle restoration of
the smaller two-track example. Current-binary stock behavior is covered by the
final-binary emulator suite.

## Remaining limits

This is targeted hardware validation, not proof of every animation or lifecycle
path. Electrical timing, physical zone adjacency, worst-case interrupt nesting,
and USB ROM stack usage remain unproven. Suspend/resume, finite end behavior,
malformed-input handling, and stock-driver burst behavior have offline coverage
but were not all retested on this hardware. Physical adjacency was intentionally
left unconstrained in the four-zone example because no verified physical map is
available. Emulator results alone are not hardware validation.
