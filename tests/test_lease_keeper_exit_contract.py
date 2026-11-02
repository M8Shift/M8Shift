"""Deterministic witnesses for child-exit races in protective lease heartbeats."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product import

CORE = Path(__file__).resolve().parents[1] / "m8shift.py"
spec = importlib.util.spec_from_file_location("keeper_core_contract", CORE)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class KeeperExitContractTests(unittest.TestCase):
    def test_child_exit_during_refresh_prevents_protective_beat(self):
        for exit_code in (0, 9, -15):
            proc = mock.Mock()
            proc.poll.return_value = exit_code
            with self.subTest(exit_code=exit_code), \
                    mock.patch.object(core, "_lease_keeper_core", return_value=(True, 0, "")) as control:
                result = core._lease_keeper_step("claude", 1, {}, proc=proc)
                self.assertEqual(result, (True, 0, "child-exited", ""))
                control.assert_called_once_with({}, "claim", "claude", "--refresh")
                proc.poll.assert_called_once_with()

    def test_live_child_gets_refresh_then_protective_beat(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(core, "_lease_keeper_core", return_value=(True, 0, "")) as control:
            result = core._lease_keeper_step("claude", 1, {}, proc=proc)
        self.assertEqual(result, (True, 0, "heartbeat", ""))
        self.assertEqual(control.call_args_list, [
            mock.call({}, "claim", "claude", "--refresh"),
            mock.call({}, "heartbeat", "claude", "--source", "wrapper", "--cadence-seconds", "1"),
        ])

    def test_refresh_failure_never_emits_a_protective_beat(self):
        proc = mock.Mock()
        with mock.patch.object(core, "_lease_keeper_core", return_value=(False, 3, "refused")) as control:
            result = core._lease_keeper_step("claude", 1, {}, proc=proc)
        self.assertEqual(result, (False, 3, "claim --refresh", "refused"))
        self.assertEqual(control.call_count, 1)
        proc.poll.assert_not_called()

    def test_child_exiting_before_first_beat_preserves_exit_code_and_never_reads_heartbeat(self):
        proc = mock.Mock()
        proc.poll.return_value = 9
        proc.wait.return_value = 9
        with mock.patch.object(core, "_shell_free_argv", return_value=["fixture-child"]), \
                mock.patch.object(core, "cmd_may_i_write", return_value=0), \
                mock.patch.object(core, "_guarded_child_env", return_value={}), \
                mock.patch.object(core, "_lease_keeper_core", return_value=(True, 0, "")) as control, \
                mock.patch.object(core.subprocess, "Popen", return_value=proc):
            result = core.cmd_lease_keeper(SimpleNamespace(agent="claude", cadence_seconds=1))
        self.assertEqual(result, 9)
        control.assert_called_once_with({}, "claim", "claude", "--refresh")


if __name__ == "__main__":
    unittest.main()
