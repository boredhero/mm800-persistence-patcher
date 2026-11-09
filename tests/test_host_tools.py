import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_patched_application
import hidraw_locator as locator
import mm800_persistence_tool


class BuilderTests(unittest.TestCase):
    def test_thumb_bl_known_encoding(self):
        self.assertEqual(build_patched_application.thumb_bl(0x3A8C, 0x4190), bytes.fromhex("00f080fb"))

    def test_thumb_b_known_encoding(self):
        self.assertEqual(build_patched_application.thumb_b(0x3200, 0x32FA), bytes.fromhex("7be0"))

    def test_parse_rgb_repeats_all_zones(self):
        self.assertEqual(mm800_persistence_tool.parse_rgb("00ff00"), bytes.fromhex("00ff00") * 15)

    def test_parse_zone_rgb_returns_one_color(self):
        self.assertEqual(mm800_persistence_tool.parse_zone_rgb("00ff00"), bytes.fromhex("00ff00"))


class ZoneCommandTests(unittest.TestCase):
    def test_set_zones_command_accepts_15_colors(self):
        colors = [f"{index:06x}" for index in range(15)]
        data = bytearray(64)
        data[4:12] = b"MM8BUILD"
        data[12:44] = bytes.fromhex(mm800_persistence_tool.FIRMWARE_VERSION["embedded_build_hash"])
        device = mock.MagicMock()
        device.__enter__.return_value.iap_debug.return_value = data
        with mock.patch.object(mm800_persistence_tool, "MM800", return_value=device), \
             mock.patch.object(sys, "argv", ["mm800_persistence_tool.py", "set-zones", *colors]):
            mm800_persistence_tool.main()
        device.__enter__.return_value.set_rgb.assert_called_once_with(
            b"".join(bytes.fromhex(color) for color in colors)
        )


class FirmwareVersionTests(unittest.TestCase):
    def test_matching_build_has_no_update_warning(self):
        data = bytearray(64)
        data[4:12] = b"MM8BUILD"
        data[12:44] = bytes.fromhex(mm800_persistence_tool.FIRMWARE_VERSION["embedded_build_hash"])
        self.assertIsNone(mm800_persistence_tool.firmware_update_warning(data))

    def test_different_build_warns_with_update_instructions(self):
        data = bytearray(64)
        data[4:12] = b"MM8BUILD"
        warning = mm800_persistence_tool.firmware_update_warning(data)
        self.assertIn("git fetch && git pull", warning)
        self.assertIn("--stock-backup", warning)
        self.assertIn("does not require reflashing", warning)


class HidTests(unittest.TestCase):
    def test_query_accepts_padded_64_byte_response(self):
        packet = bytearray(64)
        packet[:2] = [0x0E, 0x22]
        mm800 = mm800_persistence_tool.MM800.__new__(mm800_persistence_tool.MM800)
        mm800.fd = 1
        mm800.timeout = 0.01
        mm800.device = "/dev/hidraw-test"
        with mock.patch("os.write", return_value=64), \
             mock.patch("select.select", return_value=([1], [], [])), \
             mock.patch("os.read", return_value=packet):
            response = mm800.query(packet, 49)
        self.assertEqual(response, packet)

    def test_locator_persists_and_clears_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            locator.CACHE_PATH = Path(directory) / "cache.json"
            with mock.patch.object(locator, "valid_interface", return_value=True):
                locator.write_cache("/dev/hidraw7")
                self.assertEqual(locator.locate(), "/dev/hidraw7")
                locator.note_failure("/dev/hidraw7")
                locator.note_failure("/dev/hidraw7")
                self.assertEqual(locator.read_record()["failures"], 2)
                locator.note_failure("/dev/hidraw7")
                self.assertFalse(locator.CACHE_PATH.exists())

    def test_success_resets_failure_count(self):
        with tempfile.TemporaryDirectory() as directory:
            locator.CACHE_PATH = Path(directory) / "cache.json"
            with mock.patch.object(locator, "valid_interface", return_value=True):
                locator.write_cache("/dev/hidraw7", 2)
                locator.note_success("/dev/hidraw7")
                self.assertEqual(locator.read_record()["failures"], 0)


class BrightnessTests(unittest.TestCase):
    def test_live_brightness_packet(self):
        mm800 = mm800_persistence_tool.MM800.__new__(mm800_persistence_tool.MM800)
        mm800.fd = 1
        with mock.patch("os.write", return_value=64) as write:
            mm800.set_brightness(2)
        packet = write.call_args.args[1]
        self.assertEqual(packet[:5], bytes([0x07, 0x05, 0x02, 0x00, 0x02]))

    def test_persistent_brightness_packet(self):
        mm800 = mm800_persistence_tool.MM800.__new__(mm800_persistence_tool.MM800)
        mm800.fd = 1
        with mock.patch("os.write", return_value=64) as write:
            mm800.set_brightness(2, persistent=True)
        packet = write.call_args.args[1]
        self.assertEqual(packet[:5], bytes([0x07, 0x05, 0x02, 0xF0, 0x02]))

    def test_persistent_rejects_level_above_three(self):
        mm800 = mm800_persistence_tool.MM800.__new__(mm800_persistence_tool.MM800)
        with self.assertRaises(ValueError):
            mm800.set_brightness(4, persistent=True)


if __name__ == "__main__":
    unittest.main()
