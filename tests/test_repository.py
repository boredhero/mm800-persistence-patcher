import unittest
from pathlib import Path


class RepositoryHygieneTests(unittest.TestCase):
    def test_no_firmware_or_device_artifacts(self):
        root = Path(__file__).resolve().parents[1]
        forbidden_suffixes = {".bin", ".zip", ".img", ".hex", ".eep", ".eeprom", ".dump", ".bak", ".o", ".elf", ".axf"}
        offenders = [str(path.relative_to(root)) for path in root.rglob("*")
                     if path.is_file() and path.suffix.lower() in forbidden_suffixes]
        self.assertEqual(offenders, [])

    def test_no_analysis_or_ghidra_projects(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = [str(path.relative_to(root)) for path in root.rglob("*")
                     if path.name in {"analysis", "ghidra", "ghidra-full"} or path.suffix in {".gpr", ".rep"}]
        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
