import json
import struct
import sys
import unittest
import zlib
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import animation_brightness as brightness
from custom_animation import CODECS, Entry, ValidationError, decode_animation

EXAMPLE = REPO / "tests" / "fixtures" / "custom_animation" / "fireflies.json"
GRAPH = [(index, index + 1) for index in range(14)]


def reseal(data):
    data = bytearray(data)
    struct.pack_into("<I", data, 28, 0)
    struct.pack_into("<I", data, 28, zlib.crc32(data))
    return bytes(data)


def round_trip(animation):
    compilation = brightness.compile_brightness(animation)
    frames, entries, loop, end = decode_animation(compilation.data)
    expected = [(animation.frames[entry.frame], entry.duration) for entry in animation.entries]
    actual = [(frames[entry.frame], entry.duration) for entry in entries]
    return compilation, actual == expected and loop == animation.loop and end == animation.end


class FixedPointTests(unittest.TestCase):
    def test_zero_full_and_fractional_brightness(self):
        self.assertEqual(brightness.parse_brightness(0), 0)
        self.assertEqual(brightness.parse_brightness(1), 65535)
        self.assertEqual(brightness.parse_brightness(Decimal("0.1375")), 9011)
        self.assertEqual(brightness.render_channel(255, 0), 0)
        self.assertEqual(brightness.render_channel(255, 65535), 255)
        self.assertEqual(brightness.render_channel(255, 9011), 35)
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-0.1"), Decimal("1.1")):
            with self.assertRaises(ValidationError):
                brightness.parse_brightness(value)

    def test_combined_gain_has_no_cumulative_rounding(self):
        zone = brightness.parse_brightness(Decimal("0.5"))
        expected = brightness.render_channel(255, zone, zone)
        for _ in range(1000):
            self.assertEqual(brightness.render_channel(255, zone, zone), expected)
        self.assertEqual(expected, 64)

    def test_independent_zone_fades(self):
        gold = bytes.fromhex("ffd040")
        lemon = bytes.fromhex("fff080")
        first = brightness.Track(0, gold, "linear", ((0, 0), (100, 0), (200, 65535), (300, 0)))
        second = brightness.Track(7, lemon, "linear", ((0, 0), (200, 0), (300, 32768), (400, 0)))
        early = brightness.render_envelope_tick(400, [first, second], 65535, 150)
        late = brightness.render_envelope_tick(400, [first, second], 65535, 300)
        self.assertTrue(any(early[:3]))
        self.assertFalse(any(early[21:24]))
        self.assertFalse(any(late[:3]))
        self.assertTrue(any(late[21:24]))

    def test_stock_render_is_separate(self):
        frame = bytes([255, 255, 255] * 15)
        rendered = brightness.stock_render(frame)
        self.assertEqual(rendered[0], 191)
        self.assertEqual(rendered[1], 127)
        self.assertEqual(rendered[2], 90)


class TrackTests(unittest.TestCase):
    def test_fireflies_envelope_round_trip_and_size(self):
        with self.assertRaisesRegex(ValidationError, "multiple"):
            brightness.optimize_animation_document(brightness.load_animation_document(EXAMPLE))
        animation = brightness.optimize_animation_document(brightness.load_animation_document(EXAMPLE), timing="round")
        self.assertEqual(len(animation.envelope["base_palette"]), 2)
        self.assertGreater(len(animation.palette), 2)
        compilation, valid = round_trip(animation)
        self.assertTrue(valid)
        self.assertEqual(compilation.selected, "brightness-envelope")
        self.assertEqual(len(compilation.data), 110)
        self.assertLess(len(compilation.data), 1369)

    def test_palette_applies_to_base_color_not_shades(self):
        animation = brightness.optimize_animation_document(brightness.load_animation_document(EXAMPLE), timing="round")
        self.assertEqual(animation.warnings, [])
        document = json.loads(EXAMPLE.read_text())
        document["tracks"][0]["color"] = "#123456"
        with self.assertRaisesRegex(ValidationError, "outside strict palette"):
            brightness.optimize_track_model(brightness.load_track_model(document))

    def test_global_gain_is_preserved(self):
        animation = brightness.optimize_animation_document(brightness.load_animation_document(EXAMPLE), timing="round")
        data = brightness.encode_envelope(animation)
        header = struct.unpack_from("<4sBBBB10HI", data)
        self.assertEqual(header[14], brightness.parse_brightness(Decimal("0.7")))
        _, valid = round_trip(animation)
        self.assertTrue(valid)

    def test_adjacent_overlap_and_loop_boundary_rejected(self):
        color = bytes.fromhex("ffd040")
        adjacent = brightness.Track(0, color, "linear", ((0, 0), (100, 65535), (200, 0)))
        neighbor = brightness.Track(1, color, "linear", ((0, 0), (100, 65535), (200, 0)))
        model = brightness.TrackModel(200, [adjacent, neighbor], 65535, False, {}, True, "hold", GRAPH, None)
        with self.assertRaisesRegex(ValidationError, "both lit"):
            brightness.optimize_track_model(model)
        first = brightness.Track(0, color, "hold", ((0, 65535), (100, 0), (200, 65535)))
        second = brightness.Track(1, color, "hold", ((0, 0), (170, 65535), (200, 65535)))
        model = brightness.TrackModel(200, [first, second], 65535, False, {}, True, "hold", GRAPH, None)
        with self.assertRaisesRegex(ValidationError, "loop boundary"):
            brightness.optimize_track_model(model)

    def test_max_lit_zones(self):
        color = bytes.fromhex("ffd040")
        tracks = [brightness.Track(zone, color, "hold", ((0, 65535), (200, 65535))) for zone in range(3)]
        model = brightness.TrackModel(200, tracks, 65535, False, {}, False, "hold", [], 2)
        with self.assertRaisesRegex(ValidationError, "more than 2"):
            brightness.optimize_track_model(model)

    def test_maximum_track_count_and_decoder_corruption(self):
        tracks = [brightness.Track(zone, bytes.fromhex("ffd040"), "hold", ((0, 0), (200, 65535))) for zone in range(15)]
        model = brightness.TrackModel(200, tracks, 65535, False, {}, True, "hold", [], 15)
        animation = brightness.optimize_track_model(model)
        data = brightness.encode_envelope(animation)
        self.assertEqual(len(data), 305)
        with self.assertRaisesRegex(ValidationError, "total size"):
            decode_animation(data[:-1])
        invalid = bytearray(data)
        invalid[32 + 3 + 1] = 15
        with self.assertRaisesRegex(ValidationError, "invalid envelope track"):
            decode_animation(reseal(invalid))
        invalid_time = bytearray(data)
        invalid_time[32 + 3 + 90] = 1
        with self.assertRaises(ValidationError):
            decode_animation(reseal(invalid_time))

    def test_deterministic_fireflies(self):
        palette = {"gold": "#ffd040", "lemon": "#fff080"}
        first = brightness.generate_firefly_document(800, 5984, palette, GRAPH, 1, "0.7")
        second = brightness.generate_firefly_document(800, 5984, palette, GRAPH, 1, "0.7")
        self.assertEqual(first, second)
        model = brightness.load_track_model(first)
        animation = brightness.optimize_track_model(model)
        self.assertEqual(len(animation.envelope["base_palette"]), 2)
        compilation, valid = round_trip(animation)
        self.assertTrue(valid)
        self.assertEqual(len(compilation.data), 296)


if __name__ == "__main__":
    unittest.main()
