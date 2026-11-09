# Custom animation implementation plan

## Phase A: offline model and codec evidence (this branch)

Deliver a versioned JSON schema, strict parser, canonical optimizer, four binary
encoders, strict reference decoders, deterministic golden fixtures, and measured
benchmarks. Do not modify firmware or write a device in this phase.

The initial device target is an **assumed** EEPROM A/B profile: two 1,792-byte
banks with 64-byte headers and 1,728 bytes of animation payload per bank. This is
arithmetic from the storage assessment, not a validated partition or public
hardware capacity. The current patch reservation has only 12 spare bytes, so no
frame or upload buffer is assumed to fit yet.

Default processing is lossless: exact RGB bytes, frame order, durations, and loop
boundaries. The assumed target timing quantum is 34 ms. Non-multiples are an
error by default and require the explicit `--timing round` conversion option.
No interpolation, color quantization, palette reduction, or frame interpolation
is allowed.

## Phase B: freeze capabilities and decoder

Only after the benchmark and round-trip evidence:

- Finalize the capability/storage query and exact usable capacity.
- Implement justified codecs with bounded incremental decoding.
- Compare device output against reference output, including loop restart and
  finite end behavior.
- Measure worst-case decode time, actual-MSP stack use, reserved RAM, and
  instruction-limit failures.

Open questions: exact timing behavior, buffer ownership, ROM/USB stack bound,
and whether every candidate codec earns its firmware size.

## Phase C: transactional upload and storage

- Upload only the inactive bank; validate the complete image and readback before
  changing its generation.
- Preserve the old valid bank on truncation, corruption, disconnect, or failed
  commit. Coordinate profile references and generations.
- Define retry/abort/reboot behavior and test interruption at every write.
- Re-query actual capabilities before any write and refuse unsupported codecs or
  oversized payloads before the first EEPROM operation.

The 0x180..0xfbf region remains proposed until its ownership is validated.
Upper flash is out of scope until upgrade preservation, erase bounds, migration,
and interrupted-write recovery are implemented and tested.

## Phase D: hardware validation

Verify actual timing, finite ends, loop boundaries, stock-driver burst takeover,
brightness, reconnect, suspend/resume, power loss, installed-data identity, and
firmware-upgrade preservation. Emulator results are not hardware validation.

## Brightness addendum results

The offline implementation now supports independent zone envelopes, fractional
16-bit brightness, base-color palettes, adjacency/lit-limit validation, and a
deterministic fireflies generator. Existing frame/dictionary/delta codecs are
preserved as the baked fallback.

Measured example: two base colors and 110 rendered colors require 110 bytes in
the envelope codec versus 1,369 bytes for the smallest baked codec. A generated
six-track fireflies document requires 296 bytes versus 1,226 bytes baked.
These results justify taking the envelope candidate into the Phase B decoder
review, not implementing it blindly in firmware.

Phases A–C are implemented: the firmware supports all five codecs, transactional
EEPROM upload, and RAM-cached envelope playback with explicit resource limits.
Phase D has targeted hardware results for installation, power-loss restoration,
and responsive four-zone fireflies. Upper flash remains disabled. Physical
adjacency, electrical timing, and every lifecycle path remain unproven; see
`custom-animation-validation.md` for the current evidence boundary.
