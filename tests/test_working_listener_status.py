"""#532 item 4: a working pen must not hide missing autonomous pickup."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ambient_env  # noqa: E402
from tests import test_m8shift as base


class TestWorkingListenerStatus(base.CLIBase):
    def setUp(self):
        super().setUp()
        self.init()
        self.assertEqual(self.cw("claim", "codex").returncode, 0)
        self.runtime = Path(self.d, ".m8shift/runtime")

    def listener(self, kind, agent="codex"):
        listeners = self.runtime / "listeners"
        listeners.mkdir(parents=True, exist_ok=True)
        if kind == "absent":
            return
        if kind == "foreground":
            (self.runtime / "presence.json").write_text(json.dumps({agent: {
                "last_seen": base.cowork.iso(base.cowork.now()), "pid": os.getpid(),
            }}))
            return
        if kind == "stale":
            (listeners / (agent + ".pid")).write_text("99999999\n")
            return
        (listeners / (agent + ".pid")).write_text(json.dumps({
            "pid": os.getpid(), "generation": "status-fixture",
        }))
        (listeners / (agent + ".json")).write_text(
            "{invalid" if kind == "unknown" else json.dumps({
                "phase": "halted" if kind == "halted" else "polling",
                "reason": "manual_stop" if kind == "halted" else "",
                "process_pid": os.getpid(), "generation": "status-fixture",
                "notify_only": kind == "notifier",
            }))

    def snapshot(self):
        return {str(p.relative_to(self.d)): p.read_bytes()
                for p in Path(self.d).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts}

    @staticmethod
    def pickup(text):
        return [line for line in text.splitlines() if line.startswith("  pickup ")]

    def test_working_status_reports_coverage_without_inventing_autonomy(self):
        cases = {
            "absent": "holder 'codex' has no listener (absent)",
            "stale": "listener is STALE (process gone)",
            "halted": "listener is HALTED (cause: manual_stop)",
            "unknown": "listener state is unknown; verify listener status",
            "foreground": "foreground presence active; no autonomous pickup",
            "notifier": "ALIVE but notify-only; autonomous pickup is not active",
            "invoker": None,
        }
        for kind, expected in cases.items():
            with self.subTest(kind=kind):
                shutil.rmtree(self.runtime, ignore_errors=True)
                self.listener(kind)
                before = self.snapshot()
                result = self.cw("status", "--for", "claude")
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = self.pickup(result.stdout)
                if expected is None:
                    self.assertEqual(lines, [])
                else:
                    self.assertEqual(len(lines), 1, result.stdout)
                    self.assertIn(expected, lines[0])
                    if kind == "unknown":
                        self.assertNotIn("pickup is dead", lines[0])
                        self.assertNotIn("no autonomous", lines[0])
                watched = self.cw("watch", "--once", "--for", "claude")
                self.assertEqual(watched.returncode, 0, watched.stderr)
                self.assertEqual(self.pickup(watched.stdout), lines)
                self.assertEqual(before, self.snapshot())
                self.assertEqual(self.lock()["state"], "WORKING_CODEX")

    def test_brief_json_and_awaiting_keep_their_existing_surfaces(self):
        self.listener("absent")
        before = self.snapshot()
        brief = self.cw("status", "--brief", "--for", "codex")
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertEqual(self.pickup(brief.stdout), [])
        report = self.cw("status", "--json", "--for", "codex")
        self.assertEqual(report.returncode, 0, report.stderr)
        data = json.loads(report.stdout)
        self.assertEqual(data["state"], "WORKING_CODEX")
        self.assertNotIn("pickup", data)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.cw("append", "codex", "--to", "claude",
                                 "--ask", "review", "--done", "fixture").returncode, 0)
        result = self.cw("status", "--for", "codex")
        self.assertEqual(self.pickup(result.stdout), [])
        self.assertIn("  attention ", result.stdout)

    def test_watch_change_signature_tracks_listener_lifecycle_and_source(self):
        spec = importlib.util.spec_from_file_location(
            "working_status_core", Path(self.d, "m8shift.py"))
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        lock = core.get_lock(core.load_or_die())
        row = {"relay_attention": "none", "producer_coverage": "absent",
               "cause": "", "lifecycle": "DEAD", "source": "none"}
        with mock.patch.object(core, "_status_attention", return_value={"codex": row}):
            first = core._status_signature(lock, False, None, "codex")
            row["lifecycle"] = "STALE"
            second = core._status_signature(lock, False, None, "codex")
            self.assertNotEqual(first, second)
            row["source"] = "presence"
            third = core._status_signature(lock, False, None, "codex")
            self.assertNotEqual(second, third)
