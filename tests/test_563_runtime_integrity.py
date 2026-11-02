"""Focused regression tests for #563 runtime integrity/lifecycle fixes."""
import importlib.util
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product import

RUNTIME = Path(__file__).resolve().parents[1] / "m8shift-runtime.py"
spec = importlib.util.spec_from_file_location("m8shift_runtime_563_test", RUNTIME)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeIntegrityTests(unittest.TestCase):
    def test_restore_timeout_override_is_bounded_and_restore_only(self):
        with mock.patch.dict(os.environ, {runtime.LISTENER_RESTORE_TIMEOUT_ENV: "0.25"}, clear=False):
            self.assertEqual(runtime.listener_start_observe_timeout(True), 0.25)
            self.assertEqual(runtime.listener_start_observe_timeout(False),
                             runtime.LISTENER_START_OBSERVE_TIMEOUT_S)
        for value in ("", "0", "-1", "nan", "inf", "garbage"):
            with self.subTest(value=value), mock.patch.dict(
                    os.environ, {runtime.LISTENER_RESTORE_TIMEOUT_ENV: value}, clear=False):
                self.assertEqual(runtime.listener_start_observe_timeout(True),
                                 runtime.LISTENER_START_OBSERVE_TIMEOUT_S)

    def test_listener_started_at_tracks_process_identity_and_preserves_origin(self):
        original = runtime.LISTENERS_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime.LISTENERS_DIR = tmp
                with mock.patch.object(runtime, "current_relay_session", return_value="session-test"), \
                        mock.patch.object(runtime, "iso", side_effect=[
                            "2026-01-01T00:00:01Z",
                            "2026-01-01T00:00:02Z",
                            "2026-01-01T00:00:03Z"]):
                    first = runtime.write_listener_state(
                        "claude", phase="polling", consecutive_failures=0,
                        generation="gen-a", process_pid=101)
                    same = runtime.write_listener_state(
                        "claude", phase="polling", consecutive_failures=0,
                        generation="gen-a", process_pid=101)
                    restarted = runtime.write_listener_state(
                        "claude", phase="polling", consecutive_failures=0,
                        generation="gen-b", process_pid=202)
                self.assertEqual(first["started_at"], "2026-01-01T00:00:01Z")
                self.assertEqual(first["first_started_at"], "2026-01-01T00:00:01Z")
                self.assertEqual(same["started_at"], first["started_at"])
                self.assertEqual(same["first_started_at"], first["first_started_at"])
                self.assertEqual(restarted["started_at"], "2026-01-01T00:00:03Z")
                self.assertEqual(restarted["first_started_at"], first["first_started_at"])
        finally:
            runtime.LISTENERS_DIR = original

    def test_runtime_doctor_delegation_is_read_only_by_contract(self):
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('kit_check = getattr(core, "_kit_doctor_findings", None)', source)
        self.assertIn('findings.extend(kit_check())', source)


if __name__ == "__main__":
    unittest.main()
