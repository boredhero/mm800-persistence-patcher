# Custom animation binary format version 1

All integers are little-endian and unsigned. Durations are 34 ms ticks stored as
`uint32`. `total_size` includes the complete header and all sections. No trailing
bytes are allowed.

## Common 32-byte header

| Offset | Type | Meaning |
|---:|---|---|
| 0 | 4 bytes | Magic `MM8A` |
| 4 | u8 | Format version 1 |
| 5 | u8 | Codec: 1 dictionary, 2 delta |
| 6 | u8 | Flags: bit 0 loop, bit 1 finite end-off |
| 7 | u8 | Index width: 0 raw RGB, 4-bit palette, 8-bit palette |
| 8 | u16 | Header size, exactly 32 |
| 10 | u16 | Total binary size |
| 12 | u16 | Palette color count |
| 14 | u16 | Dictionary frame count; zero for delta |
| 16 | u16 | Timeline entry/record count |
| 18 | u16 | Initial dictionary frame ID; zero for delta |
| 20 | u16 | Palette section bytes, exactly `3 * palette_count` |
| 22 | u16 | Frame section bytes; zero for delta |
| 24 | u16 | Timeline section bytes |
| 26 | u16 | Reserved, zero for codecs 1–2; animation-wide gain for codec 3 |
| 28 | u32 | CRC-32 of all bytes with this field zero |

Sections follow contiguously: palette, dictionary frames when present, timeline.
Reserved fields and the high nibble of an odd final 4-bit index are zero. Unknown
versions/codecs/widths, noncanonical padding, arithmetic overflow, truncation,
inconsistent lengths, bad references, zero durations, and invalid indices/masks
are rejected.

## Codec 1: frame dictionary and timed playlist

Each dictionary frame is one of:

- Raw: exactly 45 RGB bytes.
- 4-bit palette: 15 indices packed into 8 bytes.
- 8-bit palette: 15 indices in 15 bytes.

Each timeline entry is `u16 frame_id` plus `u32 duration_ticks` (6 bytes). The
initial ID references the first timeline entry's dictionary frame. Raw encoding
has palette count/index width zero. Palette encoding supports at most 16 colors
at 4 bits or 256 at 8 bits; more colors disable that candidate, not the animation.

## Codec 2: delta sequence

The first record is always a complete initial frame. Subsequent records choose a
complete frame whenever it is not larger than a delta. Every record has its own
`u32 duration_ticks`.

- Full raw: `u8 kind=0`, `u32 duration`, 45 RGB bytes (50 total).
- Delta raw: `u8 kind=1`, `u32 duration`, `u16 changed_mask`,
  `u8 change_count`, then 3 RGB bytes per set bit, zone order (8 + 3N bytes).
- Full palette: `u8 kind=2`, `u32 duration`, packed 15 palette indices.
- Delta palette: `u8 kind=3`, `u32 duration`, `u16 changed_mask`,
  `u8 change_count`, then one 4- or 8-bit index per set bit. Four-bit replacement
  indices are packed contiguously, with a zero high nibble on an odd final value.

The mask uses bit 0 for stock zone 0 through bit 14 for zone 14; bit 15 is zero.
`change_count` must equal the mask's population count and is bounded to 15.
Full palette frames use the same canonical nibble packing as the dictionary.
Loop restart uses the initial complete record, so prior-loop RAM is irrelevant.

## Fit and inspection

The assumed offline `eeprom-ab` profile has a 1,728-byte complete-binary budget.
A candidate is reported unavailable when its palette/count/width rules cannot be
represented or its complete binary exceeds that profile. Connected installation
must query real capabilities and cannot rely on this assumption.

## Codec 3: brightness envelope

Codec 3 uses the common header with these interpretations:

- Palette contains base RGB colors, not rendered shades.
- `frame_count` is the number of zone tracks, at most 15.
- `timeline_count` is the total keyframe count.
- `initial` is the animation duration in 34 ms ticks, nonzero and at most 65,535.
- The reserved u16 at offset 26 stores the animation-wide gain. Codecs 1 and 2
  still require that field to be zero.
- `frame_bytes` is `6 * track_count`; `timeline_bytes` is `6 * keyframe_count`.

Each 6-byte track table entry is `zone:u8`, `base_color_index:u8`,
`interpolation:u8` (0 hold, 1 linear), `keyframe_count:u8`, and
`first_keyframe_index:u16`. Each zone appears once and color indices must be in
bounds. Every 6-byte keyframe is `time_ms:u32` and `gain:u16`. Times start at 0,
strictly increase, and end at the duration. Gains use the same fixed-point
semantics as the host. Base-palette widths are 4 or 8 bits, so more than 256 base
colors makes this candidate unavailable.

The decoder samples at 34 ms ticks using the original base colors and combined
zone/global gain, then applies the existing frame deduplication and timeline
merge rules. It does not require continuous-time playback or a second firmware
player. This is a storage candidate only until decoder cost, RAM, and hardware
timing are validated.
