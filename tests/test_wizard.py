import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import mm800_patch_and_flash


class WizardTests(unittest.TestCase):
    def test_find_recovery_device(self):
        output = (
            "sda 223.6G ntfs SanDisk sata\n"
            "/dev/sdc 130K vfat CRP DISABLD LPC1XXX IFLASH usb\n"
        )
        with mock.patch("subprocess.check_output", return_value=output):
            self.assertEqual(mm800_patch_and_flash.find_recovery_device(), "/dev/sdc")

    def test_find_recovery_device_rejects_missing(self):
        with mock.patch("subprocess.check_output", return_value="sda 223.6G ntfs SanDisk sata\n"):
            with self.assertRaises(RuntimeError):
                mm800_patch_and_flash.find_recovery_device()

    def test_extract_stock_rejects_wrong_hash(self):
        with mock.patch("pathlib.Path.read_bytes", return_value=bytes(131072)):
            with self.assertRaises(RuntimeError):
                mm800_patch_and_flash.extract_stock(Path("/tmp/unused"))


if __name__ == "__main__":
    unittest.main()
