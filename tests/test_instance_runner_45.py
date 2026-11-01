"""Runtime/runner propagation tests for holder-instance binding (#564)."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load(ROOT / "m8shift-runtime.py", "m8shift_runtime_instance_test")
runner = load(ROOT / "examples" / "headless_runner.py", "m8shift_runner_instance_test")


class RuntimeRunnerInstanceTests(unittest.TestCase):
    def test_managed_listener_instance_is_safe_and_stable(self):
        a = runtime.listener_managed_instance_env("claude", "abc123")
        b = runtime.listener_managed_instance_env("claude", "abc123")
        self.assertEqual(a["M8SHIFT_INSTANCE"], "listener-claude-abc123")
        self.assertEqual(a["M8SHIFT_INSTANCE"], b["M8SHIFT_INSTANCE"])
        self.assertEqual(a["M8SHIFT_INSTANCE_MODE"], "managed")

    def test_reservation_passes_instance_to_core(self):
        captured = {}
        def fake_run(argv, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        env = runtime.listener_managed_instance_env("claude", "generation")
        with mock.patch.object(runtime.subprocess, "run", side_effect=fake_run):
            ok, _why = runtime.reserve_turn_before_launch("claude", env)
        self.assertTrue(ok)
        self.assertEqual(captured["env"]["M8SHIFT_INSTANCE"],
                         "listener-claude-generation")

    def test_runner_child_inherits_held_instance_and_mode(self):
        plan = {
            "env_allowlist": [],
            "run_id": "run-1",
            "agent": "claude",
            "agent_model": "",
            "resume_working": True,
        }
        lock = {
            "holder": "claude", "turn": "7",
            "holder_instance": "listener-claude-generation",
            "holder_mode": "managed",
        }
        env = runner.child_env_for_plan(plan, lock, str(ROOT / "m8shift.py"))
        self.assertEqual(env["M8SHIFT_INSTANCE"], "listener-claude-generation")
        self.assertEqual(env["M8SHIFT_INSTANCE_MODE"], "managed")

    def test_resume_working_rejects_foreign_instance(self):
        args = SimpleNamespace(resume_working=True)
        lock = {
            "holder": "claude",
            "state": "WORKING_CLAUDE",
            "holder_instance": "original",
        }
        with mock.patch.dict(os.environ, {"M8SHIFT_INSTANCE": "foreign"}, clear=False):
            with self.assertRaises(SystemExit) as raised:
                runner.resume_eligible(args, "claude", "WORKING_CLAUDE", lock)
        self.assertEqual(raised.exception.code, 5)

    def test_resume_working_accepts_matching_and_legacy_instances(self):
        args = SimpleNamespace(resume_working=True)
        matched = {"holder": "claude", "state": "WORKING_CLAUDE",
                   "holder_instance": "original"}
        with mock.patch.dict(os.environ, {"M8SHIFT_INSTANCE": "original"}, clear=False):
            self.assertTrue(runner.resume_eligible(
                args, "claude", "WORKING_CLAUDE", matched))
        legacy = {"holder": "claude", "state": "WORKING_CLAUDE"}
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(runner.resume_eligible(
                args, "claude", "WORKING_CLAUDE", legacy))


if __name__ == "__main__":
    unittest.main()
