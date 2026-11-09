import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_FRAMES = 4096
MAX_TIMELINE = 65536
MAX_COLORS = 4096
MAX_DURATION = (1 << 63) - 1
MAX_TICKS = 0xFFFFFFFF
DEFAULT_BUDGET = 1728
TIMING_QUANTUM = 34
CODECS = ("dictionary-raw", "dictionary-palette", "delta-raw", "delta-palette")


class ValidationError(ValueError):
    pass


class CodecUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    frame: int
    duration: int


@dataclass
class CanonicalAnimation:
    frames: list
    entries: list
    palette: list
    loop: bool
    end: str
    warnings: list
    original_entries: int
    total_before: int
    total_after: int
    envelope: object = None


@dataclass
class Candidate:
    name: str
    data: bytes | None
    reason: str | None


@dataclass
class Compilation:
    selected: str
    data: bytes
    candidates: list
    smallest: str
    excess: int


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def parse_color(value):
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ValidationError(f"invalid RGB color {value!r}; expected #RRGGBB")
    try:
        return bytes.fromhex(value[1:])
    except ValueError as error:
        raise ValidationError(f"invalid RGB color {value!r}; expected #RRGGBB") from error


def color_hex(rgb):
    return "#" + rgb.hex()


def load_document(path):
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValidationError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        document = json.loads(path.read_text(), object_pairs_hook=unique_object)
    except json.JSONDecodeError as error:
        raise ValidationError(f"invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ValidationError("root must be a JSON object")
    allowed = {"version", "strict_palette", "loop", "end", "palette", "frames", "timeline"}
    unknown = set(document) - allowed
    if unknown:
        raise ValidationError(f"unknown root fields: {', '.join(sorted(unknown))}")
    if document.get("version") != 1 or isinstance(document.get("version"), bool):
        raise ValidationError("version must be integer 1")
    strict = document.get("strict_palette", False)
    loop = document.get("loop", False)
    if not isinstance(strict, bool) or not isinstance(loop, bool):
        raise ValidationError("strict_palette and loop must be booleans")
    end = document.get("end", "hold")
    if end not in ("hold", "off"):
        raise ValidationError("end must be 'hold' or 'off'")
    if loop and end == "off":
        raise ValidationError("end=off is only meaningful for finite animations")
    palette_declaration = document.get("palette")
    if palette_declaration is not None and not isinstance(palette_declaration, dict):
        raise ValidationError("palette must be an object")
    if strict and palette_declaration is None:
        raise ValidationError("strict_palette=true requires a declared palette")
    palette = {}
    for name, value in (palette_declaration or {}).items():
        if not isinstance(name, str) or not name:
            raise ValidationError("palette names must be nonempty strings")
        palette[name] = parse_color(value)
    declarations = document.get("frames")
    if not isinstance(declarations, dict) or not declarations:
        raise ValidationError("frames must be a nonempty object")
    if len(declarations) > MAX_FRAMES:
        raise ValidationError("too many frame declarations")
    frames = {}
    for name, declaration in declarations.items():
        if not isinstance(name, str) or not name or not isinstance(declaration, dict):
            raise ValidationError("frame names must be nonempty strings with object values")
        if set(declaration) not in ({"fill"}, {"zones"}):
            raise ValidationError(f"frame {name} must contain exactly fill or zones")
        if "fill" in declaration:
            frames[name] = declaration["fill"]
        else:
            zones = declaration["zones"]
            if not isinstance(zones, list) or len(zones) != 15:
                raise ValidationError(f"frame {name} must contain exactly 15 zones")
            frames[name] = zones
    timeline = document.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise ValidationError("timeline must be a nonempty array")
    if len(timeline) > MAX_TIMELINE:
        raise ValidationError("too many timeline entries")
    references = []
    total = 0
    for index, entry in enumerate(timeline):
        if not isinstance(entry, dict) or set(entry) != {"frame", "duration_ms"}:
            raise ValidationError(f"timeline[{index}] must contain frame and duration_ms")
        name = entry["frame"]
        if name not in frames:
            raise ValidationError(f"timeline[{index}] references unknown frame {name!r}")
        duration = entry["duration_ms"]
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ValidationError(f"timeline[{index}] duration must be a positive integer")
        if total + duration > MAX_DURATION:
            raise ValidationError("total duration exceeds the supported integer bound")
        total += duration
        references.append((name, duration))
    return frames, palette, references, strict, loop, end


def optimize_document(document, timing="exact", quantum=TIMING_QUANTUM):
    frames, declared_palette, references, strict, loop, end = document
    if timing not in ("exact", "round"):
        raise ValidationError("timing must be 'exact' or 'round'")
    resolved = []
    used_colors = set()
    occurrences = {}
    for name, duration in references:
        declaration = frames[name]
        if isinstance(declaration, list):
            zones = []
            for zone, value in enumerate(declaration):
                if isinstance(value, str) and value in declared_palette:
                    rgb = declared_palette[value]
                else:
                    rgb = parse_color(value)
                zones.append(rgb)
                used_colors.add(rgb)
                if declared_palette and rgb not in declared_palette.values():
                    occurrences.setdefault(rgb, []).append(f"{name}/zone{zone}")
            resolved.append((tuple(zones), duration))
        else:
            value = declaration
            rgb = declared_palette[value] if isinstance(value, str) and value in declared_palette else parse_color(value)
            zones = tuple([rgb] * 15)
            used_colors.add(rgb)
            if declared_palette and rgb not in declared_palette.values():
                occurrences.setdefault(rgb, []).append(f"{name}/fill")
            resolved.append((zones, duration))
    if len(used_colors) > MAX_COLORS:
        raise ValidationError("too many distinct colors")
    if strict and occurrences:
        details = "; ".join(f"{color_hex(rgb)} at {', '.join(locations[:3])}" for rgb, locations in occurrences.items())
        raise ValidationError(f"colors outside strict palette: {details}")
    warnings = [
        {"color": color_hex(rgb), "count": len(locations), "locations": locations[:3]}
        for rgb, locations in occurrences.items()
    ]
    unique_frames = []
    frame_ids = {}
    merged = []
    for zones, duration in resolved:
        key = bytes().join(zones)
        if key not in frame_ids:
            frame_ids[key] = len(unique_frames)
            unique_frames.append(key)
        frame_id = frame_ids[key]
        if merged and merged[-1].frame == frame_id:
            previous = merged[-1]
            merged[-1] = Entry(frame_id, previous.duration + duration)
        else:
            merged.append(Entry(frame_id, duration))
    palette = []
    for zones, _ in resolved:
        for rgb in zones:
            if rgb not in palette:
                palette.append(rgb)
    entries = []
    for entry in merged:
        if entry.duration % quantum and timing == "exact":
            raise ValidationError(
                f"duration {entry.duration} ms is not representable in {quantum} ms ticks; "
                f"use --timing round to explicitly convert it"
            )
        ticks = entry.duration if timing == "exact" else max(1, (entry.duration + quantum // 2) // quantum)
        if timing == "exact":
            ticks = entry.duration // quantum
        while ticks:
            part = min(ticks, MAX_TICKS)
            entries.append(Entry(entry.frame, part))
            ticks -= part
    total_after = sum(entry.duration * quantum for entry in entries)
    return CanonicalAnimation(
        frames=unique_frames,
        entries=entries,
        palette=palette,
        loop=loop,
        end=end,
        warnings=warnings,
        original_entries=len(references),
        total_before=sum(duration for _, duration in references),
        total_after=total_after,
    )


def palette_width(palette):
    count = len(palette)
    if count <= 16:
        return 4
    if count <= 256:
        return 8
    raise CodecUnavailable(f"{count} colors exceed the 256-color palette limit")


def pack_indices(indices, width):
    if width == 8:
        return bytes(indices)
    result = bytearray()
    for index in range(0, len(indices), 2):
        value = indices[index]
        if index + 1 < len(indices):
            value |= indices[index + 1] << 4
        result.append(value)
    return bytes(result)


def encode_header(codec, flags, width, palette, frame_count, timeline_count, initial, frame_bytes, timeline_bytes, total_size, reserved=0):
    header = bytearray(struct.pack(
        "<4sBBBB10HI", b"MM8A", 1, codec, flags, width, 32, total_size,
        len(palette) // 3, frame_count, timeline_count, initial, len(palette),
        frame_bytes, timeline_bytes, reserved, 0,
    ))
    return header


def finish_binary(codec, flags, width, palette, frames, timeline, frame_count, initial, timeline_count, reserved=0):
    total = 32 + len(palette) + len(frames) + len(timeline)
    if total > 0xFFFF or not timeline:
        raise CodecUnavailable("binary size or timeline count exceeds the format bounds")
    header = encode_header(codec, flags, width, palette, frame_count, timeline_count, initial, len(frames), len(timeline), total, reserved)
    binary = header + palette + frames + timeline
    struct.pack_into("<I", binary, 28, zlib.crc32(binary))
    return bytes(binary)


def encode_dictionary(animation, use_palette):
    if len(animation.entries) > 0xFFFF or any(entry.duration > MAX_TICKS for entry in animation.entries):
        raise CodecUnavailable("timeline count or duration exceeds the format bounds")
    width = palette_width(animation.palette) if use_palette else 0
    palette = animation.palette if use_palette else []
    palette_bytes = b"".join(palette)
    indices = {rgb: index for index, rgb in enumerate(palette)}
    frames = bytearray()
    for frame in animation.frames:
        if use_palette:
            zones = [frame[index:index + 3] for index in range(0, 45, 3)]
            frame_indices = []
            for zone in range(15):
                rgb = zones[zone]
                if rgb not in indices:
                    raise CodecUnavailable("frame references a color outside the palette")
                frame_indices.append(indices[rgb])
            frames.extend(pack_indices(frame_indices, width))
        else:
            frames.extend(frame)
    timeline = bytearray()
    for entry in animation.entries:
        timeline.extend(struct.pack("<HI", entry.frame, entry.duration))
    flags = int(animation.loop) | (0 if animation.loop and animation.end == "hold" else (2 if animation.end == "off" else 0))
    return finish_binary(1, flags, width, palette_bytes, bytes(frames), bytes(timeline), len(animation.frames), animation.entries[0].frame, len(animation.entries))


def encode_delta(animation, use_palette):
    if len(animation.entries) > 0xFFFF or any(entry.duration > MAX_TICKS for entry in animation.entries):
        raise CodecUnavailable("delta record count or duration exceeds the format bounds")
    width = palette_width(animation.palette) if use_palette else 0
    palette = animation.palette if use_palette else []
    palette_bytes = b"".join(palette)
    indices = {rgb: index for index, rgb in enumerate(palette)}
    previous = bytes(45)
    timeline = bytearray()
    for entry_index, entry in enumerate(animation.entries):
        frame = animation.frames[entry.frame]
        zones = [frame[index:index + 3] for index in range(0, 45, 3)]
        changed = [index for index in range(15) if entry_index == 0 or zones[index] != previous[index]]
        if use_palette:
            full = pack_indices([indices[rgb] for rgb in zones], width)
            replacement = pack_indices([indices[zones[index]] for index in changed], width)
            delta_size = 8 + len(replacement)
            if entry_index and delta_size < 5 + len(full):
                timeline.extend(struct.pack("<BIHB", 3, entry.duration, sum(1 << index for index in changed), len(changed)))
                timeline.extend(replacement)
            else:
                timeline.extend(struct.pack("<BI", 2, entry.duration))
                timeline.extend(full)
        else:
            replacement = b"".join(zones[index] for index in changed)
            if entry_index and 8 + len(replacement) < 50:
                timeline.extend(struct.pack("<BIHB", 1, entry.duration, sum(1 << index for index in changed), len(changed)))
                timeline.extend(replacement)
            else:
                timeline.extend(struct.pack("<BI", 0, entry.duration))
                timeline.extend(frame)
        previous = zones
    flags = int(animation.loop) | (0 if animation.loop and animation.end == "hold" else (2 if animation.end == "off" else 0))
    return finish_binary(2, flags, width, palette_bytes, b"", bytes(timeline), 0, 0, len(animation.entries))


def encode_candidate(animation, name):
    if name == "dictionary-raw":
        return encode_dictionary(animation, False)
    if name == "dictionary-palette":
        return encode_dictionary(animation, True)
    if name == "delta-raw":
        return encode_delta(animation, False)
    if name == "delta-palette":
        return encode_delta(animation, True)
    raise CodecUnavailable(f"unknown codec {name}")


def compile_animation(animation, encoding="auto", budget=DEFAULT_BUDGET):
    if encoding != "auto" and encoding not in CODECS:
        raise CodecUnavailable(f"unknown codec {encoding}; choose auto or {', '.join(CODECS)}")
    names = CODECS if encoding == "auto" else (encoding,)
    candidates = []
    for name in names:
        try:
            data = encode_candidate(animation, name)
            if len(data) > budget:
                candidates.append(Candidate(name, None, f"requires {len(data)} bytes, {len(data) - budget} over the {budget}-byte budget"))
            else:
                candidates.append(Candidate(name, data, None))
        except CodecUnavailable as error:
            candidates.append(Candidate(name, None, str(error)))
    available = [candidate for candidate in candidates if candidate.data is not None]
    if not available:
        smallest = None
        for name in CODECS:
            try:
                data = encode_candidate(animation, name)
                if smallest is None or len(data) < smallest[1]:
                    smallest = (name, len(data))
            except CodecUnavailable:
                pass
        if smallest is None:
            raise CodecUnavailable("no supported encoding can represent this animation")
        raise CodecUnavailable(
            f"no encoding fits the {budget}-byte budget; smallest is {smallest[0]} at {smallest[1]} bytes, "
            f"exceeding it by {smallest[1] - budget} bytes; reduce unique colors, frames, or timeline entries"
        )
    selected = available[0] if encoding != "auto" else min(available, key=lambda candidate: (len(candidate.data), CODECS.index(candidate.name)))
    return Compilation(selected.name, selected.data, candidates, selected.name, 0)


def decode_header(data):
    if len(data) < 32:
        raise ValidationError("truncated header")
    fields = struct.unpack_from("<4sBBBB10HI", data)
    (magic, version, codec, flags, width, header_size, total_size, palette_count,
     frame_count, timeline_count, initial, palette_bytes, frame_bytes, timeline_bytes, reserved, checksum) = fields
    if magic != b"MM8A" or version != 1 or codec not in (1, 2, 3):
        raise ValidationError("unknown animation magic, version, or codec")
    if header_size != 32 or total_size != len(data):
        raise ValidationError("inconsistent header or total size")
    if flags & ~3 or (codec != 3 and reserved) or (flags & 1 and flags & 2):
        raise ValidationError("invalid flags or reserved values")
    verification = bytearray(data)
    struct.pack_into("<I", verification, 28, 0)
    if zlib.crc32(verification) != checksum:
        raise ValidationError("CRC-32 mismatch")
    if width not in (0, 4, 8) or (width == 0 and palette_count) or (width and not palette_count):
        raise ValidationError("invalid palette width/count")
    if width == 4 and palette_count > 16 or width == 8 and palette_count > 256:
        raise ValidationError("palette count exceeds index width")
    if palette_bytes != palette_count * 3 or 32 + palette_bytes + frame_bytes + timeline_bytes != len(data):
        raise ValidationError("inconsistent section sizes")
    if codec == 2 and (frame_count or initial):
        raise ValidationError("delta format has a nonzero reserved frame field")
    return codec, flags, width, palette_count, frame_count, timeline_count, initial, palette_bytes, frame_bytes, timeline_bytes, reserved


def decode_palette(data, width, count):
    palette = [data[index:index + 3] for index in range(0, len(data), 3)]
    if len(palette) != count:
        raise ValidationError("truncated palette")
    return palette


def unpack_indices(data, width, count):
    if width == 8:
        if len(data) != count:
            raise ValidationError("incorrect 8-bit index payload length")
        return list(data)
    expected = (count + 1) // 2
    if len(data) != expected:
        raise ValidationError("incorrect 4-bit index payload length")
    result = []
    for value in data:
        result.extend((value & 0x0F, value >> 4))
    result = result[:count]
    if count % 2 and data[-1] & 0xF0:
        raise ValidationError("nonzero high nibble in final 4-bit index")
    return result


def validate_indices(indices, palette):
    if any(index >= len(palette) for index in indices):
        raise ValidationError("palette index out of bounds")
    return [palette[index] for index in indices]


def decode_animation(data):
    (codec, flags, width, palette_count, frame_count, timeline_count, initial,
     palette_bytes, frame_bytes, timeline_bytes, reserved) = decode_header(data)
    if codec == 3:
        from animation_brightness import decode_envelope
        return decode_envelope(data)
    palette_data = data[32:32 + palette_bytes]
    palette = decode_palette(palette_data, width, palette_count) if palette_count else []
    timeline_offset = 32 + palette_bytes + frame_bytes
    timeline_data = data[timeline_offset:timeline_offset + timeline_bytes]
    entries = []
    if codec == 1:
        if not frame_count or not timeline_count:
            raise ValidationError("empty dictionary or timeline")
        if frame_bytes % (45 if width == 0 else (8 if width == 4 else 15)):
            raise ValidationError("inconsistent dictionary frame size")
        if frame_bytes // (45 if width == 0 else (8 if width == 4 else 15)) != frame_count:
            raise ValidationError("dictionary frame count/size mismatch")
        if timeline_bytes != timeline_count * 6:
            raise ValidationError("dictionary timeline size mismatch")
        frames = []
        stride = frame_bytes // frame_count
        for index in range(frame_count):
            raw = data[32 + palette_bytes + index * stride:32 + palette_bytes + (index + 1) * stride]
            if width == 0:
                frames.append(raw)
            else:
                indices = unpack_indices(raw, width, 15)
                frames.append(b"".join(validate_indices(indices, palette)))
        for index in range(timeline_count):
            frame_id, duration = struct.unpack_from("<HI", timeline_data, index * 6)
            if frame_id >= frame_count or not duration:
                raise ValidationError("invalid dictionary frame ID or zero duration")
            entries.append(Entry(frame_id, duration))
        if entries[0].frame != initial:
            raise ValidationError("initial frame does not match the first timeline entry")
        return frames, entries, bool(flags & 1), "off" if flags & 2 else "hold"
    if not timeline_count:
        raise ValidationError("empty delta sequence")
    frames = []
    previous = bytes(45)
    offset = 0
    for record in range(timeline_count):
        if offset + 5 > len(timeline_data):
            raise ValidationError("truncated delta record")
        kind, duration = struct.unpack_from("<BI", timeline_data, offset)
        if not duration:
            raise ValidationError("zero delta duration")
        offset += 5
        if kind in (0, 2):
            stride = 45 if kind == 0 else (8 if width == 4 else 15)
            if (kind == 0) != (width == 0):
                raise ValidationError("full-frame codec/index-width mismatch")
            if offset + stride > len(timeline_data):
                raise ValidationError("truncated complete frame")
            raw = timeline_data[offset:offset + stride]
            offset += stride
            zones = [raw[index:index + 3] for index in range(0, 45, 3)] if kind == 0 else validate_indices(unpack_indices(raw, width, 15), palette)
        elif kind in (1, 3):
            if (kind == 1) != (width == 0):
                raise ValidationError("delta codec/index-width mismatch")
            if offset + 3 > len(timeline_data):
                raise ValidationError("truncated delta mask")
            mask, count = struct.unpack_from("<HB", timeline_data, offset)
            offset += 3
            if mask & 0x8000 or count != mask.bit_count() or (record == 0):
                raise ValidationError("invalid delta mask or initial delta record")
            replacement_count = count if width == 8 else (count + 1) // 2
            stride = count * 3 if width == 0 else replacement_count
            if offset + stride > len(timeline_data):
                raise ValidationError("truncated delta replacements")
            raw = timeline_data[offset:offset + stride]
            offset += stride
            replacements = [raw[index:index + 3] for index in range(0, len(raw), 3)] if width == 0 else validate_indices(unpack_indices(raw, width, count), palette)
            zones = list(previous)
            for index in range(15):
                if mask & (1 << index):
                    zones[index] = replacements.pop(0)
        else:
            raise ValidationError("unknown delta record kind")
        if record == 0 and kind not in (0, 2):
            raise ValidationError("delta sequence must start with a complete frame")
        frames.append(b"".join(zones))
        entries.append(Entry(len(frames) - 1, duration))
        previous = zones
    if offset != len(timeline_data):
        raise ValidationError("trailing bytes in delta timeline")
    return frames, entries, bool(flags & 1), "off" if flags & 2 else "hold"


def decoded_rgb_timeline(animation, frames, entries):
    return [(frames[entry.frame], entry.duration) for entry in entries]
