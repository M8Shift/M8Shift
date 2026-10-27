"""Regression test for the top CLI version contract."""
import subprocess
import sys
from pathlib import Path
import unittest

TOP = Path(__file__).resolve().parents[1] / "m8shift-top.py"

class TopVersionTests(unittest.TestCase):
    def test_version_noninteractive(self):
        result = subprocess.run([sys.executable, str(TOP), "--version"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("m8shift-top.py", result.stdout)
        self.assertRegex(result.stdout, r"\d+\.\d+\.\d+")
        self.assertEqual(result.stderr, "")

if __name__ == "__main__":
    unittest.main()
