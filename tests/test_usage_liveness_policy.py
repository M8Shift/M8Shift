"""Regression witnesses for usage-watcher liveness policy (#404).

These tests exercise the shipped runtime's pure health/reconcile decisions.
They do not start, stop, or signal any actual watcher.
"""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - isolate ambient relay state

RUNTIME = Path(__file__).resolve().parents[1] / "m8shift-runtime.py"
spec = importlib.util.spec_from_file_location("m8shift_runtime_liveness_test", RUNTIME)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def watch(*, pid=888888, phase="running", desired="running", lease="test-lease"):
    return {
        "schema": runtime.USAGE_WATCH_SCHEMA,
        "kind": "usage_watch",
        "agent": "claude",
        "phase": phase,
        "desired_state": desired,
        "pid": pid,
        "lease_id": lease,
        "process_start_ref": "",
        "interval": 60,
        "started": "",
        "last_tick": "",
        "last_success": "",
        "consecutive_unknown": 0,
    }


class WatcherLivenessPolicyTests(unittest.TestCase):
    def test_dead_running_watcher_requires_reconciliation(self):
        stale = watch()
        health = runtime.usage_watch_health(stale, pid_probe=lambda _pid: False)
        self.assertEqual(health["status"], "dead")
        plan = runtime.usage_watch_reconcile_decision(
            stale, pid_probe=lambda _pid: False)
        self.assertEqual(plan["action"], "start")

    def test_explicit_stop_must_not_restart(self):
        stopped = watch(phase="stopped", desired="stopped")
        plan = runtime.usage_watch_reconcile_decision(
            stopped, pid_probe=lambda _pid: False)
        self.assertEqual(plan["action"], "keep_stopped")

    def test_malformed_registry_must_not_be_started(self):
        plan = runtime.usage_watch_reconcile_decision(
            {"schema": "unknown", "desired_state": "running"},
            pid_probe=lambda _pid: False)
        self.assertEqual(plan["action"], "investigate")

    def test_unverifiable_process_identity_fails_closed(self):
        running = watch()
        running["process_start_ref"] = "original"
        with mock.patch.object(runtime, "fleet_process_start_ref", return_value=""):
            health = runtime.usage_watch_health(
                running, pid_probe=lambda _pid: True)
        self.assertEqual(health["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
