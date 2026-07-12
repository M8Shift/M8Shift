import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M8ShiftTopFallbackTests(unittest.TestCase):
    def test_piped_stdout_falls_back_to_watch_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "m8shift-top.py"), "--interval", "2", "--once"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("invalid int value", proc.stderr)
        self.assertNotIn("\x1b[?1049", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
