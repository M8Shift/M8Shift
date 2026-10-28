"""Point lookup must not substitute an archived homonym for the live handoff."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product import

CORE = Path(__file__).resolve().parents[1] / "m8shift.py"


def turn_block(number, done):
    return (f"<!-- M8SHIFT:TURN {number} alpha BEGIN -->\n"
            f"- from: alpha\n- to: beta\n- done: {done}\n\n"
            f"<!-- M8SHIFT:TURN {number} alpha END -->\n")


class TurnLookupIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m8shift-turn-lookup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy2(CORE, self.root / "m8shift.py")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("M8SHIFT_")}
        self.call("init", "--name", "turn-fixture", "--agents", "alpha,beta")
        self.call("claim", "alpha")
        self.call("append", "alpha", "--to", "beta", "--ask", "next", "--done", "LIVE_DONE")
        self.archive = self.root / "M8SHIFT.archive.md"

    def call(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-B", "m8shift.py", *args],
                                cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_live_turn_wins_over_multiple_archive_homonyms_without_writes(self):
        self.archive.write_text(turn_block(1, "OLD_ONE") + turn_block(1, "OLD_TWO"))
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (self.archive, self.root / "M8SHIFT.md")}
        result = json.loads(self.call("turn", "1", "--json").stdout)
        self.assertEqual(result["done"], "LIVE_DONE")
        self.assertEqual(result["source"], "live")
        self.assertTrue(result["session"])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in (self.archive, self.root / "M8SHIFT.md")})

    def test_live_lookup_does_not_read_an_invalid_archive(self):
        self.archive.write_bytes(b"\xff\xfe")
        result = json.loads(self.call("turn", "1", "--json").stdout)
        self.assertEqual(result["done"], "LIVE_DONE")

    def test_unique_archive_result_is_explicitly_unbound(self):
        self.archive.write_text(turn_block(9, "ARCHIVED_DONE"))
        result = json.loads(self.call("turn", "9", "--json").stdout)
        self.assertEqual(result["source"], "archive")
        self.assertIsNone(result["session"])
        self.assertEqual(result["done"], "ARCHIVED_DONE")
        text = self.call("turn", "9")
        self.assertIn("session identity is not recorded", text.stderr)

    def test_archive_homonyms_are_refused_without_leaking_either_body(self):
        self.archive.write_text(turn_block(9, "OLD_SECRET_ONE") + turn_block(9, "OLD_SECRET_TWO"))
        result = self.call("turn", "9", "--json", expected=4)
        self.assertEqual(result.stdout, "")
        self.assertIn("2 matches in archive", result.stderr)
        self.assertNotIn("OLD_SECRET", result.stderr)

    def test_duplicate_live_turn_is_refused_instead_of_chosen(self):
        relay = self.root / "M8SHIFT.md"
        relay.write_text(relay.read_text() + turn_block(1, "DUPLICATE"))
        result = self.call("turn", "1", "--json", expected=4)
        self.assertIn("2 matches in live", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_absent_negative_and_unreadable_cases_are_distinct(self):
        self.call("turn", "99", "--json", expected=3)
        self.call("turn", "-1", "--json", expected=2)
        self.archive.write_bytes(b"\xff")
        result = self.call("turn", "99", "--json", expected=1)
        self.assertIn("archive could not be read", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
