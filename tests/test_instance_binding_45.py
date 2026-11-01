"""Regression tests for optional holder-instance binding (#564 first slice)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product execution

ROOT = Path(__file__).resolve().parents[1]


class HolderInstanceBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="m8shift-instance-binding-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy(ROOT / "m8shift.py", self.root / "m8shift.py")
        init = self.run("init")
        self.assertEqual(init.returncode, 0, init.stderr)

    def run(self, *args, instance=None, mode="managed"):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("M8SHIFT_INSTANCE", None)
        env.pop("M8SHIFT_INSTANCE_MODE", None)
        if instance is not None:
            env["M8SHIFT_INSTANCE"] = instance
            env["M8SHIFT_INSTANCE_MODE"] = mode
        return subprocess.run(
            [sys.executable, "-B", "m8shift.py", *args],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=20)

    def relay_bytes(self):
        return (self.root / "M8SHIFT.md").read_bytes()

    def lock(self):
        text = (self.root / "M8SHIFT.md").read_text(encoding="utf-8")
        start = text.index("<!-- M8SHIFT:LOCK:BEGIN -->")
        end = text.index("<!-- M8SHIFT:LOCK:END -->", start)
        result = {}
        for line in text[start:end].splitlines():
            if ":" in line and not line.lstrip().startswith("<!--"):
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
        return result

    def test_bound_claim_records_instance_and_matching_append_clears_it(self):
        claimed = self.run("claim", "claude", instance="lane-001", mode="managed")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        lock = self.lock()
        self.assertEqual(lock["holder_instance"], "lane-001")
        self.assertEqual(lock["holder_mode"], "managed")

        appended = self.run(
            "append", "claude", "--to", "codex", "--done", "ok",
            instance="lane-001")
        self.assertEqual(appended.returncode, 0, appended.stderr)
        lock = self.lock()
        self.assertNotIn("holder_instance", lock)
        self.assertNotIn("holder_mode", lock)

    def test_foreign_instance_is_refused_without_mutation(self):
        claimed = self.run("claim", "claude", instance="lane-original")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        before = self.relay_bytes()

        attempts = (
            ("claim", "claude", "--refresh"),
            ("append", "claude", "--to", "codex", "--done", "must refuse"),
            ("heartbeat", "claude", "--source", "wrapper", "--cadence-seconds", "1"),
            ("work-tag", "claude", "ticket-564"),
            ("pause", "claude", "--reason", "test"),
            ("release", "claude", "--to", "codex"),
            ("done", "claude"),
        )
        for argv in attempts:
            with self.subTest(argv=argv):
                result = self.run(*argv, instance="lane-foreign")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("M8SHIFT_INSTANCE", result.stderr + result.stdout)
                self.assertEqual(self.relay_bytes(), before)

    def test_legacy_unbound_window_remains_compatible(self):
        claimed = self.run("claim", "claude")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        lock = self.lock()
        self.assertNotIn("holder_instance", lock)
        refreshed = self.run("claim", "claude", "--refresh")
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        appended = self.run("append", "claude", "--to", "codex", "--done", "legacy")
        self.assertEqual(appended.returncode, 0, appended.stderr)

    def test_invalid_instance_is_refused_before_write(self):
        before = self.relay_bytes()
        result = self.run("claim", "claude", instance="bad instance")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("M8SHIFT_INSTANCE", result.stderr + result.stdout)
        self.assertEqual(self.relay_bytes(), before)

    def test_bound_window_requires_declared_instance_for_may_i_write(self):
        claimed = self.run("claim", "claude", instance="lane-guarded")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        missing = self.run("may-i-write", "claude")
        self.assertEqual(missing.returncode, 3)
        matching = self.run("may-i-write", "claude", instance="lane-guarded")
        self.assertEqual(matching.returncode, 0, matching.stdout + matching.stderr)


if __name__ == "__main__":
    unittest.main()
