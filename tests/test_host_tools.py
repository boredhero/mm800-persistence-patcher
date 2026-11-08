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


if __name__ == "__main__":
    unittest.main()
