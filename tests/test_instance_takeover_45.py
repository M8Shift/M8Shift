"""Regression tests for explicit audited same-agent instance takeover (#564)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]


class InstanceTakeoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="m8shift-instance-takeover-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy(ROOT / "m8shift.py", self.root / "m8shift.py")
        init = self.cli("init")
        self.assertEqual(init.returncode, 0, init.stderr)

    def cli(self, *args, instance=None, mode="manual"):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("M8SHIFT_INSTANCE", None)
        env.pop("M8SHIFT_INSTANCE_MODE", None)
        if instance is not None:
            env["M8SHIFT_INSTANCE"] = instance
            env["M8SHIFT_INSTANCE_MODE"] = mode
        return subprocess.run(
            [sys.executable, "-B", "m8shift.py", *args],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=20)

    def relay(self):
        return (self.root / "M8SHIFT.md").read_bytes()

    def lock(self):
        text = (self.root / "M8SHIFT.md").read_text(encoding="utf-8")
        begin = text.index("<!-- M8SHIFT:LOCK:BEGIN -->")
        end = text.index("<!-- M8SHIFT:LOCK:END -->", begin)
        row = {}
        for line in text[begin:end].splitlines():
            if ":" in line and not line.lstrip().startswith("<!--"):
                key, value = line.split(":", 1)
                row[key.strip()] = value.strip()
        return row

    def events(self):
        path = self.root / "M8SHIFT.sessions.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def claim_original(self):
        result = self.cli("claim", "claude", instance="manual-original")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lock().get("holder_instance"), "manual-original")

    def test_explicit_takeover_rebinds_and_records_adjacent_evidence(self):
        self.claim_original()
        result = self.cli(
            "claim", "claude", "--takeover-instance",
            "--reason", "operator moved work to replacement process",
            instance="manual-replacement")
        self.assertEqual(result.returncode, 0, result.stderr)
        lock = self.lock()
        self.assertEqual(lock["holder_instance"], "manual-replacement")
        self.assertEqual(lock["holder_mode"], "manual")
        rows = self.events()
        self.assertGreaterEqual(len(rows), 2)
        state, audit = rows[-2:]
        self.assertEqual(state["event"], "state")
        self.assertEqual(state["operation"], "instance-takeover")
        self.assertEqual(audit["event"], "instance_change")
        self.assertEqual(audit["basis"], "operator-decision")
        self.assertEqual(audit["displaced_instance"], "manual-original")
        self.assertEqual(audit["arriving_instance"], "manual-replacement")
        self.assertEqual(audit["reason"], "operator moved work to replacement process")
        self.assertEqual(audit["previous_work_window_id"], state["previous_work_window_id"])
        self.assertEqual(audit["work_window_id"], state["work_window_id"])

    def test_takeover_requires_reason_and_declared_instance_without_mutation(self):
        self.claim_original()
        before = self.relay()
        missing_reason = self.cli(
            "claim", "claude", "--takeover-instance",
            instance="manual-replacement")
        self.assertNotEqual(missing_reason.returncode, 0)
        self.assertEqual(self.relay(), before)
        missing_instance = self.cli(
            "claim", "claude", "--takeover-instance",
            "--reason", "operator decision")
        self.assertNotEqual(missing_instance.returncode, 0)
        self.assertEqual(self.relay(), before)

    def test_takeover_refuses_same_instance_and_nonworking_state(self):
        self.claim_original()
        same = self.cli(
            "claim", "claude", "--takeover-instance",
            "--reason", "not actually a takeover",
            instance="manual-original")
        self.assertNotEqual(same.returncode, 0)
        self.assertIn("same-name WORKING", same.stderr + same.stdout)

    def test_fresh_protective_heartbeat_blocks_foreign_takeover(self):
        self.claim_original()
        beat = self.cli(
            "heartbeat", "claude", "--source", "test", "--cadence-seconds", "60",
            instance="manual-original")
        self.assertEqual(beat.returncode, 0, beat.stderr)
        before = self.relay()
        takeover = self.cli(
            "claim", "claude", "--takeover-instance",
            "--reason", "operator decision",
            instance="manual-replacement")
        self.assertNotEqual(takeover.returncode, 0)
        self.assertIn("appears alive", takeover.stderr + takeover.stdout)
        self.assertEqual(self.relay(), before)

    def test_takeover_flags_are_mutually_exclusive(self):
        self.claim_original()
        before = self.relay()
        for extra in (("--force",), ("--refresh",), ("--check",)):
            with self.subTest(extra=extra):
                result = self.cli(
                    "claim", "claude", "--takeover-instance",
                    "--reason", "operator decision", *extra,
                    instance="manual-replacement")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mutually exclusive", result.stderr + result.stdout)
                self.assertEqual(self.relay(), before)


if __name__ == "__main__":
    unittest.main()
