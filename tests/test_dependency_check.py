import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import check_dependencies


class DependencyTests(unittest.TestCase):
    def test_missing_dependency_raises_with_install_command(self):
        with mock.patch("shutil.which", side_effect=lambda command: None if command == "clang" else "/usr/bin/tool"):
            with self.assertRaisesRegex(RuntimeError, "clang"):
                check_dependencies.require_dependencies()

    def test_all_dependencies_present_passes(self):
        with mock.patch("shutil.which", return_value="/usr/bin/tool"):
            check_dependencies.require_dependencies()


if __name__ == "__main__":
    unittest.main()
