"""CLI contract regression: append --body-file is explicit and --body remains an alias."""
import subprocess
import sys
from pathlib import Path
import unittest

CORE = Path(__file__).resolve().parents[1] / "m8shift.py"

class AppendBodyHelpTests(unittest.TestCase):
    def test_help_describes_file_and_stdin(self):
        result = subprocess.run([sys.executable, str(CORE), "append", "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--body-file", result.stdout)
        self.assertIn("--body", result.stdout)
        self.assertIn("not literal text", result.stdout)
        self.assertIn("stdin", result.stdout)

if __name__ == "__main__":
    unittest.main()
