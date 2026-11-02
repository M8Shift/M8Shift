"""Behavioral contract for --body-file, stdin and the backward-compatible alias."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before the product

CORE = Path(__file__).resolve().parents[1] / "m8shift.py"


class AppendBodyHelpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m8shift-body-file-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy2(CORE, self.root / "m8shift.py")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("M8SHIFT_")}
        self.command("init", "--name", "body-fixture", "--agents", "alpha,beta")

    def command(self, *args, input=None, expected=0):
        result = subprocess.run([sys.executable, "-B", str(self.root / "m8shift.py"), *args],
                                cwd=self.root, env=self.env, input=input,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_help_describes_file_and_stdin(self):
        result = self.command("append", "--help")
        text = " ".join(result.stdout.split())
        for phrase in ("--body-file", "--body", "not literal text", "stdin", "PATH|-"):
            self.assertIn(phrase, text)

    def test_file_option_and_legacy_alias_read_bytes_not_the_path(self):
        body = "BODY_FIXTURE_FIRST\nA second line with Unicode: été.\n"
        path = self.root / "body.txt"
        path.write_text(body, encoding="utf-8")
        for agent, peer, option in (("alpha", "beta", "--body-file"),
                                    ("beta", "alpha", "--body")):
            self.command("claim", agent)
            self.command("append", agent, "--to", peer, "--ask", "next", "--done", "done",
                         option, str(path))
        text = (self.root / "M8SHIFT.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("BODY_FIXTURE_FIRST"), 2)
        self.assertEqual(text.count("A second line with Unicode: été."), 2)
        self.assertNotIn(str(path), text)

    def test_stdin_is_supported_by_new_option(self):
        self.command("claim", "alpha")
        self.command("append", "alpha", "--to", "beta", "--ask", "next", "--done", "done",
                     "--body-file", "-", input="BODY_FROM_STDIN\n")
        self.assertIn("BODY_FROM_STDIN", (self.root / "M8SHIFT.md").read_text(encoding="utf-8"))

    def test_missing_file_does_not_append_or_release_the_pen(self):
        self.command("claim", "alpha")
        before = (self.root / "M8SHIFT.md").read_bytes()
        result = subprocess.run([sys.executable, "-B", str(self.root / "m8shift.py"),
                                 "append", "alpha", "--to", "beta", "--ask", "next",
                                 "--done", "done", "--body-file", "absent.txt"],
                                cwd=self.root, env=self.env, capture_output=True,
                                text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual((self.root / "M8SHIFT.md").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
