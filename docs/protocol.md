# Protocol and profile format

## Stock RGB and brightness

Normal live color uses `07 22 0f 00` followed by 45 bytes: R,G,B for each of
15 zones. The stock brightness command is separate. Live levels are 0–8 and
persistent levels are 0–3. These are integer driver levels, not percentages.

The renderer applies channel factors and the stock 750/1000 intensity cap.
That cap is not a user brightness parameter and is not raised by this project.

## Added profile commands

- `07 23`: save the current 45-byte RGB buffer. Normal RGB commands never
  write EEPROM.
- `0e 23`: return validity and the newest valid saved RGB profile.
- `0e 24`: read-only EEPROM access in chunks of at most 56 bytes.
- `0e 60`: return the 64-byte embedded build record.

GET24 also has a chip-info subcommand, `0e 24 ff ff 00`, returning part ID,
ROM version, and UID without writing EEPROM.

## A/B record

Each slot is 64 bytes. Slots A and B are at EEPROM offsets `0x100` and `0x140`.
The layout is:

- `0..3`: magic `MM8L`
- `4..7`: format version 1, little-endian
- `8..11`: RGB length 45, little-endian
- `12..56`: 45 RGB bytes
- `57..59`: 24-bit little-endian sequence number
- `60..63`: CRC-32 over bytes 0–59

The newest valid record wins. A corrupt newest record falls back to the older
valid record. Save aborts if either slot cannot be read, avoiding the case
where a temporary read failure makes the only valid profile appear empty.

A completed write is read back and checked. SET23 alone does not prove that
the intended profile was saved; clients must compare all 45 returned bytes.

The current record stores static RGB only, not animation metadata.
