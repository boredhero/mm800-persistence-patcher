import os
import struct
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

try:
    import unicorn  # noqa: F401
except ImportError:
    unicorn = None

STOCK = os.environ.get("MM800_STOCK")
CANDIDATE = os.environ.get("MM800_CANDIDATE")
PATCH_ELF = os.environ.get("MM800_PATCH_ELF")
READY = bool(unicorn and STOCK and CANDIDATE and PATCH_ELF)
if READY:
    from firmware_harness import FirmwareHarness, OWNER, RGB, PACKET, IAP_ENTRY, STACK_TOP
    from custom_animation import CODECS, Entry, decode_animation
    from animation_brightness import load_animation_document, optimize_animation_document

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "tests" / "fixtures" / "custom_animation" / "fireflies.json"


@unittest.skipUnless(READY, "set MM800_STOCK, MM800_CANDIDATE, MM800_PATCH_ELF and install unicorn")
class CustomFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.symbols = {}
        for line in subprocess.check_output(["llvm-nm", "-n", PATCH_ELF], text=True).splitlines():
            fields = line.split()
            if len(fields) == 3:
                cls.symbols[fields[2]] = int(fields[0], 16)
        FirmwareHarness.main_loop = cls.symbols["lighting_poll_guard"]

    def setUp(self):
        self.harness = FirmwareHarness(CANDIDATE)
        self.harness.initialize_ram()
        self.harness.call(self.symbols["boot_restore"])

    def upload(self, data):
        h = self.harness
        h.dispatch(bytearray([7, 0x26, 0, len(data) & 0xFF, len(data) >> 8, data[5]]) + bytes(58), max_instructions=2000000)
        for offset in range(0, len(data), 48):
            packet = bytearray([7, 0x26, 1, offset & 0xFF, offset >> 8]) + data[offset:offset + 48]
            packet.extend(bytes(64 - len(packet)))
            h.dispatch(packet, max_instructions=2000000)
        h.dispatch(bytearray([7, 0x26, 2]) + bytes(61), max_instructions=2000000)
        response, _ = h.dispatch(bytearray([0x0E, 0x26]) + bytes(62))
        self.assertEqual(response[4], 1)
        self.assertEqual(response[8], 1)
        self.assertEqual(response[21:25], bytes(4))
        self.assertTrue(all(entry["command"][2] % 4 == 0 for entry in h.writes()))
        return response

    def test_upload_data_initializes_length_argument(self):
        from unicorn.arm_const import UC_ARM_REG_R1

        def invalidate_length(uc, address, _size, _user_data):
            if address == self.symbols["dispatch_set_hook"]:
                uc.reg_write(UC_ARM_REG_R1, 0)

        self.harness.uc.hook_add(unicorn.UC_HOOK_CODE, invalidate_length)
        animation = optimize_animation_document(load_animation_document(EXAMPLE), timing="round")
        self.upload(__import__("animation_brightness").encode_envelope(animation))

    def test_large_envelope_uses_incremental_playback(self):
        from animation_brightness import generate_firefly_document, load_track_model

        document = generate_firefly_document(804, 5984, {"gold": "#ffd040", "lemon": "#fff080"}, [], 4, "0.8", 0.25, 0.9)
        animation = optimize_animation_document(load_track_model(document))
        self.assertEqual(len(animation.envelope["tracks"]), 14)
        data = __import__("animation_brightness").encode_envelope(animation)
        self.upload(data)
        self.harness.call(self.symbols["boot_restore"])
        frames, entries, _, _ = decode_animation(data)
        maximum_lit = max(sum(any(frame[zone * 3:zone * 3 + 3]) for zone in range(15)) for frame in frames)
        self.assertGreaterEqual(maximum_lit, 3)
        self.assertLessEqual(maximum_lit, 4)
        expected = [frames[entry.frame] for entry in entries for _ in range(entry.duration)]
        for tick, frame in enumerate(expected):
            self.harness.iap_commands.clear()
            self.harness.call(self.symbols["custom_tick"])
            reads = sum(item["code"] == 0x3E for item in self.harness.iap_commands)
            self.assertLessEqual(reads, 14 if tick == 0 else 0)
            self.assertEqual(self.harness.read(RGB, 45), frame, f"RGB mismatch at tick {tick}")
        self.harness.call(self.symbols["custom_tick"])
        self.assertEqual(self.harness.read(RGB, 45), frames[0])

    def test_oversize_envelope_ram_requirements_fail_closed(self):
        from types import SimpleNamespace
        from animation_brightness import Track, encode_envelope

        cases = []
        keys = tuple([(time, 0) for time in range(153)] + [(170, 0)])
        cases.append(SimpleNamespace(envelope={"duration_ticks": 5, "base_palette": [b"\xff\x00\x00"], "tracks": [Track(0, b"\xff\x00\x00", "hold", keys)], "global_gain": 65535}, loop=True, end="hold"))
        palette = [b"\xff\x00\x00"] + [bytes([index, 0, 0]) for index in range(1, 16)]
        cases.append(SimpleNamespace(envelope={"duration_ticks": 5, "base_palette": palette, "tracks": [Track(0, b"\xff\x00\x00", "hold", ((0, 0), (170, 0)))], "global_gain": 65535}, loop=True, end="hold"))
        for case in cases:
            with self.subTest(keyframes=len(case.envelope["tracks"][0].keyframes), colors=len(case.envelope["base_palette"])):
                self.setUp()
                data = encode_envelope(case)
                h = self.harness
                h.dispatch(bytearray([7, 0x26, 0, len(data) & 0xFF, len(data) >> 8, data[5]]) + bytes(58), max_instructions=2000000)
                for offset in range(0, len(data), 48):
                    packet = bytearray([7, 0x26, 1, offset & 0xFF, offset >> 8]) + data[offset:offset + 48]
                    packet.extend(bytes(64 - len(packet)))
                    h.dispatch(packet, max_instructions=2000000)
                h.dispatch(bytearray([7, 0x26, 2]) + bytes(61), max_instructions=2000000)
                response, _ = h.dispatch(bytearray([0x0E, 0x26]) + bytes(62))
                self.assertEqual(response[8], 0)
                self.assertEqual(int.from_bytes(response[21:25], "little"), 5)

    def test_envelope_upload_boot_and_playback(self):
        animation = optimize_animation_document(load_animation_document(EXAMPLE), timing="round")
        data = __import__("animation_brightness").encode_envelope(animation)
        response = self.upload(data)
        self.assertEqual(response[7], 3)
        self.assertEqual(response[11:13], len(data).to_bytes(2, "little"))
        self.harness.call(self.symbols["boot_restore"])
        frames, entries, _, _ = decode_animation(data)
        for entry in entries:
            for _ in range(entry.duration):
                self.harness.call(self.symbols["custom_tick"])
            self.assertEqual(self.harness.read(RGB, 45), frames[entry.frame])
        self.harness.call(self.symbols["custom_tick"])
        self.assertEqual(self.harness.read(RGB, 45), frames[0])

    def test_all_codec_playback(self):
        red = bytes.fromhex("ff0000") * 15
        blue = bytes.fromhex("0000ff") * 15
        mixed = bytes.fromhex("ff0000") + bytes.fromhex("0000ff") * 14
        from test_custom_animation import make_animation
        animation = make_animation([red, blue, mixed, red], [1, 2, 3, 4], loop=True)
        for codec in CODECS:
            with self.subTest(codec=codec):
                self.setUp()
                data = __import__("custom_animation").encode_candidate(animation, codec)
                self.upload(data)
                self.harness.call(self.symbols["boot_restore"])
                frames, entries, _, _ = decode_animation(data)
                for entry in entries:
                    for _ in range(entry.duration):
                        self.harness.call(self.symbols["custom_tick"])
                    self.assertEqual(self.harness.read(RGB, 45), frames[entry.frame])

    def test_interrupted_upload_preserves_previous_bank(self):
        animation = optimize_animation_document(load_animation_document(EXAMPLE), timing="round")
        data = __import__("animation_brightness").encode_envelope(animation)
        self.upload(data)
        replacement = bytearray(data)
        replacement[6] = 0
        self.harness.dispatch(bytearray([7, 0x26, 0, len(replacement) & 0xFF, len(replacement) >> 8, replacement[5]]) + bytes(58))
        partial = bytearray([7, 0x26, 1, 0, 0]) + replacement[:16]
        partial.extend(bytes(64 - len(partial)))
        self.harness.dispatch(partial)
        self.harness.dispatch(bytearray([7, 0x26, 3]) + bytes(61))
        self.harness.call(self.symbols["boot_restore"])
        frames, entries, _, _ = decode_animation(data)
        self.harness.call(self.symbols["custom_tick"])
        self.assertEqual(self.harness.read(RGB, 45), frames[0])

    def test_unknown_patch_ram_initializes_capability_state(self):
        self.harness.write(0x10001900, bytes([0xA5]) * 512)
        self.harness.call(self.symbols["boot_restore"])
        response, _ = self.harness.dispatch(bytearray([0x0E, 0x26]) + bytes(62))
        self.assertEqual(response[4], 1)
        self.assertEqual(response[5], 0)
        self.assertEqual(response[6], 0x1F)
        self.assertEqual(int.from_bytes(response[9:11], "little"), 1728)

    def test_static_takeover_does_not_erase_custom_bank(self):
        animation = optimize_animation_document(load_animation_document(EXAMPLE), timing="round")
        data = __import__("animation_brightness").encode_envelope(animation)
        self.upload(data)
        rgb = bytes([0x12, 0x34, 0x56]) * 15
        self.harness.dispatch(bytearray([7, 0x22, 15, 0]) + rgb + bytes(15))
        self.assertEqual(self.harness.read(RGB, 45), rgb)
        self.harness.call(self.symbols["boot_restore"])
        self.harness.call(self.symbols["custom_tick"])
        frames, _, _, _ = decode_animation(data)
        self.assertEqual(self.harness.read(RGB, 45), frames[0])

    def test_purple_delta_palette_uses_bounded_cached_reads(self):
        from custom_animation import encode_candidate

        example = REPO / "examples" / "purple-rotation.json"
        animation = optimize_animation_document(load_animation_document(example))
        data = encode_candidate(animation, "delta-palette")
        self.assertEqual(len(data), 1412)
        self.upload(data)
        h = self.harness
        h.iap_commands.clear()
        boot = h.call(self.symbols["boot_restore"])
        self.assertLess(boot["instructions"], 250000)
        self.assertLessEqual(len(h.iap_commands), 120)
        from unicorn.arm_const import UC_ARM_REG_PRIMASK
        primasks = []
        def observe_iap(uc, address, _size, _data):
            if address == IAP_ENTRY:
                primasks.append(uc.reg_read(UC_ARM_REG_PRIMASK))
        h.uc.hook_add(unicorn.UC_HOOK_CODE, observe_iap)
        frames, entries, _, _ = decode_animation(data)
        expected = [frames[entry.frame] for entry in entries for _ in range(entry.duration)]
        for loop in range(100):
            for tick, frame in enumerate(expected):
                h.iap_commands.clear()
                h.call(self.symbols["custom_tick"])
                self.assertEqual(h.read(RGB, 45), frame, f"RGB mismatch at loop {loop} tick {tick}")
                reads = sum(item["code"] == 0x3E for item in h.iap_commands)
                self.assertEqual(reads, 1 if tick % 4 == 0 else 0)
        self.assertGreaterEqual(h.min_sp, 0x1000076C)
        self.assertTrue(primasks)
        self.assertEqual(set(primasks), {1})

    def test_failed_frame_read_preserves_last_good_output_and_control(self):
        from custom_animation import encode_candidate

        example = REPO / "examples" / "purple-rotation.json"
        animation = optimize_animation_document(load_animation_document(example))
        data = encode_candidate(animation, "delta-palette")
        self.upload(data)
        h = self.harness
        h.call(self.symbols["boot_restore"])
        h.call(self.symbols["custom_tick"])
        previous = h.read(RGB, 45)
        for _ in range(3):
            h.call(self.symbols["custom_tick"])
        h.eeprom_status_queues[0x3E].append(1)
        h.call(self.symbols["custom_tick"])
        self.assertEqual(h.read(RGB, 45), previous)
        response, _ = h.dispatch(bytearray([0x0E, 0x26]) + bytes(62))
        self.assertEqual(response[4], 1)
        rgb = bytes([0x12, 0x34, 0x56]) * 15
        h.dispatch(bytearray([7, 0x22, 15, 0]) + rgb + bytes(15))
        self.assertEqual(h.read(RGB, 45), rgb)

    def test_partial_delta_preserves_unchanged_zones_with_poisoned_stack(self):
        from custom_animation import encode_candidate
        from test_custom_animation import make_animation

        first = bytes([0x11, 0x22, 0x33]) * 15
        second = bytearray(first)
        second[0:3] = bytes([0x44, 0x55, 0x66])
        animation = make_animation([first, bytes(second)], [1, 1], loop=True)
        data = encode_candidate(animation, "delta-palette")
        self.upload(data)
        h = self.harness
        h.call(self.symbols["boot_restore"])
        h.call(self.symbols["custom_tick"])
        self.assertEqual(h.read(RGB, 45), first)
        h.write(h.min_sp, bytes([0xA5]) * (STACK_TOP - h.min_sp))
        h.call(self.symbols["custom_tick"])
        self.assertEqual(h.read(RGB, 45), bytes(second))


if __name__ == "__main__":
    unittest.main()
