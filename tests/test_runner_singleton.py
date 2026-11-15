"""Per-root, per-agent runner ownership and corroborated pickup coverage (#564)."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401
from tests import test_m8shift as base


class RunnerSingletonTests(base.CLIBase):
    RUNNER = str(Path(base.REPO, "examples/headless_runner.py"))

    def _runner_pid_path(self, agent):
        return os.path.join(
            self.d, ".m8shift", "runtime", "runner-%s.pid" % agent)

    def _runner_argv(self, agent, *extra, code="pass"):
        return [
            sys.executable, self.RUNNER, agent,
            "--m8shift", "M8SHIFT.md", "--m8shift-py", "m8shift.py",
            "--interval", "30", *extra,
            "--cmd", sys.executable, "-c", code,
        ]

    def _stop_waiting_runner(self, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

    def _wait_for_runner_pid(self, agent, expected_pid, proc, timeout=5):
        path = self._runner_pid_path(agent)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                self.fail(
                    "runner exited before publishing its PID: %s" %
                    (stdout + stderr))
            try:
                with open(path, encoding="utf-8") as fh:
                    if fh.read().strip() == str(expected_pid):
                        return path
            except (FileNotFoundError, OSError):
                pass
            time.sleep(0.02)
        self.fail("runner did not publish PID %s at %s" % (expected_pid, path))

    def _start_waiting_runner(self, agent):
        proc = subprocess.Popen(
            self._runner_argv(agent), cwd=self.d,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._stop_waiting_runner, proc)
        self._wait_for_runner_pid(agent, proc.pid, proc)
        return proc

    @staticmethod
    def _complete_idle_turn_code(agent, peer):
        return (
            "import subprocess, sys\n"
            "m = [sys.executable, 'm8shift.py']\n"
            "subprocess.check_call(m + ['claim', %r])\n"
            "subprocess.check_call(m + ['append', %r, '--to', %r, "
            "'--done', 'singleton test'])\n" % (agent, agent, peer)
        )

    def test_runner_singleton_refuses_second_live_instance_for_same_agent(self):
        self.init()
        first = self._start_waiting_runner("claude")
        second = subprocess.run(
            self._runner_argv(
                "claude", "--start-on-idle", "--once",
                code=self._complete_idle_turn_code("claude", "codex")),
            cwd=self.d, capture_output=True, text=True, timeout=8)
        refusal = second.stdout + second.stderr
        self.assertEqual(second.returncode, 5, refusal)
        self.assertIn("already running", refusal)
        self.assertIn("PID %s" % first.pid, refusal)
        self.assertEqual(self.lock()["state"], "IDLE")

    def test_runner_singleton_reclaims_stale_pid_after_kill(self):
        self.init()
        first = self._start_waiting_runner("claude")
        path = self._runner_pid_path("claude")
        first.kill()
        first.wait(timeout=5)
        self.assertTrue(os.path.isfile(path), "SIGKILL must leave the stale PID witness")

        replacement = subprocess.run(
            self._runner_argv(
                "claude", "--start-on-idle", "--once",
                code=self._complete_idle_turn_code("claude", "codex")),
            cwd=self.d, capture_output=True, text=True, timeout=8)
        self.assertEqual(replacement.returncode, 0,
                         replacement.stdout + replacement.stderr)
        self.assertEqual(self.lock()["state"], "AWAITING_CODEX")
        self.assertFalse(os.path.exists(path))

    def test_runner_singleton_is_scoped_per_agent(self):
        self.init()
        first = self._start_waiting_runner("claude")
        second = subprocess.run(
            self._runner_argv(
                "codex", "--start-on-idle", "--once",
                code=self._complete_idle_turn_code("codex", "claude")),
            cwd=self.d, capture_output=True, text=True, timeout=8)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIsNone(first.poll(), "the other agent's runner was disturbed")
        self.assertEqual(self.lock()["state"], "AWAITING_CLAUDE")

    def test_runner_singleton_removes_pid_file_on_termination_signal(self):
        self.init()
        proc = self._start_waiting_runner("claude")
        path = self._runner_pid_path("claude")
        proc.terminate()
        proc.wait(timeout=5)
        deadline = time.monotonic() + 2
        while os.path.exists(path) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(os.path.exists(path))

    def test_status_correlates_coverage_with_locked_runner_singleton(self):
        self.init()
        proc = self._start_waiting_runner("claude")
        handed_off = self.turn("codex", "claude", done="runner coverage fixture")
        self.assertEqual(handed_off.returncode, 0,
                         handed_off.stdout + handed_off.stderr)
        self.assertNotIn("advisory:", handed_off.stdout)

        payload = json.loads(self.cw("status", "--json").stdout)
        attention = payload["snapshot"]["attention"]["claude"]
        self.assertEqual(
            (attention["producer_coverage"], attention["source"],
             attention["relay_attention"]),
            ("invoker", "runner", "covered"))

        proc.terminate()
        proc.wait(timeout=5)
        path = self._runner_pid_path("claude")
        deadline = time.monotonic() + 2
        while os.path.exists(path) and time.monotonic() < deadline:
            time.sleep(0.02)
        with open(path, "w", encoding="ascii") as fh:
            fh.write(str(os.getpid()) + "\n")
        stale = json.loads(self.cw("status", "--json").stdout)
        stale_attention = stale["snapshot"]["attention"]["claude"]
        self.assertEqual(
            (stale_attention["producer_coverage"], stale_attention["source"],
             stale_attention["relay_attention"]),
            ("absent", "none", "human_resume_needed"))


    def test_root_alias_conflicts_but_a_distinct_relay_is_independent(self):
        self.init()
        first = self._start_waiting_runner("claude")
        with tempfile.TemporaryDirectory(prefix="m8shift-runner-roots-") as parent:
            alias = os.path.join(parent, "alias")
            try:
                os.symlink(self.d, alias, target_is_directory=True)
            except OSError:
                self.skipTest("host cannot create a directory alias")
            duplicate = subprocess.run(
                self._runner_argv("claude", "--start-on-idle", "--once"),
                cwd=alias, capture_output=True, text=True, timeout=8)
            self.assertEqual(duplicate.returncode, 5, duplicate.stdout + duplicate.stderr)
            self.assertEqual(self.lock()["state"], "IDLE")
            other = os.path.join(parent, "other")
            shutil.copytree(self.d, other, ignore=shutil.ignore_patterns(".m8shift"))
            independent = subprocess.run(
                self._runner_argv("claude", "--start-on-idle", "--once",
                                  code=self._complete_idle_turn_code("claude", "codex")),
                cwd=other, capture_output=True, text=True, timeout=8)
            self.assertEqual(independent.returncode, 0,
                             independent.stdout + independent.stderr)
            self.assertIsNone(first.poll())
            self.assertEqual(self.lock()["state"], "IDLE")
