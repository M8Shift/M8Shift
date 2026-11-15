"""Concurrent listener startup, crash release and exception recovery (#564)."""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401
from tests import test_m8shift as base


class ListenerStartupTransactionTests(base.ListenerCLIBase):
    def _load_runtime(self):
        spec = importlib.util.spec_from_file_location("runtime_start_transaction", self.RUNTIME)
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        return runtime

    def test_concurrent_detached_starts_have_one_spawn_and_one_winner(self):
        """#427: two parents past preflight must not both spawn one lane."""
        runtime = self._load_runtime()
        listeners = os.path.join(self.d, "startup-race")
        args = argparse.Namespace(
            agent="claude", from_plan=False, poll_interval=1.0, max_ticks=0,
            max_retries=1, max_backoff=1, backend="local", runner="",
            restart=False, foreground=False, service_payload=False,
            dry_run=False, notify_only=False, force=False,
            allow_ephemeral_runner=True, grace=0,
        )
        profile = {"start_on_idle": False, "review_delivery": "none"}
        entered = threading.Event()
        release = threading.Event()
        spawn_calls = []
        results = []

        def spawn(*_args):
            spawn_calls.append(threading.get_ident())
            entered.set()
            release.wait(5)
            os.makedirs(listeners, exist_ok=True)
            with open(os.path.join(listeners, "claude.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"phase": "polling"}, fh)
            return 4200 + len(spawn_calls), {"process_start_ref": "test"}

        def start():
            try:
                results.append(runtime.cmd_listener_start(args))
            except SystemExit as exc:
                results.append(exc)

        patches = (
            mock.patch.object(runtime, "LISTENERS_DIR", listeners),
            mock.patch.object(runtime, "listener_backend_probe", return_value={}),
            mock.patch.object(runtime, "select_listener_backend", return_value=("local", "")),
            mock.patch.object(runtime, "load_listener_profile", return_value=profile),
            mock.patch.object(runtime, "listener_root_metadata"),
            mock.patch.object(runtime, "listener_starters", return_value={}),
            mock.patch.object(runtime, "require_runner_handshake"),
            mock.patch.object(runtime, "build_listener_plan", return_value={}),
            mock.patch.object(runtime, "write_json_atomic"),
            mock.patch.object(runtime, "read_listener_pid", return_value=(False, None)),
            mock.patch.object(runtime, "listener_process_census", return_value=[]),
            mock.patch.object(runtime, "spawn_detached_listener", side_effect=spawn),
        )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            first = threading.Thread(target=start)
            second = threading.Thread(target=start)
            first.start()
            self.assertTrue(entered.wait(5), "first start never reached spawn")
            second.start()
            second.join(0.25)
            release.set()
            first.join(5)
            second.join(5)

        self.assertEqual(len(spawn_calls), 1, results)
        self.assertEqual(sum(result == 0 for result in results), 1, results)
        refusals = [result for result in results if isinstance(result, SystemExit)]
        self.assertEqual(len(refusals), 1, results)
        self.assertIn("startup transaction", str(refusals[0]))

    def test_listener_start_transaction_is_released_by_owner_crash(self):
        """#427: a dead starter cannot strand a false live startup claim."""
        listeners = os.path.join(self.d, "startup-crash")
        code = """
import importlib.util
import sys
import time
spec = importlib.util.spec_from_file_location("runtime_crash_owner", sys.argv[1])
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
runtime.LISTENERS_DIR = sys.argv[2]
runtime.acquire_listener_start_transaction("claude")
print("locked", flush=True)
time.sleep(60)
"""
        owner = subprocess.Popen(
            [sys.executable, "-c", code, self.RUNTIME, listeners],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(owner.stdout.readline().strip(), "locked")
            owner.kill()
            owner.communicate(timeout=5)
            runtime = self._load_runtime()
            with mock.patch.object(runtime, "LISTENERS_DIR", listeners):
                transaction = runtime.acquire_listener_start_transaction("claude")
                runtime.release_listener_start_transaction(transaction)
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.communicate()

    def test_listener_start_transaction_is_released_after_exception(self):
        """#427: a transient startup exception cannot poison the next attempt."""
        runtime = self._load_runtime()
        listeners = os.path.join(self.d, "startup-exception")
        args = argparse.Namespace(
            agent="claude", from_plan=False, poll_interval=1.0, max_ticks=0,
            max_retries=1, max_backoff=1, backend="local", runner="",
            restart=False, foreground=False, service_payload=False,
            dry_run=False, notify_only=False, force=False,
            allow_ephemeral_runner=True, grace=0,
        )
        profile = {"start_on_idle": False, "review_delivery": "none"}

        def spawn(*_args):
            os.makedirs(listeners, exist_ok=True)
            with open(os.path.join(listeners, "claude.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"phase": "polling"}, fh)
            return 4200, {"process_start_ref": "test"}

        patches = (
            mock.patch.object(runtime, "LISTENERS_DIR", listeners),
            mock.patch.object(runtime, "listener_backend_probe", return_value={}),
            mock.patch.object(runtime, "select_listener_backend",
                              return_value=("local", "")),
            mock.patch.object(runtime, "load_listener_profile", return_value=profile),
            mock.patch.object(runtime, "listener_root_metadata"),
            mock.patch.object(runtime, "listener_starters", return_value={}),
            mock.patch.object(runtime, "require_runner_handshake"),
            mock.patch.object(runtime, "build_listener_plan", return_value={}),
            mock.patch.object(runtime, "write_json_atomic"),
            mock.patch.object(runtime, "read_listener_pid",
                              side_effect=[OSError("disk hiccup"), (False, None)]),
            mock.patch.object(runtime, "listener_process_census", return_value=[]),
            mock.patch.object(runtime, "spawn_detached_listener", side_effect=spawn),
        )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            with self.assertRaisesRegex(OSError, "disk hiccup"):
                runtime.cmd_listener_start(args)
            self.assertEqual(runtime.cmd_listener_start(args), 0)
