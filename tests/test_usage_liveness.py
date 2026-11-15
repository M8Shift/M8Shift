"""#404: exercise the public diagnostic and the real resident loop seams."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ambient_env  # noqa: E402 - isolate before importing the product harness
from tests import test_m8shift as base


class TestUsageLiveness(base.ListenerCLIBase):
    def setUp(self):
        super().setUp()
        self.init()
        spec = importlib.util.spec_from_file_location(
            "usage_liveness_runtime", os.path.join(self.d, "m8shift-runtime.py"))
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)

    def registry(self, **changes):
        row = self.runtime.default_usage_watch("claude")
        row.update(pid=99999999, phase="running", lease_id="dead-lease")
        row.update(changes)
        path = Path(self.runtime.usage_watch_path("claude"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row), encoding="utf-8")
        return row

    def install_receipt(self):
        runtime = Path(self.d, "m8shift-runtime.py")
        core = Path(self.d, "m8shift.py")
        manifest = {"schema": "m8shift.kit.v1", "core": {
            "script": core.name, "version": base.VERSION,
            "sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        }, "companions": [{
            "name": "runtime", "script": runtime.name,
            "version": base.VERSION,
            "sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
            "copied_at": self.runtime.iso(), "source": "fixture",
        }]}
        Path(self.d, ".m8shift", "kit.json").write_text(
            json.dumps(manifest), encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.d)): p.read_bytes()
                for p in Path(self.d).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts}

    def test_core_doctor_surfaces_real_dead_watcher_read_only_and_advisory(self):
        self.registry()
        before_install = self.cw("doctor", "--json", "--lint")
        self.assertFalse(any(row["check"] == "usage.watch_dead"
                             for row in json.loads(before_install.stdout)["findings"]))
        self.install_receipt()
        before = self.snapshot()
        result = self.cw("doctor", "--json", "--lint")
        findings = json.loads(result.stdout)["findings"]
        dead = [row for row in findings if row["check"] == "usage.watch_dead"]
        self.assertEqual(len(dead), 1, findings)
        self.assertEqual(dead[0]["agent"], "claude")
        self.assertEqual(dead[0]["source"], "runtime")
        self.assertEqual(result.returncode, before_install.returncode, findings)
        self.assertEqual(before, self.snapshot())
        text = self.cw("doctor").stdout
        self.assertIn("usage.watch_dead", text)
        self.assertIn("usage watch reconcile --agent claude", text)

    def test_core_doctor_declines_edited_missing_and_symlinked_companion(self):
        self.install_receipt()
        runtime = Path(self.d, "m8shift-runtime.py")
        original = runtime.read_bytes()
        marker = Path(self.d, "unexpected-execution")
        runtime.write_text("VERSION = %s\nfrom pathlib import Path\n"
                           "Path('unexpected-execution').touch()\n" % json.dumps(base.VERSION))
        for state in ("edited", "missing", "symlink"):
            with self.subTest(state=state):
                if state == "missing":
                    runtime.unlink()
                elif state == "symlink":
                    target = Path(self.d, "other-runtime.py")
                    target.write_bytes(original)
                    runtime.symlink_to(target)
                result = self.cw("doctor", "--json")
                findings = json.loads(result.stdout)["findings"]
                self.assertTrue(any(row["check"] == "runtime.doctor_unavailable"
                                    for row in findings), findings)
                self.assertFalse(marker.exists())

    def test_core_doctor_delegates_to_effective_relay_not_the_script_checkout(self):
        self.registry()
        self.install_receipt()
        with tempfile.TemporaryDirectory(prefix="m8shift-doctor-target-") as target:
            shutil.copytree(self.d, target, dirs_exist_ok=True)
            registry = Path(target, ".m8shift", "runtime", "usage-watchers")
            row = json.loads((registry / "claude.json").read_text())
            row["agent"] = "codex"
            (registry / "claude.json").unlink()
            (registry / "codex.json").write_text(json.dumps(row))
            before = self.snapshot()
            target_before = {str(p): p.read_bytes() for p in Path(target).rglob("*")
                             if p.is_file() and "__pycache__" not in p.parts}
            env = dict(os.environ, M8SHIFT_ROOT=target)
            result = subprocess.run(
                [sys.executable, str(Path(self.d, "m8shift.py")), "doctor", "--json"],
                cwd=self.d, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            dead = [row["agent"] for row in json.loads(result.stdout)["findings"]
                    if row["check"] == "usage.watch_dead"]
            self.assertEqual(dead, ["codex"])
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(target_before, {
                str(p): p.read_bytes() for p in Path(target).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts})

    def test_core_doctor_reports_bad_output_and_timeout_without_raw_child_text(self):
        runtime = Path(self.d, "m8shift-runtime.py")
        for output in ("not-json-private-detail", json.dumps({"findings": [
                {"check": "bad", "severity": [], "message": "private-detail"}]})):
            with self.subTest(output=output):
                runtime.write_text("VERSION = %s\nprint(%r)\n" % (json.dumps(base.VERSION), output))
                self.install_receipt()
                result = self.cw("doctor", "--json")
                findings = json.loads(result.stdout)["findings"]
                self.assertTrue(any(row["check"] == "runtime.doctor_unavailable"
                                    for row in findings), findings)
                self.assertNotIn("private-detail", result.stdout + result.stderr)
        core = self.runtime.load_core()
        with mock.patch.object(core.subprocess, "run", side_effect=
                               subprocess.TimeoutExpired("private-detail", 10)):
            findings = core._runtime_doctor_findings()
        self.assertEqual(findings[0]["check"], "runtime.doctor_unavailable")
        self.assertIn("TimeoutExpired", findings[0]["message"])
        self.assertNotIn("private-detail", findings[0]["message"])

    def test_listener_restarts_dead_once_using_serialized_current_intent(self):
        runtime = self.runtime
        self.registry(mode="apply", interval=17)
        relay = Path(self.d, "M8SHIFT.md").read_bytes()

        def spawn(agent, row):
            self.assertTrue(Path(runtime.usage_watch_lock_path(agent)).exists())
            self.assertEqual(row["mode"], "apply")
            self.assertEqual(row["interval"], 17)
            row = dict(row, pid=os.getpid(), phase="starting", started=runtime.iso())
            runtime.atomic_write_json(runtime.usage_watch_path(agent), row)
            return row

        with mock.patch.object(runtime, "spawn_usage_watch", side_effect=spawn) as start, \
             mock.patch.object(runtime, "usage_watch_adapter_probe") as probe, \
             mock.patch.object(runtime, "usage_watch_terminate") as terminate:
            self.assertEqual(runtime.listener_usage_watch_tick("claude"), "started")
            self.assertEqual(runtime.listener_usage_watch_tick("claude"), "healthy")
        self.assertEqual(start.call_count, 1)
        probe.assert_not_called()
        terminate.assert_not_called()
        self.assertFalse(Path(runtime.usage_watch_lock_path("claude")).exists())
        self.assertEqual(Path(self.d, "M8SHIFT.md").read_bytes(), relay)

    def test_listener_never_repairs_absent_stopped_live_or_malformed_registry(self):
        runtime = self.runtime
        current = runtime.iso()
        cases = [
            (None, "absent"),
            ({"desired_state": "stopped"}, "not_requested"),
            ({"desired_state": None}, "not_requested"),
            ({"agent": "codex"}, "invalid"),
            ({"interval": "bad"}, "invalid"),
            ({"pid": True}, "invalid"),
            ({"phase": "stopped"}, "stopped"),
            ({"pid": os.getpid(), "last_tick": current}, "healthy"),
            ({"pid": os.getpid()}, "stale"),
            ({"pid": os.getpid(), "last_tick": current,
              "consecutive_unknown": 3}, "degraded"),
            ({"pid": os.getpid(), "lease_id": ""}, "legacy"),
        ]
        with mock.patch.object(runtime, "spawn_usage_watch") as start, \
             mock.patch.object(runtime, "usage_watch_adapter_probe") as probe, \
             mock.patch.object(runtime, "usage_watch_terminate") as terminate:
            for changes, expected in cases:
                with self.subTest(expected=expected, changes=changes):
                    if changes is not None:
                        self.registry(**changes)
                    before = self.snapshot()
                    self.assertEqual(runtime.listener_usage_watch_tick("claude"), expected)
                    self.assertEqual(self.snapshot(), before)
        start.assert_not_called()
        probe.assert_not_called()
        terminate.assert_not_called()

    def test_listener_rechecks_stop_and_replacement_under_lock_and_fails_open(self):
        runtime = self.runtime
        acquire = runtime.acquire_usage_watch_lock
        for changes, expected in [({"desired_state": "stopped"}, "not_requested"),
                                  ({"pid": os.getpid(), "last_tick": runtime.iso()},
                                   "healthy")]:
            self.registry()

            def racing_acquire(agent):
                self.registry(**changes)
                return acquire(agent)

            with mock.patch.object(runtime, "acquire_usage_watch_lock",
                                   side_effect=racing_acquire), \
                 mock.patch.object(runtime, "spawn_usage_watch") as start:
                self.assertEqual(runtime.listener_usage_watch_tick("claude"), expected)
                start.assert_not_called()
        self.registry()
        with mock.patch.object(runtime, "spawn_usage_watch", side_effect=OSError("private")):
            self.assertEqual(runtime.listener_usage_watch_tick("claude"), "unavailable")
        self.assertFalse(Path(runtime.usage_watch_lock_path("claude")).exists())

    def test_actual_listener_loop_supervises_peer_wait_with_bounded_cadence(self):
        runtime = self.runtime
        self.registry()
        for notify_only, phase, state, expected in [
                (False, "polling", "AWAITING_CODEX", 2),
                (True, "polling", "AWAITING_CODEX", 0),
                (False, "halted", "AWAITING_CODEX", 0),
                (False, "polling", "DONE", 0)]:
            with self.subTest(notify_only=notify_only, phase=phase, state=state):
                ticks = iter([1, 1, 2, 301, 301])
                with mock.patch.object(runtime, "read_listener_state", return_value={"phase": phase}), \
                     mock.patch.object(runtime, "write_listener_state"), \
                     mock.patch.object(runtime, "read_relay_lock_fields", return_value=(
                         {"state": state, "holder": "codex"}, "relay")), \
                     mock.patch.object(runtime, "maybe_notify_stranded"), \
                     mock.patch.object(runtime, "listener_usage_watch_tick", return_value="stale") as tick, \
                     mock.patch.object(runtime, "listener_emit") as emit, \
                     mock.patch.object(runtime, "remove_own_listener_pid"), \
                     mock.patch.object(runtime.time, "monotonic", side_effect=lambda: next(ticks)), \
                     mock.patch.object(runtime.time, "sleep"), \
                     mock.patch.object(runtime, "spawn_usage_watch") as spawn:
                    rc = runtime.run_listener_loop(
                        "claude", {"start_on_idle": False}, self.RUNNER,
                        poll=0.01, max_ticks=3, max_retries=3, max_backoff=1,
                        notify_only=notify_only)
                self.assertEqual(rc, 0)
                self.assertEqual(tick.call_count, expected)
                spawn.assert_not_called()
                warnings = [call for call in emit.call_args_list
                            if "usage.watch_stale" in call.args[1]]
                self.assertEqual(len(warnings), 1 if expected else 0)

    def test_real_listener_wait_restarts_a_real_collector_and_observes_its_tick(self):
        if (not self.runtime.fleet_process_start_ref(os.getpid())
                and not self.runtime.process_argv(os.getpid())):
            self.skipTest("host cannot corroborate process identity; collector stop cannot be qualified")
        self.registry()
        self.assertEqual(self.rt("usage", "init").returncode, 0)
        runtime = self.runtime
        profile = self.profile_path()
        result = self.rt(
            "listener", "start", "--agent", "claude", "--cmd-file", profile,
            "--runner", self.RUNNER, "--foreground", "--max-ticks", "1",
            "--poll-interval", "0.01")
        watch, error = runtime.read_usage_watch("claude")
        try:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("usage.watch_restarted", result.stdout)
            self.assertFalse(error)
            self.assertNotEqual(watch["pid"], 99999999)
            self.assertTrue(runtime.pid_alive(watch["pid"]))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not watch.get("last_tick"):
                time.sleep(0.05)
                watch, error = runtime.read_usage_watch("claude")
            self.assertTrue(watch.get("last_tick"), watch)
            self.assertEqual(watch.get("total_ticks"), 1, watch)
        finally:
            if watch.get("pid") != 99999999:
                diagnostic = {"recorded_start": watch.get("process_start_ref"),
                              "current_start": runtime.fleet_process_start_ref(watch["pid"]),
                              "argv": runtime.process_argv(watch["pid"]),
                              "cwd": runtime.process_cwd(watch["pid"])}
                stopped = self.rt("usage", "watch", "stop", "--agent", "claude")
                if stopped.returncode != 0:
                    # This pid was created by this private fixture. Do not leak
                    # it even when a restricted host denies the stop identity probe.
                    try:
                        os.kill(watch["pid"], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr
                                 + json.dumps(diagnostic))
