import json
import random
import struct
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from custom_animation import (
    CODECS, MAX_DURATION, MAX_INPUT_BYTES, MAX_TICKS, TIMING_QUANTUM, Candidate, CodecUnavailable,
    Compilation, ValidationError, color_hex, decode_header, encode_candidate,
    finish_binary, load_document, optimize_document, parse_color, unique_object,
)

GAIN_MAX = 65535
GAIN_SCALE = GAIN_MAX * GAIN_MAX
ENVELOPE_CODEC = "brightness-envelope"
ALL_CODECS = (*CODECS, ENVELOPE_CODEC)


@dataclass(frozen=True)
class Track:
    zone: int
    color: bytes
    interpolation: str
    keyframes: tuple


@dataclass
class TrackModel:
    duration: int
    tracks: list
    global_gain: int
    strict_palette: bool
    declared_palette: dict
    loop: bool
    end: str
    adjacency: list
    max_lit_zones: int | None


def parse_brightness(value):
    if isinstance(value, bool):
        raise ValidationError("brightness must be a finite number in [0, 1]")
    try:
        number = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValidationError("brightness must be a finite number in [0, 1]") from error
    if not number.is_finite() or number < 0 or number > 1:
        raise ValidationError("brightness must be a finite number in [0, 1]")
    return int((number * GAIN_MAX).to_integral_value(rounding=ROUND_HALF_UP))


def brightness_text(gain):
    return str((Decimal(gain) / GAIN_MAX).normalize())


def render_channel(base, zone_gain, global_gain=GAIN_MAX):
    numerator = base * zone_gain * global_gain
    return min(255, (numerator + GAIN_SCALE // 2) // GAIN_SCALE)


def render_frame(base_frame, zone_gains, global_gain=GAIN_MAX):
    return bytes(render_channel(channel, zone_gains[index // 3], global_gain) for index, channel in enumerate(base_frame))


def stock_render(frame):
    factors = (255, 170, 120)
    output = bytearray()
    for index, channel in enumerate(frame):
        output.append((channel * factors[index % 3] // 255) * 750 // 1000)
    return bytes(output)


def parse_adjacency(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("adjacency must be an array of zone pairs")
    result = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValidationError("each adjacency entry must contain two zones")
        a, b = pair
        if any(isinstance(zone, bool) or not isinstance(zone, int) or not 0 <= zone < 15 for zone in pair):
            raise ValidationError("adjacency zones must be integers from 0 through 14")
        if a == b:
            raise ValidationError("a zone cannot be adjacent to itself")
        edge = tuple(sorted((a, b)))
        if edge in result:
            raise ValidationError("duplicate adjacency edge")
        result.append(edge)
    return result


def resolve_base_color(value, declared_palette):
    return declared_palette[value] if isinstance(value, str) and value in declared_palette else parse_color(value)


def load_track_model(document):
    allowed = {"version", "name", "duration_ms", "loop", "end", "brightness", "strict_palette", "palette", "tracks", "adjacency", "max_lit_zones"}
    unknown = set(document) - allowed
    if unknown:
        raise ValidationError(f"unknown track-document fields: {', '.join(sorted(unknown))}")
    if document.get("version") != 1 or isinstance(document.get("version"), bool):
        raise ValidationError("version must be integer 1")
    duration = document.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0 or duration > MAX_DURATION:
        raise ValidationError("duration_ms must be a positive bounded integer")
    loop = document.get("loop", False)
    if not isinstance(loop, bool):
        raise ValidationError("loop must be a boolean")
    end = document.get("end", "hold")
    if end not in ("hold", "off") or (loop and end == "off"):
        raise ValidationError("end must be hold or off; off is finite-only")
    global_gain = parse_brightness(document.get("brightness", 1))
    strict = document.get("strict_palette", False)
    if not isinstance(strict, bool):
        raise ValidationError("strict_palette must be a boolean")
    declared = document.get("palette", {})
    if not isinstance(declared, dict):
        raise ValidationError("palette must be an object")
    if strict and not declared:
        raise ValidationError("strict_palette=true requires a declared palette")
    palette = {name: parse_color(value) for name, value in declared.items()}
    max_lit = document.get("max_lit_zones")
    if max_lit is not None and (isinstance(max_lit, bool) or not isinstance(max_lit, int) or not 0 <= max_lit <= 15):
        raise ValidationError("max_lit_zones must be an integer from 0 through 15")
    declarations = document.get("tracks")
    if not isinstance(declarations, list) or not declarations:
        raise ValidationError("tracks must be a nonempty array")
    tracks = []
    used_zones = set()
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) - {"zone", "color", "interpolation", "keyframes"}:
            raise ValidationError("invalid track fields")
        zone = declaration.get("zone")
        if isinstance(zone, bool) or not isinstance(zone, int) or not 0 <= zone < 15:
            raise ValidationError("track zone must be an integer from 0 through 14")
        if zone in used_zones:
            raise ValidationError(f"duplicate track for zone {zone}")
        used_zones.add(zone)
        color = resolve_base_color(declaration.get("color"), palette)
        interpolation = declaration.get("interpolation", "linear")
        if interpolation not in ("hold", "linear"):
            raise ValidationError("interpolation must be hold or linear")
        keyframes = declaration.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            raise ValidationError("track keyframes must be a nonempty array")
        parsed = []
        previous_time = -1
        for keyframe in keyframes:
            if not isinstance(keyframe, dict) or set(keyframe) != {"time_ms", "brightness"}:
                raise ValidationError("keyframes require time_ms and brightness")
            time_ms = keyframe["time_ms"]
            if isinstance(time_ms, bool) or not isinstance(time_ms, int) or not 0 <= time_ms <= duration:
                raise ValidationError("keyframe time is outside the track duration")
            if time_ms <= previous_time:
                raise ValidationError("keyframe times must be strictly increasing")
            previous_time = time_ms
            parsed.append((time_ms, parse_brightness(keyframe["brightness"])))
        if parsed[0][0] != 0 or parsed[-1][0] != duration:
            raise ValidationError("keyframes must start at 0 and end at duration_ms")
        tracks.append(Track(zone, color, interpolation, tuple(parsed)))
    return TrackModel(duration, tracks, global_gain, strict, palette, loop, end, parse_adjacency(document.get("adjacency")), max_lit)


def load_animation_document(path):
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValidationError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    text = path.read_text()
    document = json.loads(text, object_pairs_hook=unique_object, parse_float=Decimal)
    if isinstance(document, dict) and "tracks" in document:
        return load_track_model(document)
    return load_document(path)


def gain_at(track, time_ms):
    keyframes = track.keyframes
    for index in range(len(keyframes) - 1):
        start_time, start_gain = keyframes[index]
        end_time, end_gain = keyframes[index + 1]
        if start_time <= time_ms <= end_time:
            if time_ms == end_time:
                return end_gain
            if track.interpolation == "hold" or time_ms == start_time:
                return start_gain
            fraction = Decimal(time_ms - start_time) / (end_time - start_time)
            return int((Decimal(start_gain) + Decimal(end_gain - start_gain) * fraction).to_integral_value(rounding=ROUND_HALF_UP))
    return keyframes[-1][1]


def render_envelope_tick(duration, tracks, global_gain, time_ms):
    output = bytearray(45)
    for track in tracks:
        gain = gain_at(track, time_ms)
        for channel in range(3):
            output[track.zone * 3 + channel] = render_channel(track.color[channel], gain, global_gain)
    return bytes(output)


def validate_constraints(frames, adjacency, max_lit_zones, loop):
    rendered = [stock_render(frame) for frame in frames]
    for index, frame in enumerate(rendered):
        lit = {zone for zone in range(15) if any(frame[zone * 3:zone * 3 + 3])}
        if max_lit_zones is not None and len(lit) > max_lit_zones:
            raise ValidationError(f"more than {max_lit_zones} zones are lit at tick {index}")
        for a, b in adjacency:
            if a in lit and b in lit:
                raise ValidationError(f"adjacent zones {a} and {b} are both lit at tick {index}")
    if loop and len(rendered) > 1:
        first, last = rendered[0], rendered[-1]
        first_lit = {zone for zone in range(15) if any(first[zone * 3:zone * 3 + 3])}
        last_lit = {zone for zone in range(15) if any(last[zone * 3:zone * 3 + 3])}
        for a, b in adjacency:
            if (a in first_lit and b in last_lit) or (b in first_lit and a in last_lit):
                raise ValidationError(f"adjacent zones {a} and {b} overlap at the loop boundary")


def canonical_from_rendered(rendered, loop, end, envelope):
    frames = []
    frame_ids = {}
    entries = []
    palette = []
    from custom_animation import Entry
    for frame in rendered:
        if frame not in frame_ids:
            frame_ids[frame] = len(frames)
            frames.append(frame)
        frame_id = frame_ids[frame]
        if entries and entries[-1].frame == frame_id:
            entries[-1] = Entry(frame_id, entries[-1].duration + 1)
        else:
            entries.append(Entry(frame_id, 1))
        for index in range(0, 45, 3):
            color = frame[index:index + 3]
            if color not in palette:
                palette.append(color)
    from custom_animation import CanonicalAnimation
    total = len(rendered) * TIMING_QUANTUM
    return CanonicalAnimation(frames, entries, palette, loop, end, [], len(rendered), total, total, envelope)


def optimize_track_model(model):
    rendered = [render_envelope_tick(model.duration, model.tracks, model.global_gain, time_ms) for time_ms in range(0, model.duration, TIMING_QUANTUM)]
    validate_constraints(rendered, model.adjacency, model.max_lit_zones, model.loop)
    occurrences = {}
    for track in model.tracks:
        if model.declared_palette and track.color not in model.declared_palette.values():
            occurrences.setdefault(track.color, []).append(f"zone{track.zone}")
    if model.strict_palette and occurrences:
        raise ValidationError("base colors outside strict palette: " + ", ".join(color_hex(rgb) for rgb in occurrences))
    warnings = [{"color": color_hex(rgb), "count": len(locations), "locations": locations[:3]} for rgb, locations in occurrences.items()]
    base_palette = []
    for track in model.tracks:
        if track.color not in base_palette:
            base_palette.append(track.color)
    envelope = {
        "duration_ticks": model.duration // TIMING_QUANTUM,
        "base_palette": base_palette,
        "tracks": model.tracks,
        "global_gain": model.global_gain,
    }
    animation = canonical_from_rendered(rendered, model.loop, model.end, envelope)
    animation.warnings = warnings
    return animation


def convert_track_timing(model):
    def ticks(value):
        return int((Decimal(value) / TIMING_QUANTUM).to_integral_value(rounding=ROUND_HALF_UP)) * TIMING_QUANTUM
    duration = max(TIMING_QUANTUM, ticks(model.duration))
    tracks = []
    for track in model.tracks:
        keyframes = []
        for time_ms, gain in track.keyframes:
            converted = min(duration, max(0, ticks(time_ms)))
            if keyframes and keyframes[-1][0] == converted:
                keyframes[-1] = (converted, gain)
            else:
                keyframes.append((converted, gain))
        tracks.append(Track(track.zone, track.color, track.interpolation, tuple(keyframes)))
    return TrackModel(duration, tracks, model.global_gain, model.strict_palette, model.declared_palette, model.loop, model.end, model.adjacency, model.max_lit_zones)


def optimize_animation_document(document, timing="exact"):
    if isinstance(document, TrackModel):
        if timing == "round":
            document = convert_track_timing(document)
        if document.duration % TIMING_QUANTUM:
            raise ValidationError(f"track duration must be a multiple of {TIMING_QUANTUM} ms; use --timing round")
        return optimize_track_model(document)
    return optimize_document(document, timing=timing)


def encode_envelope(animation):
    envelope = animation.envelope
    if not envelope:
        raise CodecUnavailable("no brightness-envelope source tracks")
    from custom_animation import palette_width, pack_indices
    palette = envelope["base_palette"]
    width = palette_width(palette)
    indices = {rgb: index for index, rgb in enumerate(palette)}
    tracks = envelope["tracks"]
    duration_ticks = envelope["duration_ticks"]
    if not 0 < duration_ticks <= 0xFFFF:
        raise CodecUnavailable("envelope duration exceeds uint16 ticks")
    table = bytearray()
    keyframes = bytearray()
    keyframe_count = 0
    for track in tracks:
        count = len(track.keyframes)
        if count > 255 or keyframe_count + count > 0xFFFF:
            raise CodecUnavailable("too many envelope keyframes")
        table.extend(struct.pack("<BBBB", track.zone, indices[track.color], 1 if track.interpolation == "linear" else 0, count))
        table.extend(struct.pack("<H", keyframe_count))
        for time_ms, gain in track.keyframes:
            keyframes.extend(struct.pack("<IH", time_ms, gain))
        keyframe_count += count
    palette_bytes = b"".join(palette)
    flags = int(animation.loop) | (2 if animation.end == "off" else 0)
    return finish_binary(3, flags, width, palette_bytes, bytes(table), bytes(keyframes), len(tracks), duration_ticks, keyframe_count, envelope["global_gain"])


def decode_envelope(data):
    from custom_animation import decode_palette
    (codec, flags, width, palette_count, track_count, keyframe_count, duration_ticks,
     palette_bytes, table_bytes, keyframe_bytes, global_gain) = decode_header(data)
    if codec != 3 or not 0 < track_count <= 15 or not duration_ticks:
        raise ValidationError("invalid envelope codec, track count, or duration")
    if table_bytes != track_count * 6 or keyframe_bytes != keyframe_count * 6:
        raise ValidationError("inconsistent envelope section sizes")
    palette = decode_palette(data[32:32 + palette_bytes], width, palette_count)
    table = data[32 + palette_bytes:32 + palette_bytes + table_bytes]
    records = data[32 + palette_bytes + table_bytes:]
    tracks = []
    used_zones = set()
    offset = 0
    for index in range(track_count):
        zone, color_index, interpolation, count, first = struct.unpack_from("<BBBBH", table, index * 6)
        if zone >= 15 or zone in used_zones or color_index >= len(palette) or interpolation > 1 or not count or first != offset:
            raise ValidationError("invalid envelope track")
        used_zones.add(zone)
        parsed = []
        previous = -1
        for _ in range(count):
            time_ms, gain = struct.unpack_from("<IH", records, offset * 6)
            offset += 1
            if time_ms <= previous or time_ms > duration_ticks * TIMING_QUANTUM:
                raise ValidationError("noncanonical envelope keyframe times")
            previous_time = time_ms
            parsed.append((time_ms, gain))
        if parsed[0][0] != 0 or parsed[-1][0] != duration_ticks * TIMING_QUANTUM:
            raise ValidationError("envelope endpoints do not cover the animation")
        tracks.append(Track(zone, palette[color_index], "linear" if interpolation else "hold", tuple(parsed)))
    rendered = [render_envelope_tick(duration_ticks * TIMING_QUANTUM, tracks, global_gain, time_ms) for time_ms in range(0, duration_ticks * TIMING_QUANTUM, TIMING_QUANTUM)]
    canonical = canonical_from_rendered(rendered, bool(flags & 1), "off" if flags & 2 else "hold", None)
    return canonical.frames, canonical.entries, canonical.loop, canonical.end


def encode_brightness_candidate(animation, name):
    return encode_envelope(animation) if name == ENVELOPE_CODEC else encode_candidate(animation, name)


def compile_brightness(animation, encoding="auto", budget=1728):
    if encoding != "auto" and encoding not in ALL_CODECS:
        raise CodecUnavailable(f"unknown codec {encoding}")
    names = ALL_CODECS if encoding == "auto" else (encoding,)
    candidates = []
    for name in names:
        try:
            data = encode_brightness_candidate(animation, name)
            if len(data) > budget:
                candidates.append(Candidate(name, None, f"requires {len(data)} bytes, {len(data) - budget} over budget"))
            else:
                candidates.append(Candidate(name, data, None))
        except CodecUnavailable as error:
            candidates.append(Candidate(name, None, str(error)))
    available = [candidate for candidate in candidates if candidate.data is not None]
    if not available:
        smallest = None
        for name in ALL_CODECS:
            try:
                data = encode_brightness_candidate(animation, name)
                if smallest is None or len(data) < smallest[1]:
                    smallest = (name, len(data))
            except CodecUnavailable:
                pass
        if smallest is None:
            raise CodecUnavailable("no encoding can represent this animation")
        raise CodecUnavailable(f"no encoding fits; smallest={smallest[0]} bytes={smallest[1]} excess={smallest[1] - budget}")
    selected = available[0] if encoding != "auto" else min(available, key=lambda candidate: (len(candidate.data), ALL_CODECS.index(candidate.name)))
    return Compilation(selected.name, selected.data, candidates, selected.name, 0)


def generate_fireflies(seed, duration, palette, adjacency, max_lit, global_brightness, min_peak, max_peak):
    if duration <= 0 or duration % TIMING_QUANTUM:
        raise ValidationError("fireflies duration must be a positive multiple of 34 ms")
    randomizer = random.Random(seed)
    pulses = []
    for _ in range(2000):
        zone = randomizer.randrange(15)
        fade_in = randomizer.randrange(3, 13) * TIMING_QUANTUM
        hold = randomizer.randrange(0, 8) * TIMING_QUANTUM
        fade_out = randomizer.randrange(3, 13) * TIMING_QUANTUM
        idle = randomizer.randrange(2, 18) * TIMING_QUANTUM
        peak = min_peak + randomizer.random() * (max_peak - min_peak)
        start = randomizer.randrange(0, duration)
        end = start + fade_in + hold + fade_out
        if end > duration:
            continue
        conflict = False
        for other in pulses:
            other_start, other_end, other_zone, other_idle = other[3], other[4], other[0], other[7]
            overlap = start < other_end + other_idle and other_start < end + TIMING_QUANTUM
            if not overlap:
                continue
            if zone == other_zone or (zone, other_zone) in adjacency or (other_zone, zone) in adjacency:
                conflict = True
                break
            if max_lit == 1:
                conflict = True
                break
        if conflict:
            continue
        simultaneous = 1 + sum(start < other[4] and other[3] < end for other in pulses)
        if simultaneous > max_lit:
            continue
        pulses.append((zone, peak, fade_in, start, end, hold, fade_out, idle))
    pulses.sort(key=lambda pulse: pulse[3])
    grouped = {}
    for pulse in pulses:
        grouped.setdefault(pulse[0], []).append(pulse)
    tracks = []
    for zone in sorted(grouped):
        color_name = randomizer.choice(list(palette))
        keyframes = []
        for zone_pulse in grouped[zone]:
            _, peak, fade_in, start, end, hold, _, _ = zone_pulse
            for time_ms, brightness in [
                (0, 0.0), (start, 0.0), (start + fade_in, peak),
                (start + fade_in + hold, peak), (end, 0.0), (duration, 0.0),
            ]:
                if keyframes and keyframes[-1]["time_ms"] == time_ms:
                    keyframes[-1]["brightness"] = brightness
                else:
                    keyframes.append({"time_ms": time_ms, "brightness": brightness})
        keyframes.sort(key=lambda keyframe: keyframe["time_ms"])
        merged = []
        for keyframe in keyframes:
            if merged and merged[-1]["time_ms"] == keyframe["time_ms"]:
                merged[-1] = keyframe
            else:
                merged.append(keyframe)
        tracks.append({"zone": zone, "color": color_name, "interpolation": "linear", "keyframes": merged})
    if not tracks:
        raise ValidationError("no firefly pulses fit the requested duration and constraints")
    return tracks


def generate_firefly_document(seed, duration, palette, adjacency, max_lit, brightness, min_peak=0.1, max_peak=0.9):
    if not 0 <= min_peak <= max_peak <= 1:
        raise ValidationError("firefly peak range must be within [0, 1]")
    global_gain = parse_brightness(brightness)
    tracks = generate_fireflies(seed, duration, palette, adjacency, max_lit, global_gain, min_peak, max_peak)
    return {
        "version": 1,
        "name": "fireflies",
        "duration_ms": duration,
        "loop": True,
        "brightness": brightness,
        "strict_palette": True,
        "palette": palette,
        "adjacency": [list(edge) for edge in adjacency],
        "max_lit_zones": max_lit,
        "tracks": tracks,
    }
