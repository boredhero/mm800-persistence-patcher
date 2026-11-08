import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import mm800_restore


class RestoreTests(unittest.TestCase):
    def test_rejects_wrong_backup_hash(self):
        with mock.patch("pathlib.Path.read_bytes", return_value=bytes(131072)):
            with self.assertRaises(RuntimeError):
                mm800_restore.validate_stock_backup(Path("/tmp/unused"))


if __name__ == "__main__":
    unittest.main()
