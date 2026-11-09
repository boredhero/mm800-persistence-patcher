# Protocol and profile format

## Stock RGB and brightness

Normal live color uses `07 22 0f 00` followed by 45 bytes: R,G,B for each of
15 zones. The stock brightness command is separate. Live levels are 0–8 and
persistent levels are 0–3. These are integer driver levels, not percentages.
Existing static RGB packets, `07 23` static snapshot saves, and stock brightness
commands retain their behavior.

The renderer applies channel factors and the stock 750/1000 intensity cap.
That cap is not a user brightness parameter and is not raised by this project.

## Versioned animation capability and profile query

`0e 25` returns a 64-byte response. It is both the capability query and the
saved-profile query. Fields after byte 4 are:

- `4`: saved status: 0 none, 1 static, 2 animation, `0xfd` unsupported record,
  or `0xfe` read error.
- `5`: animation protocol version 1.
- `6`: capabilities `0x07`: static, animation preview, and verified save.
- `7`: runtime owner: 0 stock, 1 saved static, 2 saved animation, 3 host static,
  4 host animation. This is independent of saved-profile validity.
- `8..11`: saved kind, public effect ID, payload length, and flags.
- `12..56`: saved canonical payload, zero-padded.
- `57`: last save status; `0x7f` means no save attempted, `0x80` means queued
  or committing (`BUSY`), 0 means verified, and other values are failures.
- `58..60`: supported public effect IDs `10 20 30`.
- `61`: supported speed code 1.
- `62..63`: reserved zero.

`capabilities` fails closed if this versioned interface is absent. `get-profile`
prints the committed recipe and runtime owner without exposing EEPROM metadata.

## Animation preview and save

SET25 uses a complete 64-byte report:

| Bytes | Meaning |
|---|---|
| `0..1` | `07 25` |
| `2` | persistence selector: `00` preview, `f0` save |
| `3` | protocol version 1 |
| `4` | public effect ID |
| `5` | canonical payload length |
| `6` | flags, zero in version 1 |
| `7..` | canonical effect payload, then zero padding |

Preview and save accept byte-for-byte identical effect parameters. Only byte 2
changes. Validated requests are applied at the safe main-loop boundary, so a
USB interrupt cannot change ownership or effect objects underneath an active
animation poll. Effect/save requests use a four-slot FIFO. Ordinary stock RGB,
mode, suspend, resume, and configure traffic instead uses dedicated sequenced
slots: latest RGB and mode are coalesced without consuming that FIFO, and 32-bit
sequence numbers preserve their ordering against saves, effects, and lifecycle
events. GET22 returns the latest logically queued RGB value even before that
boundary. Effect/save overflow fails rather than being reported as committed.

Preview reconstructs the selected device-run effect without writing EEPROM.
Save applies that same recipe, commits it, and requires readback. The host polls
GET25 through `BUSY`, then compares the committed effect and payload. A USB write,
a queued request, or a matching current frame is not reported as a successful
save.

Public effect IDs are stable protocol values, not stock selector or constructor
IDs:

| Public ID | CLI name | Payload | Behavior |
|---|---|---|---|
| `0x10` | `breathing` | `01 R G B` | One-color breathing, speed code 1 |
| `0x20` | `rainbow` | `01` | Uniform rainbow, speed code 1 |
| `0x30` | `moving-rainbow` | `01 00` | Moving rainbow, speed code 1, stock direction 0 |

All other IDs, lengths, flags, speeds, directions, protocol versions, and nonzero
padding are rejected before effect RAM changes. The broken fast-breathing speed
0 preset is not exposed. Uploaded frame sequences and arbitrary streamed
animations are outside this protocol.

`release` sends the stock autonomous-mode command `07 04 01`. It changes runtime
ownership without erasing the saved profile. Deliberate RGB commands take host
static ownership without changing the saved animation; a later power cycle
restores the committed recipe.

Legacy `0e 23` returns status 1 and 45 RGB bytes for a static profile. For an
animation it returns status 2 and zero RGB bytes; clients must use GET25 rather
than mistaking an animation recipe for a static frame.

`0e 24` retains read-only EEPROM access in chunks of at most 56 bytes. Its
`0e 24 ff ff 00` subcommand returns part ID, ROM version, and UID. `0e 60`
returns the embedded build record used by the update checker.

## Internal A/B record and migration

Each internal slot remains 64 bytes with a 24-bit sequence at bytes 57–59 and
CRC-32 over bytes 0–59. V1 records remain readable as static RGB. New explicit
saves write V2 into the other slot; boot never migrates or rewrites EEPROM.

V2 replaces the V1 length word with kind, public effect ID, payload length, and
flags. Static V2 uses kind 0, effect 0, length 45. Animation V2 uses kind 1 and
one of the exact public payloads above. Unused payload bytes must be zero.
Recipes are stored as parameters, never rendered frames, RAM objects, pointers,
phase counters, or keyframe arrays.

The newest valid supported record wins across mixed V1/V2 slots. Corrupt newer
records fall back to the older valid record. Saves fail closed on either slot
read error, a CRC-valid unsupported/future record, write failure, or readback
mismatch. A failed save does not report the requested recipe as committed.
Unchanged V1-only firmware cannot restore V2 records; this downgrade boundary
is intentional and must not be hidden.

## Runtime scheduling

Static owners suppress effect generation while brightness and rendering remain
active. Animation owners reconstruct one stock effect layer, explicitly disable
the other, and allow normal effect, brightness, and render ticks. Configure and
resume reapply the owned recipe at the main-loop boundary after stock
housekeeping; resume does so only when the stock `context+0xed` condition is
nonzero. Suspend retains the recipe while stock brightness turns output off. No
magic stock lifecycle state is added.

Breathing and uniform rainbow use the stock counter reset. Moving rainbow is
reset every 87 ticks, an exact output-repeat boundary at speed 1. This avoids
the stock 32-bit `counter * 1000` overflow without changing the visible frame
sequence.
