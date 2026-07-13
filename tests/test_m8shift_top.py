import subprocess
import sys
import unittest
import importlib.util
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_top():
    spec = importlib.util.spec_from_file_location("m8shift_top", ROOT / "m8shift-top.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    return {
        "project": "demo", "m8shift_version": "v3.60.0", "session": "session-1",
        "holder": "codex", "state": "WORKING_CODEX", "turn": 7,
        "since": "2026-07-13T00:00:00Z", "expires": "2026-07-13T00:30:00Z",
        "pen": {"heartbeat": "2026-07-13T00:10:00Z"},
        "agents": [{"id": "codex", "role_state": "working", "usage": {"windows": {}}}],
        "ledger": {}, "listeners": [], "last_turn": {"ask_excerpt": "x"},
        "activity": [{"agent": "claude", "summary": "x" * 200}],
    }


class M8ShiftTopFallbackTests(unittest.TestCase):
    NOW = datetime(2026, 7, 13, 0, 15, tzinfo=timezone.utc)

    @staticmethod
    def _plain(output):
        # ANSI is confined inside fixed-width borders; strip it before measuring.
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", output)

    def test_stacked_frame_fidelity_narrow(self):
        top = load_top()
        old = os.environ.pop("NO_COLOR", None)
        try:
            for width in (80, 96):  # < 100 => stacked layout
                output = top.render(fixture(), width, self.NOW)
                self.assertTrue(all(token in output for token in (
                    "┌", "│", "├", "└", "M8SHIFT · demo", "PEN codex", "TTL <")))
                plain = self._plain(output)
                self.assertTrue(all(len(line) == width for line in plain.splitlines()))
        finally:
            if old is not None:
                os.environ["NO_COLOR"] = old

    def test_wide_layout_tabulates_and_pins_right_edge(self):
        top = load_top()
        old = os.environ.pop("NO_COLOR", None)
        try:
            for width in (100, 120):  # >= 100 => wide tabulated layout
                output = top.render(fixture(), width, self.NOW)
                self.assertTrue(all(token in output for token in (
                    "┌", "│", "├", "└", "M8SHIFT · demo", "AGENTS", "TTL", "codex")))
                plain = self._plain(output)
                lines = plain.splitlines()
                self.assertTrue(all(len(line) == width for line in lines))
                # the pen holder sits in its own column, not glued to the label
                self.assertNotIn("PEN codex", output)
                # structural blanks stay blank (clean("") must not leak "unavailable")
                self.assertIn("│" + " " * (width - 2) + "│", lines)
                # colour is emitted in a colour-capable env (stripped for the width check)
                self.assertIn("\x1b[", output)
        finally:
            if old is not None:
                os.environ["NO_COLOR"] = old

    def test_width_capped_near_120(self):
        top = load_top()
        output = top.render(fixture(), 174, self.NOW)  # cap keeps the frame at 120
        plain = self._plain(output)
        self.assertTrue(all(len(line) == 120 for line in plain.splitlines()))

    def test_usage_columns_include_reset_time(self):
        top = load_top()
        data = fixture()
        data["agents"][0]["usage"]["windows"] = {
            "session_5h": {"used_ratio": .42, "resets_at": "2026-07-13T05:00:00Z"},
            "weekly": {"used_ratio": .3, "resets_at": "2026-07-17T05:00:00Z"},
        }
        output = self._plain(top.render(data, 120, self.NOW))
        self.assertIn("5h 42% reset", output)
        self.assertIn("weekly 30% reset", output)

    def test_wide_activity_tabulated_recent_first(self):
        top = load_top()
        snap = dict(fixture())
        snap["activity"] = [
            {"agent": "codex", "kind": "turn", "ts": "2026-07-13T03:40:24Z",
             "summary": "Reviewed the diff and merged"},
            {"agent": "claude", "kind": "turn", "ts": "2026-07-13T03:47:21Z",
             "summary": "Acknowledged the plan; disposable branch off origin/main"},
        ]
        old = os.environ.pop("NO_COLOR", None)
        try:
            output = top.render(snap, 120, self.NOW)
            lines = self._plain(output).splitlines()
            self.assertTrue(all(len(line) == 120 for line in lines))
            # action inferred from the leading verb (note is the remainder)
            self.assertIn("Acknowledged", output)
            self.assertIn("Reviewed", output)
            # timestamps rendered (local); recent turn (03:47) above the older (03:40)
            self.assertIn("2026-07-13T", output)
            i_new = next(i for i, l in enumerate(lines) if "Acknowledged" in l)
            i_old = next(i for i, l in enumerate(lines) if "Reviewed" in l)
            self.assertLess(i_new, i_old)
        finally:
            if old is not None:
                os.environ["NO_COLOR"] = old

    def test_no_color_keeps_frame_without_ansi(self):
        top = load_top()
        old = os.environ.get("NO_COLOR")
        os.environ["NO_COLOR"] = "1"
        try:
            for width in (80, 120):  # stacked and wide, both monochrome-framed
                output = top.render(fixture(), width, self.NOW)
                self.assertNotIn("\x1b[", output)
                self.assertIn("┌", output)
                self.assertTrue(all(len(line) == width for line in output.splitlines()))
        finally:
            if old is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = old

    def test_known_model_exhaustion_is_not_rendered_as_unavailable(self):
        top = load_top()
        snap = fixture()
        snap["agents"][0]["usage"]["windows"] = {
            "session_5h": {"used_ratio": 1.0, "model": "Fable"},
        }
        output = self._plain(top.render(snap, 120, self.NOW))
        self.assertIn("5h EXHAUSTED [Fable]", output)
        self.assertNotIn("5h unavailable", output)

    def test_piped_stdout_falls_back_to_watch_cleanly(self):
        # Piped (non-TTY) stdout must fall back to `watch` byte-compatibly: no
        # alt-screen, no `--interval` int-parse error. `init` is a script-local
        # bootstrap (RFC 038 §9), so copy the engine into a temp dir and drive
        # that copy — the relay lands next to it and the fallback's `watch` has
        # an M8SHIFT.md to render, then exits via --once. Isolating in a temp
        # dir keeps the test deterministic on a clean checkout (M8SHIFT.md is
        # gitignored, so cwd=ROOT would exit rc1 "M8SHIFT.md not found" on CI).
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
