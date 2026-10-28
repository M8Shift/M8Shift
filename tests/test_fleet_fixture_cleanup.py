"""Failed-start cleanup and an independently exercised process-leak witness."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product/harness import
import _fleet_fixture_cleanup as cleanup
import test_m8shift as harness


@unittest.skipUnless(shutil.which("ps"), "process census requires POSIX ps")
class FleetCleanupTests(unittest.TestCase):
    def test_census_detects_owned_child_and_ignores_other_roots(self):
        with tempfile.TemporaryDirectory(prefix="m8shift-fleet-upgrade-target-") as root, \
                tempfile.TemporaryDirectory() as unrelated:
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)",
                                      str(Path(root) / "m8shift-runtime.py")],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.assertIn(child.pid, cleanup.owned_listener_processes([root]))
                self.assertEqual(cleanup.owned_listener_processes([unrelated]), [])
            finally:
                child.terminate()
                child.wait(timeout=5)
            self.assertEqual(cleanup.owned_listener_processes([root]), [])

    def test_census_failure_is_not_reported_as_no_processes(self):
        with mock.patch.object(cleanup.subprocess, "run", side_effect=OSError("unavailable")):
            with self.assertRaisesRegex(AssertionError, "census unavailable"):
                cleanup.owned_listener_processes(["/fixture-only"])

    def test_cleanup_reports_failed_stop_even_when_no_process_survives(self):
        with tempfile.TemporaryDirectory() as root:
            case = harness.TestRFC081FleetUpgrade(methodName="runTest")
            case.targets, case.releases = [root], []
            case.live_listeners = [(root, "claude")]
            with mock.patch.object(cleanup.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)), \
                    mock.patch.object(cleanup, "owned_listener_processes", return_value=[]):
                with self.assertRaisesRegex(AssertionError, "listener stop failed"):
                    case.cleanup_fleet_resources()

    def test_leaked_process_prevents_silent_fixture_deletion(self):
        with tempfile.TemporaryDirectory() as root:
            case = harness.TestRFC081FleetUpgrade(methodName="runTest")
            case.targets, case.releases, case.live_listeners = [root], [], []
            with mock.patch.object(cleanup, "owned_listener_processes", return_value=[4242]):
                with self.assertRaisesRegex(AssertionError, "process leak"):
                    case.cleanup_fleet_resources()
            self.assertTrue(Path(root).exists())

    def test_real_listener_is_cleaned_when_start_reports_failure_after_daemonizing(self):
        case = harness.TestRFC081FleetUpgrade(methodName="runTest")
        case.setUp()
        real_run = subprocess.run
        spawned_roots = []

        def fail_after_start(command, *args, **kwargs):
            if "listener" in command and "start" in command:
                root = os.path.realpath(kwargs["cwd"])
                self.assertIn((root, "claude"), case.live_listeners,
                              "cleanup must be registered before launching")
                result = real_run(command, *args, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                spawned_roots.append(root)
                raise subprocess.TimeoutExpired(command, 15)
            return real_run(command, *args, **kwargs)

        try:
            release, _digest = case.make_release()
            with mock.patch.object(harness.subprocess, "run", side_effect=fail_after_start):
                with self.assertRaises(subprocess.TimeoutExpired):
                    case.make_target(release, "cleanup-witness", paused=False, notify_agent="claude")
            self.assertTrue(spawned_roots)
            self.assertTrue(cleanup.owned_listener_processes(spawned_roots),
                            "positive control: a listener must really have been launched")
        finally:
            try:
                case.tearDown()
            finally:
                cleanup_ok = case.doCleanups()
            self.assertTrue(cleanup_ok, "registered fleet cleanup failed")
        self.assertEqual(cleanup.owned_listener_processes(spawned_roots), [])
        self.assertTrue(all(not Path(root).exists() for root in spawned_roots))


if __name__ == "__main__":
    unittest.main()
