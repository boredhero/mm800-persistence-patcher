# Hardware test results

The following results were observed by one maintainer on one MM800 RGB
Polaris, USB `1b1c:1b3b`, on 2026-11-08. They are not a guarantee for other
units, revisions, hosts, or firmware versions.

## Verified during development

- Full 128 KiB backup obtained through read-only ISP mode.
- Original full backup restored and matched byte-for-byte after writing.
- Candidate full ISP writes matched their intended hashes on readback.
- Static `102030` survived power loss and moving to another computer.
- All 15 zones could have independent RGB values; a multicolor profile using
  eight colors was saved and verified.
- Stock brightness level 0 turned the lights off; level 3 restored output.
- Persistent level 0 survived power loss.
- Live levels 1 and 2 worked as distinct integer driver levels.
- A multicolor profile was saved and verified at brightness level 2.
- Part ID `0x00007c40` and ROM version `7.2` were returned by the device.

The exact final working candidate hash must be recorded with any release. Do
not assume that changing source, toolchain, or a hook leaves these results
applicable. Run the full gate again for each release candidate.

## Recovery

The original full backup was restored using the Linux in-place
`nocreat,notrunc,fsync` procedure and verified. Earlier delete-and-copy
attempts failed, so that method must not be used on this host.

## Remaining limitations

- These hardware results apply to the earlier static-only firmware. Animation
  persistence has offline CPU-test coverage only and has not been hardware-tested.
- Testing used one physical MM800 and a small number of power cycles.
- USB ROM internals and worst-case interrupt/stack behavior are not fully
  modeled.
- No claim is made for other firmware versions or universal recovery.
