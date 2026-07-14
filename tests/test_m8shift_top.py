import subprocess
import sys
import unittest
import importlib.util
import io
import os
import shutil
import tempfile
import time
from unittest import mock
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
        "agents": [{"id": "codex", "model": "gpt-5.4", "model_source": "self_declared",
                    "role_state": "working", "usage": {"windows": {}}}],
        "ledger": {}, "listeners": [],
        "last_turn": {"agent": "claude", "model": "claude-opus-4-8", "ask_excerpt": "x"},
        "activity": [{"turn": 6, "agent": "claude", "model": "claude-opus-4-8",
                      "summary": "x" * 200}],
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
                plain = self._plain(output)
                self.assertTrue(all(token in plain for token in (
                    "┌", "│", "├", "└", "M8SHIFT · demo", "PEN codex", "TTL <")))
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
                plain = self._plain(output)
                self.assertTrue(all(token in plain for token in (
                    "┌", "│", "├", "└", "M8SHIFT · demo", "AGENTS", "TTL", "codex",
                    "gpt-5.4*", "self-declared (unverified)")))
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

    def test_header_wordmark_uses_bold_brand_glyphs_at_all_layout_widths(self):
        top = load_top()
        old = os.environ.pop("NO_COLOR", None)
        try:
            for width in (80, 100, 120):
                output = top.render(fixture(), width, self.NOW)
                self.assertIn("\x1b[1;38;2;255;122;24mM\x1b[0m", output)
                self.assertIn("\x1b[1;38;2;93;38;242m8\x1b[0m", output)
                self.assertIn("\x1b[1mSHIFT\x1b[0m", output)
                self.assertTrue(all(
                    len(line) == width for line in self._plain(output).splitlines()))
        finally:
            if old is not None:
                os.environ["NO_COLOR"] = old

    def test_width_capped_near_120(self):
        top = load_top()
        output = top.render(fixture(), 174, self.NOW)  # cap keeps the frame at 120
        plain = self._plain(output)
        self.assertTrue(all(len(line) == 120 for line in plain.splitlines()))

    def test_pen_turn_label_describes_live_or_next_turn_at_all_widths(self):
        top = load_top()
        cases = (
            ("WORKING_CODEX", "codex", "claude"),
            ("AWAITING_CODEX", "codex", "claude"),
            # Even when holder and last author match, a live claim is building N+1.
            ("WORKING_CLAUDE", "claude", "claude"),
        )
        for state, holder, author in cases:
            data = fixture()
            data.update({"state": state, "holder": holder})
            data["last_turn"].update({"n": 7, "agent": author})
            for width in (80, 100, 120):
                output = self._plain(top.render(data, width, self.NOW))
                self.assertIn("[%s]" % state, output)
                self.assertIn("→ turn 8", output)
                self.assertTrue(all(len(line) == width for line in output.splitlines()))

    def test_pen_turn_label_marks_last_turn_when_there_is_no_live_holder(self):
        top = load_top()
        data = fixture()
        data.update({"state": "IDLE", "holder": "none"})
        data["last_turn"].update({"n": 7, "agent": "claude"})
        for width in (80, 100, 120):
            output = self._plain(top.render(data, width, self.NOW))
            self.assertIn("last #7", output)
            self.assertIn("#7 claude", output)
            self.assertTrue(all(len(line) == width for line in output.splitlines()))

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

    @unittest.skipUnless(hasattr(time, "tzset"), "requires POSIX timezone control")
    def test_every_time_uses_local_default_or_utc_flag_consistently(self):
        top = load_top()
        data = fixture()
        data.update({
            "since": "2026-07-13T23:30:00Z",
            "expires": "2026-07-14T00:30:00Z",
            "pen": {"heartbeat": "2026-07-13T23:40:00Z"},
            "activity": [{"turn": 6, "agent": "claude", "model": "opus",
                          "ts": "2026-07-13T23:50:00Z", "summary": "Reviewed x"}],
        })
        data["agents"][0]["usage"]["windows"] = {
            "session_5h": {"used_ratio": .42, "resets_at": "2026-07-13T23:45:00Z"},
            "weekly": {"used_ratio": .3, "resets_at": "2026-07-14T00:15:00Z"},
        }
        now = datetime(2026, 7, 13, 23, 45, tzinfo=timezone.utc)
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC-02"  # POSIX sign: local time is UTC+02:00.
        time.tzset()
        try:
            for width in (80, 100, 120):
                local_frame = self._plain(top.render(data, width, now))
                utc_frame = self._plain(top.render(data, width, now, utc=True))
                self.assertTrue(all(len(line) == width for line in local_frame.splitlines()))
                self.assertTrue(all(len(line) == width for line in utc_frame.splitlines()))

            local_frame = self._plain(top.render(data, 120, now))
            self.assertIn("01:45:00", local_frame)  # header clock
            self.assertIn("claimed 2026-07-14 01:30", local_frame)
            self.assertIn("heartbeat 2026-07-14 01:40", local_frame)
            self.assertIn("expires 2026-07-14 02:30", local_frame)
            self.assertIn("5h 42% reset 01:45", local_frame)
            self.assertIn("weekly 30% reset 02:15", local_frame)
            self.assertIn("2026-07-14T01:50:00", local_frame)
            self.assertNotIn("Z", local_frame)

            utc_frame = self._plain(top.render(data, 120, now, utc=True))
            for token in (
                    "23:45:00Z", "claimed 2026-07-13 23:30Z",
                    "heartbeat 2026-07-13 23:40Z", "expires 2026-07-14 00:30Z",
                    "5h 42% reset 23:45Z", "weekly 30% reset 00:15Z",
                    "2026-07-13T23:50:00Z"):
                self.assertIn(token, utc_frame)
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_usage_not_provided_is_distinct_from_unavailable_at_all_widths(self):
        top = load_top()
        data = fixture()
        data["agents"][0]["usage"]["windows"] = {
            "session_5h": {"available": False, "not_provided": True,
                           "used_ratio": None, "resets_at": None},
            "weekly": {"available": False, "not_provided": False,
                       "used_ratio": None, "resets_at": None},
        }
        for width in (80, 100, 120):
            output = self._plain(top.render(data, width, self.NOW))
            self.assertIn("5h n/a", output)
            self.assertIn("weekly unavailable", output)
            self.assertNotIn("5h unavailable", output)
            self.assertTrue(all(len(line) == width for line in output.splitlines()))

    def test_footer_shows_configured_refresh_tick(self):
        top = load_top()
        for width in (80, 120):
            output = self._plain(top.render(fixture(), width, self.NOW, interval=7))
            self.assertIn("tick 7s", output)

    @unittest.skipUnless(os.name == "posix", "cbreak is POSIX-only")
    def test_enter_sets_cbreak_and_restore_reinstates_terminal(self):
        top = load_top()

        class FakeStdin:
            @staticmethod
            def isatty():
                return True

            @staticmethod
            def fileno():
                return 17

        saved = ["original terminal attributes"]
        screen = io.StringIO()
        with mock.patch.object(top.sys, "stdin", FakeStdin()), \
                mock.patch.object(top.termios, "tcgetattr", return_value=saved) as get, \
                mock.patch.object(top.tty_module, "setcbreak") as cbreak, \
                mock.patch.object(top.termios, "tcsetattr") as restore_attrs:
            top.enter(screen)
            get.assert_called_once_with(17)
            cbreak.assert_called_once_with(17, top.termios.TCSANOW)
            top.restore(screen)
            restore_attrs.assert_called_once_with(
                17, top.termios.TCSADRAIN, saved)
            top.restore(screen)
            self.assertEqual(restore_attrs.call_count, 1)
        self.assertEqual(screen.getvalue(), top.ALT_ON + top.ALT_OFF)

    def test_read_key_decodes_arrows_and_standalone_escape(self):
        top = load_top()

        def ready(readers, _writers, _errors, _timeout):
            return readers, [], []

        self.assertEqual(top.read_key(io.StringIO("\x1b[A"), selector=ready), "up")
        self.assertEqual(top.read_key(io.StringIO("\x1b[B"), selector=ready), "down")
        self.assertEqual(
            top.read_key(io.StringIO("\x1b"), selector=lambda *_: ([], [], [])),
            "escape")
        self.assertEqual(top.read_key(io.StringIO("q"), selector=ready), "q")

    def test_every_advertised_key_has_a_real_state_effect(self):
        top = load_top()
        self.assertEqual(top.key_effect("q", 2, 4, False), (True, False, 2, False))
        self.assertEqual(top.key_effect("?", 2, 4, False), (False, True, 2, True))
        self.assertEqual(top.key_effect("?", 2, 4, True), (False, True, 2, False))
        self.assertEqual(top.key_effect("r", 2, 4, True), (False, True, 2, False))
        self.assertEqual(top.key_effect("escape", 2, 4, True),
                         (False, True, 2, False))
        self.assertEqual(top.key_effect("up", 2, 4, False), (False, True, 1, False))
        self.assertEqual(top.key_effect("down", 2, 4, False), (False, True, 3, False))
        self.assertEqual(top.key_effect("down", 4, 4, False), (False, True, 4, False))

    def test_activity_arrows_address_a_clamped_height_aware_window(self):
        top = load_top()
        snap = fixture()
        snap["activity"] = [
            {"turn": n, "agent": "codex", "model": "gpt", "summary": "event %d" % n}
            for n in range(1, 11)
        ]
        # One agent makes the wide frame's fixed portion 14 rows, leaving four
        # activity rows in an 18-line terminal.
        self.assertEqual(top.activity_max_scroll(snap, 120, 18), 6)
        output = self._plain(top.render(
            snap, 120, self.NOW, height=18, activity_offset=1))
        self.assertEqual(len(output.splitlines()), 18)
        self.assertIn("activity 2-5/10", output)
        self.assertIn("│  9", output)
        self.assertNotIn("│  10", output)
        self.assertIn("│  6", output)
        self.assertNotIn("│  5", output)

    def test_help_overlay_documents_keys_and_preserves_frame_width(self):
        top = load_top()
        for width in (80, 120, 160):
            output = top.render_help(width, interval=7)
            expected = min(width, 120)
            self.assertTrue(all(len(line) == expected for line in output.splitlines()))
            self.assertIn("q       quit", output)
            self.assertIn("Esc     close help", output)
            self.assertIn("↑ / ↓   scroll", output)
            self.assertIn("every 7s", output)

    def test_help_documents_refresh_interval(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "m8shift-top.py"), "--help"],
            text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--interval", proc.stdout)
        self.assertIn("refresh interval in seconds", proc.stdout)
        self.assertIn("--utc", proc.stdout)
        self.assertIn("every dashboard time in UTC", proc.stdout)

    def test_wide_activity_tabulated_recent_first(self):
        top = load_top()
        snap = dict(fixture())
        snap["activity"] = [
            {"turn": 40, "agent": "codex", "model": "gpt-5.4", "kind": "turn", "ts": "2026-07-13T03:40:24Z",
             "summary": "Reviewed the diff and merged"},
            {"turn": 41, "agent": "claude", "model": "claude-opus-4-8", "kind": "turn", "ts": "2026-07-13T03:47:21Z",
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
            self.assertIn("claude-opus-4-8*", output)
            # timestamps rendered (local); recent turn (03:47) above the older (03:40)
            self.assertIn("2026-07-13T", output)
            i_new = next(i for i, l in enumerate(lines) if "Acknowledged" in l)
            i_old = next(i for i, l in enumerate(lines) if "Reviewed" in l)
            self.assertIn("│  41    2026-07-13T", lines[i_new])
            self.assertLess(i_new, i_old)
        finally:
            if old is not None:
                os.environ["NO_COLOR"] = old

    def test_no_color_keeps_frame_without_ansi(self):
        top = load_top()
        old = os.environ.get("NO_COLOR")
        os.environ["NO_COLOR"] = "1"
        try:
            for width in (80, 100, 120):  # stacked and wide, both monochrome-framed
                output = top.render(fixture(), width, self.NOW)
                self.assertNotIn("\x1b[", output)
                self.assertIn("M8SHIFT", output)
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

    def test_wide_long_fields_keep_a_gap_between_columns(self):
        top = load_top()
        snap = fixture()
        snap["agents"][0]["usage"]["windows"] = {
            "session_5h": {
                "used_ratio": 1.0,
                "model": "Fable reset mon 08:00",
            },
            "weekly": {"used_ratio": 0.42},
        }
        lines = self._plain(top.render(snap, 120, self.NOW)).splitlines()
        agent_line = next(line for line in lines if "5h EXHAUSTED" in line)
        pen_line = next(line for line in lines if "heartbeat" in line)

        self.assertEqual(agent_line[agent_line.index("weekly") - 1], " ")
        self.assertEqual(pen_line[pen_line.index("heartbeat") - 1], " ")
        self.assertTrue(all(len(line) == 120 for line in lines))

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
