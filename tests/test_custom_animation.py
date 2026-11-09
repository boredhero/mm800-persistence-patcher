import json
import random
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import custom_animation as codec

EXAMPLE = REPO / "tests" / "fixtures" / "custom_animation" / "example.json"
GOLDEN_DICTIONARY = "4d4d38410101010420005c0004000300040000000c0018001800000069f3858c8000ffff008000000012345600000000000000001111111111111101100221100221100300000f00000001000300000000000300000002003b000000"
GOLDEN_DELTA = "4d4d3841010201042000600004000000040000000c00000034000000a6d800178000ffff0080000000123456020f00000000000000000000000203000000111111111111110102030000000000000000000000023b0000001002211002211003"


def make_animation(frames, durations, loop=False, end="hold"):
    palette = []
    for frame in frames:
        for index in range(0, 45, 3):
            color = frame[index:index + 3]
            if color not in palette:
                palette.append(color)
    entries = [codec.Entry(index, duration) for index, duration in enumerate(durations)]
    total = sum(durations) * 34
    return codec.CanonicalAnimation(frames, entries, palette, loop, end, [], len(entries), total, total)


def round_trip(animation, name):
    data = codec.encode_candidate(animation, name)
    frames, entries, loop, end = codec.decode_animation(data)
    expected = [(animation.frames[entry.frame], entry.duration) for entry in animation.entries]
    actual = [(frames[entry.frame], entry.duration) for entry in entries]
    return data, actual == expected and loop == animation.loop and end == animation.end


def reseal(data):
    data = bytearray(data)
    struct.pack_into("<I", data, 28, 0)
    struct.pack_into("<I", data, 28, zlib.crc32(data))
    return bytes(data)


class OptimizerTests(unittest.TestCase):
    def test_example_exact_timing_and_explicit_rounding(self):
        with self.assertRaisesRegex(codec.ValidationError, "not representable"):
            codec.optimize_document(codec.load_document(EXAMPLE), timing="exact")
        animation = codec.optimize_document(codec.load_document(EXAMPLE), timing="round")
        self.assertEqual([entry.duration for entry in animation.entries], [15, 3, 3, 59])
        self.assertEqual(animation.total_before, 2700)
        self.assertEqual(animation.total_after, 2720)
        self.assertEqual(len(animation.warnings), 1)
        self.assertEqual(animation.warnings[0]["color"], "#123456")

    def test_merge_dedup_and_remove_unused(self):
        document = {
            "version": 1,
            "palette": {"a": "#010203", "unused": "#ffffff"},
            "frames": {
                "a": {"fill": "a"}, "b": {"fill": "#010203"},
                "c": {"fill": "#040506"}, "unused": {"fill": "#000000"},
            },
            "timeline": [
                {"frame": "a", "duration_ms": 34}, {"frame": "b", "duration_ms": 68},
                {"frame": "c", "duration_ms": 34}, {"frame": "a", "duration_ms": 34},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(document))
            animation = codec.optimize_document(codec.load_document(path))
        self.assertEqual(len(animation.frames), 2)
        self.assertEqual([entry.duration for entry in animation.entries], [3, 1, 1])
        self.assertEqual(animation.palette, [bytes.fromhex("010203"), bytes.fromhex("040506")])

    def test_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"version":1,"version":1,"frames":{},"timeline":[]}')
            with self.assertRaisesRegex(codec.ValidationError, "duplicate JSON"):
                codec.load_document(path)

    def test_strict_palette_and_discovery(self):
        document = json.loads(EXAMPLE.read_text())
        document["strict_palette"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "strict.json"
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(codec.ValidationError, "outside strict palette"):
                codec.optimize_document(codec.load_document(path))
            del document["palette"]
            document["strict_palette"] = False
            replacements = {"purple": "#8000ff", "pink": "#ff0080", "off": "#000000"}
            for frame in document["frames"].values():
                if "fill" in frame:
                    frame["fill"] = replacements[frame["fill"]]
                else:
                    frame["zones"] = [replacements.get(value, value) for value in frame["zones"]]
            path.write_text(json.dumps(document))
            animation = codec.optimize_document(codec.load_document(path), timing="round")
        self.assertEqual(animation.warnings, [])

    def test_duration_split_and_overflow(self):
        animation = make_animation([bytes.fromhex("010203") * 15], [codec.MAX_TICKS + 5])
        with self.assertRaises(codec.CodecUnavailable):
            codec.encode_candidate(animation, "dictionary-raw")
        animation.entries = [codec.Entry(0, codec.MAX_TICKS), codec.Entry(0, 5)]
        data, valid = round_trip(animation, "dictionary-raw")
        self.assertTrue(valid)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overflow.json"
            path.write_text(json.dumps({
                "version": 1, "frames": {"a": {"fill": "#000000"}},
                "timeline": [{"frame": "a", "duration_ms": codec.MAX_DURATION}, {"frame": "a", "duration_ms": 1}],
            }))
            with self.assertRaisesRegex(codec.ValidationError, "total duration"):
                codec.load_document(path)


class CodecTests(unittest.TestCase):
    def test_golden_binaries(self):
        animation = codec.optimize_document(codec.load_document(EXAMPLE), timing="round")
        self.assertEqual(codec.encode_candidate(animation, "dictionary-palette").hex(), GOLDEN_DICTIONARY)
        self.assertEqual(codec.encode_candidate(animation, "delta-palette").hex(), GOLDEN_DELTA)

    def test_all_codecs_round_trip(self):
        red = bytes.fromhex("ff0000") * 15
        blue = bytes.fromhex("0000ff") * 15
        mixed = bytes.fromhex("ff0000") + bytes.fromhex("0000ff") * 14
        animation = make_animation([red, blue, mixed, red], [1, 2, 3, 4], loop=True)
        for name in codec.CODECS:
            with self.subTest(codec=name):
                _, valid = round_trip(animation, name)
                self.assertTrue(valid)

    def test_random_frames_round_trip(self):
        randomizer = random.Random(800)
        frames = [bytes(randomizer.randrange(256) for _ in range(45)) for _ in range(12)]
        animation = make_animation(frames, list(range(1, 13)))
        for name in codec.CODECS:
            with self.subTest(codec=name):
                _, valid = round_trip(animation, name)
                self.assertTrue(valid)

    def test_palette_width_boundaries(self):
        for count in (16, 17, 256, 257):
            colors = [index.to_bytes(3, "big") for index in range(count)]
            frames = []
            for start in range(0, count, 15):
                group = colors[start:start + 15]
                group += [colors[-1]] * (15 - len(group))
                frames.append(b"".join(group))
            animation = make_animation(frames, [1] * len(frames))
            with self.subTest(colors=count):
                if count <= 256:
                    for name in ("dictionary-palette", "delta-palette"):
                        _, valid = round_trip(animation, name)
                        self.assertTrue(valid)
                else:
                    for name in ("dictionary-palette", "delta-palette"):
                        with self.assertRaises(codec.CodecUnavailable):
                            codec.encode_candidate(animation, name)
                    for name in ("dictionary-raw", "delta-raw"):
                        _, valid = round_trip(animation, name)
                        self.assertTrue(valid)

    def test_auto_reports_all_and_exact_budget(self):
        animation = codec.optimize_document(codec.load_document(EXAMPLE), timing="round")
        compilation = codec.compile_animation(animation, "auto")
        self.assertEqual(compilation.selected, "dictionary-palette")
        self.assertEqual(len(compilation.candidates), 4)
        exact = len(compilation.data)
        codec.compile_animation(animation, "auto", exact)
        with self.assertRaisesRegex(codec.CodecUnavailable, "exceeding it by 1"):
            codec.compile_animation(animation, "auto", exact - 1)

    def test_explicit_codec_does_not_fallback(self):
        animation = make_animation([bytes.fromhex("010203") * 15], [1])
        with self.assertRaises(codec.CodecUnavailable):
            codec.compile_animation(animation, "dictionary-raw", budget=10)

    def test_delta_loop_reset_and_finite_end(self):
        animation = make_animation([bytes.fromhex("ff0000") * 15, bytes.fromhex("0000ff") * 15], [1, 2], loop=True)
        data = codec.encode_candidate(animation, "delta-raw")
        frames, entries, loop, end = codec.decode_animation(data)
        self.assertTrue(loop)
        self.assertEqual(frames[0], animation.frames[0])
        self.assertEqual(entries[0].duration, 1)
        finite = make_animation(animation.frames, [1, 2], end="off")
        _, _, loop, end = codec.decode_animation(codec.encode_candidate(finite, "delta-raw"))
        self.assertFalse(loop)
        self.assertEqual(end, "off")

    def test_corruption_and_truncation(self):
        animation = codec.optimize_document(codec.load_document(EXAMPLE), timing="round")
        data = codec.encode_candidate(animation, "dictionary-palette")
        with self.assertRaisesRegex(codec.ValidationError, "CRC-32"):
            codec.decode_animation(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaisesRegex(codec.ValidationError, "total size"):
            codec.decode_animation(data[:-1])
        unknown = bytearray(data)
        unknown[5] = 99
        with self.assertRaisesRegex(codec.ValidationError, "unknown"):
            codec.decode_animation(reseal(unknown))
        bad_index = bytearray(data)
        bad_index[44] = 0x7F
        with self.assertRaises(codec.ValidationError):
            codec.decode_animation(reseal(bad_index))

    def test_bad_delta_mask_and_final_nibble(self):
        animation = make_animation([bytes.fromhex("ff0000") * 15, bytes.fromhex("0000ff") + bytes.fromhex("ff0000") * 14], [1, 2])
        data = codec.encode_candidate(animation, "delta-raw")
        header = struct.unpack_from("<4sBBBB10HI", data)
        timeline_offset = 32 + header[11] + header[12]
        first_delta = timeline_offset + 50 + 5
        invalid = bytearray(data)
        invalid[first_delta] |= 0x80
        with self.assertRaisesRegex(codec.ValidationError, "mask"):
            codec.decode_animation(reseal(invalid))
        reserved = bytearray(data)
        struct.pack_into("<H", reserved, 18, 1)
        with self.assertRaisesRegex(codec.ValidationError, "reserved frame"):
            codec.decode_animation(reseal(reserved))
        with self.assertRaisesRegex(codec.ValidationError, "high nibble"):
            codec.unpack_indices(bytes([0x10]), 4, 1)

    def test_instruction_limit_is_not_success(self):
        animation = make_animation([bytes.fromhex("010203") * 15], [1])
        data = codec.encode_candidate(animation, "dictionary-raw")
        self.assertEqual(len(data), 83)
        with self.assertRaises(codec.ValidationError):
            codec.decode_animation(data[:31])


if __name__ == "__main__":
    unittest.main()
