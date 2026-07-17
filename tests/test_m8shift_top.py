import subprocess
import sys
import unittest
import importlib.util
import copy
import hashlib
import io
import json
import os
import signal
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
        "project": "demo", "m8shift_version": "v3.61.0", "session": "session-1",
        "holder": "codex", "state": "WORKING_CODEX", "turn": 7,
        "since": "2026-07-13T00:00:00Z", "expires": "2026-07-13T00:30:00Z",
        "pen": {"heartbeat": "2026-07-13T00:10:00Z"},
        "agents": [{"id": "codex", "model": "gpt-5.4", "model_source": "self_declared",
                    "role_state": "working", "usage": {
                        "captured_at": "2026-07-13T00:14:00Z", "age_seconds": 60,
                        "freshness": "fresh", "stale": False, "windows": {}}}],
        "ledger": {}, "listeners": [],
        "time_accounting": {
            "schema": "m8shift.time-accounting/1", "quality": "partial",
            "wall_seconds": 65160, "effective_work_seconds": 19080,
            "non_work_seconds": 34860, "awaiting_seconds": 7800,
            "paused_seconds": 26400, "idle_seconds": 660,
            "unclassified_seconds": 11220, "coverage_ratio": 0.8278,
        },
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
        with mock.patch.dict(os.environ, {"TERM": "xterm-color"}, clear=True):
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

    def test_pen_and_ttl_share_semantic_column_offsets_at_all_layouts(self):
        top = load_top()
        for width in (80, 120, 160):
            with self.subTest(width=width), \
                    mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
                lines = top.render(fixture(), width, self.NOW).splitlines()
            pen = next(line for line in lines if "PEN" in line)
            ttl = next(line for line in lines if "TTL" in line)
            gauge = "<" if width < 100 else "█"
            self.assertEqual(pen.index("codex"), ttl.index(gauge))
            self.assertEqual(pen.index("→ turn 8"), ttl.index("15:00 left"))
            self.assertEqual(pen.index("claimed"), ttl.index("expires"))
            self.assertGreater(pen.index("hb " if width < 100 else "heartbeat "),
                               pen.index("claimed"))
            self.assertTrue(all(len(line) == width for line in lines))

    def test_header_wordmark_uses_truecolour_when_terminal_advertises_it(self):
        top = load_top()
        for capability in ("truecolor", "24bit"):
            with mock.patch.dict(os.environ, {"COLORTERM": capability}, clear=True):
                for width in (80, 100, 120):
                    output = top.render(fixture(), width, self.NOW)
                    self.assertIn("\x1b[1;38;2;255;122;24mM\x1b[0m", output)
                    self.assertIn("\x1b[1;38;2;93;38;242m8\x1b[0m", output)
                    self.assertIn("\x1b[1mSHIFT\x1b[0m", output)
                    self.assertTrue(all(
                        len(line) == width for line in self._plain(output).splitlines()))

    def test_header_wordmark_falls_back_to_256_colours(self):
        top = load_top()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            for width in (80, 100, 120):
                output = top.render(fixture(), width, self.NOW)
                self.assertIn("\x1b[1;38;5;208mM\x1b[0m", output)
                self.assertIn("\x1b[1;38;5;99m8\x1b[0m", output)
                self.assertNotIn("38;2", output)
                self.assertTrue(all(
                    len(line) == width for line in self._plain(output).splitlines()))

    def test_header_wordmark_falls_back_to_semantic_ansi16_slots(self):
        top = load_top()
        with mock.patch.dict(os.environ, {"TERM": "xterm-color"}, clear=True):
            output = top.render(fixture(), 120, self.NOW)
        self.assertIn("\x1b[1;33mM\x1b[0m", output)
        self.assertIn("\x1b[1;35m8\x1b[0m", output)
        self.assertNotIn("38;", output)

    def test_header_wordmark_honours_no_color(self):
        top = load_top()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1", "COLORTERM": "truecolor"},
                             clear=True):
            for width in (80, 100, 120):
                output = top.render(fixture(), width, self.NOW)
                self.assertIn("M8SHIFT", output)
                self.assertNotIn("\x1b[", output)
                self.assertTrue(all(len(line) == width for line in output.splitlines()))

    def test_semantic_roles_are_exact_in_every_colour_tier(self):
        top = load_top()
        roles = {
            "green": ((87, 171, 90), 71, "32"),
            "red": ((244, 112, 103), 203, "31"),
            "yellow": ((198, 144, 38), 172, "33"),
            "cyan": ((57, 197, 207), 80, "36"),
            "magenta": ((176, 131, 240), 141, "35"),
            "dim": ((99, 110, 123), 242, "90"),
            "badge": ((205, 217, 229), 253, "97"),
        }
        for role, (rgb, index, slot) in roles.items():
            prefix = "7;" if role == "badge" else ""
            with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True):
                self.assertEqual(
                    top._semantic(role, "meaning"),
                    "\x1b[%s38;2;%d;%d;%dmmeaning\x1b[0m" % ((prefix,) + rgb))
            with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
                self.assertEqual(top._semantic(role, "meaning"),
                                 "\x1b[%s38;5;%dmmeaning\x1b[0m" % (prefix, index))
            with mock.patch.dict(os.environ, {"TERM": "xterm-color"}, clear=True):
                self.assertEqual(top._semantic(role, "meaning"),
                                 "\x1b[%s%smeaning\x1b[0m" % (prefix, slot + "m"))
            for plain_env in ({"NO_COLOR": "1", "COLORTERM": "truecolor"},
                              {"TERM": "dumb", "COLORTERM": "truecolor"}):
                with mock.patch.dict(os.environ, plain_env, clear=True):
                    self.assertEqual(top._semantic(role, "meaning"), "meaning")

    def test_heartbeat_uses_relative_full_and_slim_formats_with_liveness_tiers(self):
        top = load_top()
        cases = (
            ("fresh", "2026-07-13T00:14:48Z", "12 s", (87, 171, 90)),
            ("alive-expired", "2026-07-13T00:12:00Z", "3 m", (198, 144, 38)),
            ("ordinary-stale", "2026-07-12T23:15:00Z", "1 h", (244, 112, 103)),
        )
        for liveness, stamp, age, rgb in cases:
            data = fixture()
            data["liveness"] = liveness
            data["pen"]["heartbeat"] = stamp
            with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True):
                wide = top.render(data, 120, self.NOW)
            colour = "\x1b[38;2;%d;%d;%dm" % rgb
            self.assertIn(colour + "heartbeat %s ago\x1b[0m" % age, wide)
            with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
                slim = top.render(data, 80, self.NOW)
            self.assertIn("hb %s" % age, slim)
            self.assertNotIn("hb %s ago" % age, slim)
            for width in (80, 120, 160):
                output = self._plain(top.render(data, width, self.NOW))
                self.assertTrue(all(len(line) == width for line in output.splitlines()))

    def test_ledger_uses_readable_full_and_slim_formats_with_semantic_colours(self):
        top = load_top()
        data = fixture()
        data["ledger"] = {
            "tasks_open": 3, "decisions_pending": 2,
            "doctor_findings": 0, "gate_armed": True,
        }
        with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True):
            wide = top.render(data, 120, self.NOW)
        plain = self._plain(wide)
        self.assertIn(
            "tasks 3 open   decisions 2 pending   doctor 0 findings   gate armed",
            plain)
        self.assertIn("\x1b[38;2;57;197;207m3\x1b[0m", wide)
        self.assertIn("\x1b[38;2;57;197;207m2\x1b[0m", wide)
        self.assertIn("\x1b[38;2;87;171;90m0\x1b[0m", wide)
        self.assertIn("\x1b[38;2;87;171;90marmed\x1b[0m", wide)

        data["ledger"].update({"doctor_findings": 4, "gate_armed": False})
        with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True):
            warning = top.render(data, 120, self.NOW)
        self.assertIn("\x1b[38;2;244;112;103m4\x1b[0m", warning)
        self.assertIn("\x1b[38;2;198;144;38mdisarmed\x1b[0m", warning)

        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
            slim = top.render(data, 80, self.NOW)
        self.assertIn("tasks 3 . decisions 2 . doctor 4 . gate disarmed", slim)
        self.assertNotIn("\x1b[", slim)
        for width in (80, 120, 160):
            output = self._plain(top.render(data, width, self.NOW))
            self.assertTrue(all(len(line) == width for line in output.splitlines()))

    def test_all_capabilities_preserve_frame_and_non_colour_meaning(self):
        top = load_top()
        tiers = (
            ({"COLORTERM": "truecolor"}, True),
            ({"TERM": "xterm-256color"}, True),
            ({"TERM": "xterm-color"}, True),
            ({"NO_COLOR": "1", "COLORTERM": "truecolor"}, False),
            ({"TERM": "dumb", "COLORTERM": "truecolor"}, False),
        )
        for env, has_ansi in tiers:
            with mock.patch.dict(os.environ, env, clear=True):
                for width in (80, 100, 120):
                    output = top.render(fixture(), width, self.NOW)
                    plain = self._plain(output)
                    self.assertEqual("\x1b[" in output, has_ansi)
                    self.assertTrue(all(len(line) == width for line in plain.splitlines()))
                    for token in ("M8SHIFT", "PEN", "[WORKING_CODEX]",
                                  "→ turn 8", "TTL", "alive", "✦", "● working"):
                        self.assertIn(token, plain)

    def test_usage_thresholds_remain_green_below_60_yellow_to_85_red_at_85(self):
        top = load_top()
        data = fixture()
        data["agents"] = []
        for name, ratio in (("safe", .59), ("elevated", .60), ("danger", .85)):
            data["agents"].append({
                "id": name, "model": "m", "role_state": "idle",
                "usage": {"freshness": "fresh", "stale": False, "windows": {
                    "session_5h": {"used_ratio": ratio},
                    "weekly": {"used_ratio": ratio},
                }},
            })
        with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True):
            output = top.render(data, 120, self.NOW)
        self.assertIn("\x1b[38;2;87;171;90m5h 59%\x1b[0m", output)
        self.assertIn("\x1b[38;2;198;144;38m5h 60%\x1b[0m", output)
        self.assertIn("\x1b[38;2;244;112;103m5h 85%\x1b[0m", output)

    def test_width_uses_real_geometry_above_120(self):
        top = load_top()
        output = top.render(fixture(), 174, self.NOW)
        plain = self._plain(output)
        self.assertTrue(all(len(line) == 174 for line in plain.splitlines()))

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

    def test_pen_turn_track_preserves_realistic_numbers_and_frame_fidelity(self):
        top = load_top()
        for turn in (725, 1234):
            data = fixture()
            data["turn"] = turn
            for width in (80, 96, 100, 120, 160):
                with self.subTest(turn=turn, width=width):
                    output = self._plain(top.render(data, width, self.NOW))
                    self.assertIn("→ turn %d" % (turn + 1), output)
                    self.assertTrue(all(
                        len(line) == width for line in output.splitlines()))

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
        for width in (80, 120, 160):
            output = self._plain(top.render(data, width, self.NOW, utc=True))
            self.assertIn("42% reset Mon 07-13 05:00Z", output)
            if width >= 120:
                self.assertIn("weekly 30% reset Fri 07-17 05:00Z", output)
            self.assertTrue(all(len(line) == width for line in output.splitlines()))

    def test_stale_ratio_always_carries_stale_token_across_layout_matrix(self):
        top = load_top()
        data = fixture()
        data["agents"][0].update({
            "id": "agent-with-long-id", "model": "provider/model-with-a-very-long-name",
        })
        data["agents"][0]["usage"].update({
            "captured_at": "2026-07-12T23:00:00Z", "age_seconds": 4500,
            "freshness": "stale", "stale": True,
            "windows": {
                "session_5h": {"used_ratio": .73},
                "weekly": {"not_provided": True, "used_ratio": None},
            },
        })
        colour_envs = ({"NO_COLOR": "1"}, {"TERM": "xterm-color"},
                       {"TERM": "xterm-256color"}, {"COLORTERM": "truecolor"})
        for width in (72, 80, 96, 99, 100, 120, 160):
            for env in colour_envs:
                with self.subTest(width=width, env=env), \
                        mock.patch.dict(os.environ, env, clear=True):
                    plain = self._plain(top.render(data, width, self.NOW))
                    ratio_lines = [line for line in plain.splitlines() if "73%" in line]
                    self.assertTrue(all("STALE" in line for line in ratio_lines))
                    self.assertNotIn("73% S│", plain)
                    self.assertTrue(all(len(line) == width for line in plain.splitlines()))

    def test_unknown_freshness_hides_ratio_but_preserves_not_provided(self):
        top = load_top()
        data = fixture()
        data["agents"][0]["usage"].update({
            "captured_at": "bad", "age_seconds": None,
            "freshness": "unknown", "stale": True,
            "windows": {
                "session_5h": {"used_ratio": .88},
                "weekly": {"not_provided": True, "used_ratio": None},
            },
        })
        for width in (80, 120, 160):
            for env in ({"NO_COLOR": "1"}, {"TERM": "xterm-color"}):
                with self.subTest(width=width, env=env), \
                        mock.patch.dict(os.environ, env, clear=True):
                    plain = self._plain(top.render(data, width, self.NOW))
                    self.assertIn("unknown", plain)
                    self.assertNotIn("88%", plain)
                    if width >= 120:
                        self.assertIn("weekly n/a", plain)
                    self.assertTrue(all(len(line) == width for line in plain.splitlines()))

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
            self.assertIn("heartbeat 5 m ago", local_frame)
            self.assertIn("expires 2026-07-14 02:30", local_frame)
            self.assertIn("5h 42% reset Tue 07-14 01:45", local_frame)
            self.assertIn("weekly 30% reset Tue 07-14 02:15", local_frame)
            self.assertIn("2026-07-14T01:50:00", local_frame)
            self.assertNotIn("Z", local_frame)

            utc_frame = self._plain(top.render(data, 120, now, utc=True))
            for token in (
                    "23:45:00Z", "claimed 2026-07-13 23:30Z",
                    "heartbeat 5 m ago", "expires 2026-07-14 00:30Z",
                    "5h 42% reset Mon 07-13 23:45Z",
                    "weekly 30% reset Tue 07-14 00:15Z",
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

    def test_footer_shows_configured_auto_refresh_interval(self):
        top = load_top()
        for width in (80, 120, 160):
            output = self._plain(top.render(fixture(), width, self.NOW, interval=7))
            self.assertIn("auto-refresh 7s", output)
            self.assertTrue(all(len(line) == width for line in output.splitlines()))

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
        self.assertEqual(top.read_key(io.StringIO("\x1b[C"), selector=ready), "right")
        self.assertEqual(top.read_key(io.StringIO("\x1b[D"), selector=ready), "left")
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
        # RFC 064's permanent TIME strip makes the one-agent wide chrome 15
        # rows, leaving three activity rows in an 18-line terminal.
        self.assertEqual(top.activity_max_scroll(snap, 120, 18), 7)
        output = self._plain(top.render(
            snap, 120, self.NOW, height=18, activity_offset=1))
        self.assertEqual(len(output.splitlines()), 18)
        self.assertIn("activity turns 7-9 / 10", output)
        self.assertIn("│  9", output)
        self.assertNotIn("│  10", output)
        self.assertIn("│  7", output)
        self.assertNotIn("│  5", output)

    def test_activity_viewport_caps_at_twenty_but_physical_fill_keeps_height(self):
        top = load_top()
        snap = fixture()
        for width, fixed in ((80, 18), (120, 15)):
            for capacity in (0, 7, 8, 16, 20, 24):
                height = fixed + capacity
                self.assertEqual(top._activity_capacity(snap, width, height), capacity)
                self.assertEqual(top._activity_limit(snap, width, height), min(capacity, 20))
        self.assertEqual(top._activity_request_limit(120, 15, 1), 180)
        self.assertEqual(top._activity_request_limit(120, 35, 1), 200)

    def test_true_turn_denominator_and_truncated_buffer_edge_marker(self):
        top = load_top()
        snap = fixture()
        snap["activity"] = [
            {"turn": n, "agent": "codex", "model": "gpt", "summary": "event %d" % n}
            for n in range(535, 735)
        ]
        snap["activity_limit"] = 200
        snap["activity_truncated"] = True
        for width, height in ((80, 37), (120, 34)):
            before_floor = self._plain(top.render(
                snap, width, self.NOW, height=height, activity_offset=180))
            at_floor = self._plain(top.render(
                snap, width, self.NOW, height=height, activity_offset=181))
            self.assertIn("turns 536-554 / 734", before_floor)
            self.assertNotIn(top.ACTIVITY_BUFFER_EDGE, before_floor)
            self.assertIn("turns 535-553 / 734", at_floor)
            self.assertIn(top.ACTIVITY_BUFFER_EDGE, at_floor)

        snap["activity_truncated"] = False
        complete = self._plain(top.render(
            snap, 120, self.NOW, height=34, activity_offset=181))
        self.assertNotIn(top.ACTIVITY_BUFFER_EDGE, complete)

    def test_expanded_reader_wraps_complete_text_and_preserves_frame_matrix(self):
        top = load_top()
        snap = fixture()
        record = {
            "schema": top.TURN_SCHEMA, "turn": 6, "agent": "claude",
            "to": "codex", "done": "alpha " + ("bravo " * 180).strip(),
        }
        for width in (80, 120, 160):
            height = 30
            wrapped = top._activity_reader_lines(record, width)
            seen = []
            offset = 0
            while True:
                visible, actual, total = top._activity_reader_window(
                    snap, record, width, height, offset)
                seen.extend(visible)
                frame = self._plain(top.render(
                    snap, width, self.NOW, height=height,
                    expanded_activity=record, text_offset=actual))
                self.assertEqual(len(frame.splitlines()), height)
                self.assertTrue(all(len(line) == width for line in frame.splitlines()))
                self.assertIn("ACTIVITY · EXPANDED #6", frame)
                if actual + len(visible) >= total:
                    break
                offset = top.activity_text_page(
                    snap, record, width, height, actual, 1)
            self.assertEqual(seen, wrapped)

    def test_expanded_reader_navigates_immutable_blocks_and_fetches_one_turn(self):
        top = load_top()
        snap = fixture()
        snap["activity"] = [{"turn": n} for n in range(1, 5)]
        self.assertEqual(top.activity_adjacent_turn(snap, 4, 1), 3)
        self.assertEqual(top.activity_adjacent_turn(snap, 3, -1), 4)
        self.assertEqual(top.activity_adjacent_turn(snap, 1, 1), 1)

        payload = {"schema": top.TURN_SCHEMA, "turn": 3, "agent": "codex",
                   "to": "claude", "at": None, "done": "complete"}
        proc = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        with mock.patch.object(top.subprocess, "run", return_value=proc) as run:
            self.assertEqual(top.load_activity_turn("engine.py", "/relay", 3), payload)
        self.assertEqual(run.call_args.args[0][-3:], ["turn", "3", "--json"])

    def test_help_overlay_documents_keys_and_preserves_frame_width(self):
        top = load_top()
        for width in (80, 120, 160):
            output = top.render_help(width, interval=7, height=24)
            self.assertTrue(all(len(line) == width for line in output.splitlines()))
            self.assertEqual(len(output.splitlines()), 24)
            self.assertIn("q       quit", output)
            self.assertIn("Esc     close help", output)
            self.assertIn("e       toggle compact", output)
            self.assertIn("↑ / ↓   scroll", output)
            self.assertIn("← / →   page complete", output)
            self.assertIn("every 7s", output)

    def test_permanent_time_strip_preserves_priority_geometry_and_one_row_budget(self):
        top = load_top()
        for width in (80, 120, 160):
            with self.subTest(width=width), \
                    mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
                output = top.render(fixture(), width, self.NOW, height=30)
            lines = output.splitlines()
            time_rows = [index for index, line in enumerate(lines) if "TIME" in line]
            self.assertEqual(len(time_rows), 1)
            self.assertIn("effective* 5h18", lines[time_rows[0]])
            self.assertIn("non-work 9h41", lines[time_rows[0]])
            self.assertIn("unknown 3h07", lines[time_rows[0]])
            self.assertIn("q quit", lines[time_rows[0] + 1])
            self.assertEqual(len(lines), 30)
            self.assertTrue(all(len(line) == width for line in lines))

        exact = fixture()
        exact["time_accounting"] = dict(exact["time_accounting"], quality="exact",
                                         unclassified_seconds=0)
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
            exact_output = top.render(exact, 120, self.NOW)
        exact_time = next(line for line in exact_output.splitlines() if "TIME" in line)
        self.assertNotIn("unknown", exact_time)

        # D4: compared with the pre-strip chrome, exactly one activity row is spent.
        self.assertEqual(top._activity_capacity(fixture(), 80, 30), 12)
        self.assertEqual(top._activity_capacity(fixture(), 120, 30), 15)

    def test_time_strip_uses_non_judgmental_colours_and_keeps_unknown_visible(self):
        top = load_top()
        with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=True):
            output = top.render(fixture(), 120, self.NOW)
        self.assertIn("\x1b[38;2;57;197;207meffective* 5h18\x1b[0m", output)
        self.assertIn("\x1b[38;2;57;197;207mnon-work 9h41\x1b[0m", output)
        self.assertIn("\x1b[38;2;198;144;38munknown 3h07\x1b[0m", output)

    def test_status_accounting_sibling_survives_snapshot_merge(self):
        top = load_top()
        payload = fixture()
        accounting = payload.pop("time_accounting")
        snapshot = {
            key: payload[key] for key in (
                "agents", "listeners", "last_turn", "ledger", "pen", "activity")
        }
        snapshot.update({
            "schema": "m8shift.status/1", "activity_limit": 8,
            "activity_truncated": False,
        })
        wire = dict(payload, time_accounting=accounting, snapshot=snapshot)
        proc = mock.Mock(returncode=0, stdout=json.dumps(wire), stderr="")
        with mock.patch.object(top.subprocess, "run", return_value=proc):
            merged = top.load_snapshot("engine.py", "/relay")
        self.assertEqual(merged["time_accounting"], accounting)
        self.assertEqual(merged["schema"], "m8shift.status/1")

    def test_120_column_plain_frame_is_byte_stable(self):
        top = load_top()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=True):
            output = top.render(fixture(), 120, self.NOW)
        self.assertEqual(
            hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "010fabe4de6fd6a1901dfb51df6337afa7261d9c30d0af89b638c82636ea957b",
        )

    def test_weighted_largest_remainder_track_plans_are_exact(self):
        top = load_top()
        plans = (
            ((9, 8, 17, 15, 26, 43), (0, 0, 0, 0, 1, 1), {
                121: [9, 8, 17, 15, 27, 43],
                160: [9, 8, 17, 15, 46, 63],
                240: [9, 8, 17, 15, 86, 103],
            }),
            ((10, 30, 12, 66), (0, 0, 0, 1), {
                121: [10, 30, 12, 67],
                160: [10, 30, 12, 106],
                240: [10, 30, 12, 186],
            }),
            ((10, 10, 18, 14, 21, 45), (0, 1, 1, 0, 2, 2), {
                121: [10, 10, 18, 14, 22, 45],
                160: [10, 17, 25, 14, 34, 58],
                240: [10, 30, 38, 14, 61, 85],
            }),
            ((8, 21, 8, 10, 22, 14, 35), (0, 0, 0, 0, 1, 1, 2), {
                121: [8, 21, 8, 10, 22, 14, 36],
                160: [8, 21, 8, 10, 32, 24, 55],
                240: [8, 21, 8, 10, 52, 44, 95],
            }),
        )
        for baseline, weights, expected_by_width in plans:
            for width, expected in expected_by_width.items():
                actual = top._flex_track_widths(width, baseline, weights)
                self.assertEqual(actual, expected)
                self.assertEqual(sum(actual), width - 2)

    def test_geometry_acceptance_matrix_plain_and_ansi(self):
        top = load_top()
        widths = (24, 80, 99, 100, 120, 121, 160, 240)
        tiers = ({"NO_COLOR": "1"}, {"COLORTERM": "truecolor"})
        count_pairs = ((0, 0), (1, 2), (3, 30))
        template = fixture()["agents"][0]
        for width in widths:
            for agent_count, activity_count in count_pairs:
                snap = fixture()
                snap["agents"] = []
                for index in range(agent_count):
                    agent = copy.deepcopy(template)
                    agent["id"] = "agent-%d" % index
                    snap["agents"].append(agent)
                snap["activity"] = [
                    {"turn": index + 1, "agent": "agent-0", "model": "model",
                     "summary": "event %d" % (index + 1)}
                    for index in range(activity_count)
                ]
                chrome = (14 if width >= 100 else 17) + agent_count
                heights = sorted(set((max(1, chrome - 1), chrome, chrome + 1,
                                      24, 40, 60)))
                for env in tiers:
                    with mock.patch.dict(os.environ, env, clear=True):
                        for height in heights:
                            output = top.render(snap, width, self.NOW, height=height)
                            plain = self._plain(output)
                            lines = plain.splitlines()
                            self.assertTrue(all(len(line) == max(24, width)
                                                for line in lines))
                            expected_height = height if height >= chrome else chrome
                            self.assertEqual(len(lines), expected_height)
                            self.assertTrue(lines[-1].startswith("└"))

    def test_self_pipe_coalesces_resize_bursts(self):
        top = load_top()
        read_fd, write_fd = top._open_self_pipe()
        try:
            os.write(write_fd, b"r" * 32)
            self.assertEqual(top._drain_self_pipe(read_fd), 32)
            self.assertEqual(top._drain_self_pipe(read_fd), 0)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    @unittest.skipUnless(hasattr(signal, "SIGWINCH"), "SIGWINCH is POSIX-only")
    def test_resize_recomputes_geometry_immediately_and_preserves_help(self):
        top = load_top()

        class TTY(io.StringIO):
            @staticmethod
            def isatty():
                return True

        stdin, stdout = TTY(), TTY()
        calls = {"select": 0, "size": 0}

        class LoopDone(Exception):
            pass

        def ready(readers, _writers, _errors, _timeout):
            calls["select"] += 1
            if calls["select"] == 1:
                return [stdin], [], []
            if calls["select"] == 2:
                return [reader for reader in readers if isinstance(reader, int)], [], []
            raise LoopDone

        def terminal_size(_fallback=None):
            if _fallback is None:  # argparse asks only for help-text wrapping.
                return os.terminal_size((80, 24))
            calls["size"] += 1
            return os.terminal_size(
                (120, 18) if calls["size"] <= 2 else (160, 24))

        real_help = top.render_help
        with mock.patch.dict(os.environ, {"TERM": "xterm"}, clear=True), \
                mock.patch.object(top.sys, "stdin", stdin), \
                mock.patch.object(top.sys, "stdout", stdout), \
                mock.patch.object(top, "enter"), mock.patch.object(top, "restore"), \
                mock.patch.object(top.atexit, "register"), \
                mock.patch.object(top.IncrementalStatusReader, "load",
                                  return_value=fixture()), \
                mock.patch.object(top.shutil, "get_terminal_size",
                                  side_effect=terminal_size), \
                mock.patch.object(top.select, "select", side_effect=ready), \
                mock.patch.object(top, "read_key", return_value="?"), \
                mock.patch.object(top, "render_help", wraps=real_help) as help_render:
            with self.assertRaises(LoopDone):
                top.main(["--root", str(ROOT), "--interval", "2"])
        self.assertEqual(
            [(call.args[0], call.args[2]) for call in help_render.call_args_list],
            [(120, 18), (160, 24)],
        )

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


class IncrementalStatusReaderTests(unittest.TestCase):
    NOW = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = self.root / "m8shift.py"
        shutil.copy(str(ROOT / "m8shift.py"), str(self.engine))
        self.journal = self.root / "M8SHIFT.md"
        self.top = load_top()
        self.write_turns(12)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def turn(number, body_size=0):
        agent = "alice" if number % 2 == 0 else "bob"
        other = "bob" if agent == "alice" else "alice"
        padding = "x" * body_size
        return (
            "<!-- M8SHIFT:TURN %d %s BEGIN -->\n"
            "- from:    %s\n- to:      %s\n- ask:     next\n"
            "- done:    event %d%s\n- files:   —\n- handoff: %s\n"
            "- at:      2026-07-15T07:%02d:00Z\n\n"
            "<!-- M8SHIFT:TURN %d %s END -->\n" % (
                number, agent, agent, other, number, padding, other,
                number % 60, number, agent))

    @classmethod
    def relay(cls, numbers, note="fixture", body_size=0):
        last = max(numbers) if numbers else 0
        header = (
            "# M8Shift — fixture\n\n"
            "<!-- M8SHIFT:LOCK:BEGIN -->\n"
            "holder: none\nstate: IDLE\nagents: alice,bob\nlang: en\n"
            "session: 20260715T070000Z-deadbeef\nturn: %d\n"
            "since: 2026-07-15T07:00:00Z\nexpires: -\nnote: %s\n"
            "<!-- M8SHIFT:LOCK:END -->\n\n" % (last, note))
        return header + "".join(cls.turn(n, body_size) for n in numbers)

    def write_turns(self, count, note="fixture", body_size=0):
        self.journal.write_text(
            self.relay(list(range(count)), note=note, body_size=body_size),
            encoding="utf-8")

    def reader(self):
        reader = self.top.IncrementalStatusReader(
            str(self.engine), str(self.root))
        reader._prepare_engine()
        self.assertIsNotNone(reader._core)
        reader._core.now = lambda: self.NOW
        return reader

    def oracle(self, reader, limit):
        data = self.journal.read_bytes()
        text = data.decode("utf-8")
        turns = reader._core.parse_turns(text)
        payload = reader._core.status_json_payload_v1(
            reader._core.get_lock(text), turns, self.NOW, limit,
            legacy_last=reader._legacy_last(text),
            valid_turn_count=len(turns))
        return self.top._merge_status_payload(payload)

    @staticmethod
    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")

    def assert_equivalent(self, reader, limit, expected_mode):
        actual = reader.load(limit)
        self.assertEqual(reader.mode, expected_mode)
        self.assertEqual(self.canonical(actual), self.canonical(self.oracle(reader, limit)))
        return actual

    def test_full_oracle_then_stable_one_and_many_appends_are_byte_identical(self):
        reader = self.reader()
        self.assert_equivalent(reader, 20, "full")
        self.assert_equivalent(reader, 20, "incremental")
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write(self.turn(12))
        self.assert_equivalent(reader, 20, "incremental")
        with self.journal.open("a", encoding="utf-8") as fh:
            for number in range(13, 63):
                fh.write(self.turn(number))
        self.assert_equivalent(reader, 20, "incremental")

    def test_lock_length_changes_do_not_invalidate_relative_watermark(self):
        reader = self.reader()
        self.assert_equivalent(reader, 8, "full")
        self.journal.write_text(
            self.relay(list(range(12)), note="x"), encoding="utf-8")
        self.assert_equivalent(reader, 8, "incremental")
        self.journal.write_text(
            self.relay(list(range(12)), note="a much longer mutable lock note"),
            encoding="utf-8")
        self.assert_equivalent(reader, 8, "incremental")

    def test_rotation_forces_full_then_next_append_returns_incremental(self):
        reader = self.reader()
        self.assert_equivalent(reader, 200, "full")
        retained = [0] + list(range(6, 12))
        self.journal.write_text(self.relay(retained), encoding="utf-8")
        self.assert_equivalent(reader, 200, "full")
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write(self.turn(12))
        self.assert_equivalent(reader, 200, "incremental")

    def test_truncated_turn_is_carried_then_completed_without_guessing(self):
        reader = self.reader()
        before = self.assert_equivalent(reader, 20, "full")
        partial = (
            "<!-- M8SHIFT:TURN 12 alice BEGIN -->\n- from:    alice\n"
            "- to:      bob\n- done:    carried")
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write(partial)
        truncated = self.assert_equivalent(reader, 20, "incremental")
        self.assertEqual(truncated["activity"], before["activity"])
        self.assert_equivalent(reader, 20, "incremental")
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write("\n<!-- M8SHIFT:TURN 12 alice END -->\n")
        completed = self.assert_equivalent(reader, 20, "incremental")
        self.assertEqual(completed["activity"][-1]["turn"], 12)

    def test_atomic_replacement_during_validation_forces_full(self):
        replacement = self.relay(list(range(13)), note="atomic replacement")
        fired = {"value": False}

        def replace(reader):
            if fired["value"]:
                return
            fired["value"] = True
            staged = self.root / "M8SHIFT.next"
            staged.write_text(replacement, encoding="utf-8")
            os.replace(str(staged), str(self.journal))
            reader.validation_hook = None

        reader = self.top.IncrementalStatusReader(
            str(self.engine), str(self.root), validation_hook=replace)
        reader._prepare_engine()
        reader._core.now = lambda: self.NOW
        self.assert_equivalent(reader, 20, "full")
        self.assert_equivalent(reader, 20, "full")
        self.assertTrue(fired["value"])

    def test_shrink_and_tail_mismatch_each_force_full(self):
        reader = self.reader()
        self.assert_equivalent(reader, 20, "full")
        self.journal.write_text(self.relay(list(range(5))), encoding="utf-8")
        self.assert_equivalent(reader, 20, "full")

        text = self.journal.read_text(encoding="utf-8")
        self.journal.write_text(text.replace("event 4", "Event 4"), encoding="utf-8")
        self.assert_equivalent(reader, 20, "full")

    def test_engine_replacement_and_version_mismatch_use_full_subprocess(self):
        reader = self.reader()
        self.assert_equivalent(reader, 8, "full")
        source = self.engine.read_text(encoding="utf-8")
        replacement = self.root / "m8shift.next.py"
        replacement.write_text(
            source.replace('VERSION = "3.61.0"', 'VERSION = "3.61.1"', 1),
            encoding="utf-8")
        os.replace(str(replacement), str(self.engine))
        actual = reader.load(8)
        self.assertEqual(reader.mode, "full")
        expected = self.top.load_snapshot(str(self.engine), str(self.root), 8)
        self.assertEqual(self.canonical(actual), self.canonical(expected))

    def test_invalid_utf8_delta_falls_back_to_full_oracle_error(self):
        reader = self.reader()
        self.assert_equivalent(reader, 8, "full")
        with self.journal.open("ab") as fh:
            fh.write(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            reader.load(8)
        self.assertEqual(reader.mode, "full")

    def test_oversized_incomplete_carry_never_seeds_incremental_state(self):
        reader = self.reader()
        self.assert_equivalent(reader, 8, "full")
        partial = ("<!-- M8SHIFT:TURN 12 alice BEGIN -->\n- done:    "
                   + "x" * (reader.MAX_CARRY + 1))
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write(partial)
        self.assert_equivalent(reader, 8, "full")
        self.assertIsNone(reader._cache)
        self.assert_equivalent(reader, 8, "full")

    def test_activity_limits_and_rfc064_sibling_match_full_oracle(self):
        self.write_turns(230)
        reader = self.reader()
        for index, limit in enumerate((0, 8, 20, 200)):
            actual = self.assert_equivalent(
                reader, limit, "full" if index == 0 else "incremental")
            self.assertEqual(actual["activity_limit"], limit)
            self.assertIn("time_accounting", actual)
            self.assertEqual(actual["time_accounting"], self.oracle(
                reader, limit)["time_accounting"])

    def test_stable_and_one_append_reads_and_parses_only_bounded_delta(self):
        self.write_turns(1000, body_size=500)
        reader = self.reader()
        self.assert_equivalent(reader, 200, "full")
        total = self.journal.stat().st_size
        self.assertGreater(total, reader.PREFIX_LIMIT * 4)

        self.assert_equivalent(reader, 200, "incremental")
        self.assertLess(reader.stats["bytes_read"], total // 2)
        self.assertLess(reader.stats["parse_bytes"], 1024)
        self.assertEqual(reader.stats["parse_calls"], 1)

        appended = self.turn(1000, body_size=500).encode("utf-8")
        with self.journal.open("ab") as fh:
            fh.write(appended)
        self.assert_equivalent(reader, 200, "incremental")
        self.assertLessEqual(
            reader.stats["bytes_read"],
            reader.PREFIX_LIMIT + 2 * reader.ANCHOR_BYTES + len(appended))
        self.assertLessEqual(reader.stats["parse_bytes"], len(appended) + 2)

    def test_importing_engine_has_no_cli_side_effects(self):
        code = (
            "import importlib.util; "
            "s=importlib.util.spec_from_file_location('engine', %r); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)" % str(self.engine))
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=str(self.root),
            text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
