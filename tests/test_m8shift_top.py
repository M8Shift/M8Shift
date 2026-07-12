import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class M8ShiftTopFallbackTests(unittest.TestCase):
    def test_piped_stdout_falls_back_to_watch_cleanly(self):
        # Piped (non-TTY) stdout must fall back to `watch` byte-compatibly: no
        # alt-screen, no `--interval` int-parse error. `init` is a script-local
        # bootstrap (RFC 038 §9), so copy the engine into a temp dir and drive
        # that copy — the relay lands next to it and the fallback's `watch` has
        # an M8SHIFT.md to render, then exits via --once.
        with tempfile.TemporaryDirectory() as d:
            for name in ("m8shift.py", "m8shift-top.py"):
                shutil.copy(str(ROOT / name), os.path.join(d, name))
            engine = os.path.join(d, "m8shift.py")
            env = dict(os.environ)
            env.pop("M8SHIFT_ROOT", None)
            env.pop("M8SHIFT_AGENT", None)
            init = subprocess.run(
                [sys.executable, engine, "init", "--agents", "alice,bob"],
                cwd=d, env=env, text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            proc = subprocess.run(
                [sys.executable, os.path.join(d, "m8shift-top.py"),
                 "--engine", engine, "--interval", "2", "--once"],
                cwd=d, env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("invalid int value", proc.stderr)
        self.assertNotIn("\x1b[?1049", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
