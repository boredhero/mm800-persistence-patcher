# Custom animation device protocol

## Capability query: GET26

`0e 26` returns 64 bytes. Byte 4 is protocol version 1. Other fields:

- `5`: upload state: 0 empty, 1 uploading, 2 valid.
- `6`: codec bitmask `0x1f`: dictionary raw/palette, delta raw/palette, envelope.
- `7`: active codec.
- `8`: committed-animation valid flag.
- `9..10`: usable payload capacity, currently 1,728 bytes.
- `11..12`: committed binary size.
- `13..16`: committed generation.
- `17..20`: uploaded byte offset.
- `21..24`: last upload status; zero is success.
- `25..26`: timing quantum, 34 ms.
- `27..28`: maximum palette colors, 256.
- `29..30`: maximum tracks, 15.
- `31..34`: maximum duration in ticks, 65,535.

Connected installation must query this before writing and reject unsupported
codecs or oversized payloads before the first upload command.

## Upload: SET26

Byte 2 selects the operation:

- `00 BEGIN`: bytes 3–4 are total binary size; byte 5 is codec. Start writing the
  inactive bank in UPLOADING state.
- `01 DATA`: bytes 3–4 are the payload offset; bytes 5 onward contain up to 48
  bytes. Offsets must be exactly sequential.
- `02 COMMIT`: validate the complete binary and readback before marking the bank
  VALID. Previous valid data is preserved on failure.
- `03 ABORT`: abandon the inactive upload and leave the previous valid bank intact.

Each bank is 1,792 bytes: a 64-byte header and 1,728 bytes of payload. Banks A and
B start at EEPROM offsets `0x180` and `0x880`. The top 64 bytes remain reserved.
The header contains magic, version, state, generation, total size, and integrity
information. Playback never writes persistent storage.

## Runtime ownership

A valid custom bank uses runtime owner 5, separate from stock, saved static,
saved built-in animation, and host live control. Static RGB/mode takeover remains
reliable. Boot validates the newest valid bank and falls back to the older valid
bank if the newest is corrupt. Suspend/resume preserves the committed recipe.
