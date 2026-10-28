"""Noninteractive and side-effect-free TOP version CLI contract."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before the product

TOP = Path(__file__).resolve().parents[1] / "m8shift-top.py"


class TopVersionTests(unittest.TestCase):
    def test_version_matches_declared_constant_without_starting_dashboard(self):
        tree = ast.parse(TOP.read_text(encoding="utf-8"))
        version = next(ast.literal_eval(node.value) for node in tree.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(name, ast.Name) and name.id == "VERSION"
                               for name in node.targets))
        env = {k: v for k, v in os.environ.items() if not k.startswith("M8SHIFT_")}
        with tempfile.TemporaryDirectory(prefix="m8shift-top-version-") as root:
            result = subprocess.run([sys.executable, "-B", str(TOP), "--version"],
                                    cwd=root, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"m8shift-top.py {version}")
            self.assertEqual(result.stderr, "")
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_help_exposes_version_option(self):
        result = subprocess.run([sys.executable, "-B", str(TOP), "--help"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--version", result.stdout)


if __name__ == "__main__":
    unittest.main()
