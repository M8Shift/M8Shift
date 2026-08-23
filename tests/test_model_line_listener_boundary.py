

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ambient_env  # noqa: E402,F401  — purge BEFORE any engine import (#288)
import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from examples.model_line_budget_adapter import (
    InvocationBoundary,
    ModelPin,
)
from examples.model_line_budget_adapter.listener import (
    LISTENER_POLICY_SCHEMA,
    BoundaryCleanHalt,
    BoundaryIntegrationError,
    perform_listener_boundary,
)


def utc(offset=0):
    value = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(
        seconds=offset
    )
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestRFC077ListenerSafeBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / ".m8shift" / "runtime"
        self.relay = self.root / "M8SHIFT.md"
        self.relay.write_text(
            "<!-- M8SHIFT:LOCK:BEGIN -->\n"
            "holder: codex\nstate: AWAITING_CODEX\nagents: claude,codex\n"
            "session: session-1\nturn: 1\n<!-- M8SHIFT:LOCK:END -->\n\n"
            "<!-- M8SHIFT:TURN 1 claude BEGIN -->\nclosed\n"
            "<!-- M8SHIFT:TURN 1 claude END -->\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def evidence(self, model, remaining, *, freshness=300, applicability="exact_model"):
        captured = utc(-10)
        return {
            "schema": "m8shift.model-line.evidence.v1",
            "provider": "example-provider",
            "mode": "api",
            "requested_model": model,
            "scope": "model",
            "applicability": applicability,
            "provider_bucket_id": "bucket-" + model,
            "used_ratio": None if remaining is None else 1 - remaining,
            "remaining_ratio": remaining,
            "reset_at": None,
            "signal": "quota_metric",
            "provenance": "documented",
            "captured_at": captured,
            "fresh_until": utc(freshness),
            "documented_mapping": None,
            "estimate": None,
            "adapter": {"name": "fixture-matrix", "version": "1"},
        }

    def configure(self, active, target, *, auto=True, target_applicability="exact_model",
                  active_provider="example-provider"):
        fixtures = self.root / "fixtures"
        fixtures.mkdir(exist_ok=True)
        (fixtures / "active.json").write_text(
            json.dumps(self.evidence("model-a", active)), encoding="utf-8"
        )
        (fixtures / "target.json").write_text(
            json.dumps(self.evidence(
                "model-b", target, applicability=target_applicability
            )), encoding="utf-8"
        )
        policy_dir = self.root / ".m8shift" / "model-line-routing"
        policy_dir.mkdir(parents=True, exist_ok=True)
        policy = {
            "schema": LISTENER_POLICY_SCHEMA,
            "policy_id": "fixture-policy",
            "active": {
                "provider": active_provider, "mode": "api",
                "auth_scope": "scope-1",
            },
            "fallbacks": [{
                "provider": "example-provider", "mode": "api",
                "auth_scope": "scope-1", "model": "model-b",
            }],
            "auto_at_safe_boundary": auto,
            "adapter": {
                "name": "fixture-matrix", "version": "1",
                "enabled": False, "retrieval": "fixture_only",
            },
            "evidence_fixtures": {
                "model-a": "fixtures/active.json",
                "model-b": "fixtures/target.json",
            },
        }
        (policy_dir / "codex.json").write_text(json.dumps(policy), encoding="utf-8")

    def perform(self, run_id, **overrides):
        values = {
            "root": str(self.root),
            "relay_path": str(self.relay),
            "runtime_dir": str(self.runtime),
            "agent": "codex",
            "active_model": "model-a",
            "run_id": run_id,
            "completed_invocations": 3,
        }
        values.update(overrides)
        return perform_listener_boundary(**values)

    def test_absent_policy_is_a_true_no_op_and_relay_bytes_are_invariant(self):
        before = self.relay.read_bytes()
        result = self.perform("run-default")
        self.assertIsNone(result)
        self.assertEqual(self.relay.read_bytes(), before)
        self.assertFalse(self.runtime.exists())

    def test_managed_provider_mismatch_is_a_stable_clean_halt(self):
        self.configure(0.0, 0.8, active_provider="other-provider")
        result = self.perform(
            "run-provider-mismatch", managed_provider="example-provider"
        )
        self.assertEqual(result.plan.action, "clean_halt")
        self.assertEqual(result.plan.reason_code, "route_provider_mismatch")
        self.assertIsNone(result.selected_pin)

    def test_listener_provider_mismatch_clean_halts_without_popen(self):
        self.configure(0.0, 0.8, active_provider="other-provider")
        runtime = self.load_runtime()
        profile = {
            "argv": ["provider", "prompt"], "cwd": str(self.root),
            "env_allowlist": [], "start_on_idle": False, "agent_model": "model-a",
            "provider_row": {
                "name": "codex", "provider": "example-provider", "mode": "headless",
                "model": "model-a", "argv": ["provider", "$M8SHIFT_PROMPT"],
            },
        }

        def boundary(**values):
            return self.perform(
                values["run_id"],
                managed_provider=values["managed_provider"],
                usage_hold=values["usage_hold"],
            )

        with mock.patch.object(runtime, "read_listener_state", return_value={}), \
                mock.patch.object(runtime, "write_listener_state") as save, \
                mock.patch.object(runtime, "remove_own_listener_pid"), \
                mock.patch.object(runtime, "read_relay_lock_fields", return_value=(
                    {"state": "AWAITING_CODEX", "holder": "codex", "session": "session-1"},
                    "relay snapshot",
                )), \
                mock.patch.object(runtime, "read_usage_hold", return_value=(None, "")), \
                mock.patch.object(runtime, "listener_completed_invocations", return_value=3), \
                mock.patch.object(runtime, "listener_route_switches", return_value=0), \
                mock.patch.object(runtime, "emit_notification_nonfatal"), \
                mock.patch.object(runtime.time, "sleep"), \
                mock.patch(
                    "examples.model_line_budget_adapter.listener.perform_listener_boundary",
                    side_effect=boundary,
                ), \
                mock.patch.object(runtime.subprocess, "Popen") as popen:
            rc = runtime.run_listener_loop(
                "codex", profile, "runner.py", poll=0, max_ticks=2,
                max_retries=1, max_backoff=1,
            )
        self.assertEqual(rc, 0)
        popen.assert_not_called()
        self.assertIn(
            "model_line_route_provider_mismatch",
            [call.kwargs.get("reason") for call in save.call_args_list],
        )

    def test_usage_hold_reaches_policy_admission_without_sidecar_writes(self):
        self.configure(0.0, 0.8)
        with self.assertRaisesRegex(BoundaryCleanHalt, "agent_usage_hold_active"):
            self.perform("run-held", usage_hold="active")
        self.assertFalse((self.runtime / "fleet" / "attempts").exists())
        self.assertFalse((self.runtime / "model-line-routing").exists())

    def test_fixture_matrix_consumes_all_eight_policy_outcomes_at_boundary(self):
        cases = (
            ("available", 0.8, 0.8, True, InvocationBoundary(), 0, "continue"),
            ("drain", 0.05, 0.8, True, InvocationBoundary(), 0,
             "route_next_invocation"),
            ("exhausted", 0.0, 0.8, True, InvocationBoundary(), 0,
             "route_next_invocation"),
            ("disabled", 0.05, 0.8, False, InvocationBoundary(), 0, "observe_only"),
            ("unknown-target", 0.0, None, True, InvocationBoundary(), 0, "clean_halt"),
            ("partial", 0.0, 0.8, True, InvocationBoundary(output_started=True), 0,
             "clean_halt"),
            ("effect", 0.0, 0.8, True, InvocationBoundary(tool_effect=True), 0,
             "clean_halt"),
            ("cap", 0.0, 0.8, True, InvocationBoundary(), 1, "clean_halt"),
        )
        for index, (name, active, target, auto, boundary, switches, action) in enumerate(
            cases, 1
        ):
            with self.subTest(name=name):
                self.configure(active, target, auto=auto)
                result = self.perform(
                    "run-%02d" % index,
                    boundary=boundary,
                    switches_completed=switches,
                )
                self.assertEqual(result.plan.action, action)

    def test_generation_guard_precedes_checkpoint_or_decision_writes(self):
        self.configure(0.0, 0.8)
        listeners = self.runtime / "listeners"
        listeners.mkdir(parents=True)
        (listeners / "codex.pid").write_text(
            json.dumps({"pid": 10, "generation": "new"}), encoding="utf-8"
        )
        (listeners / "codex.json").write_text(
            json.dumps({"process_pid": 10, "generation": "new"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(BoundaryIntegrationError, "generation"):
            self.perform("run-stale", generation="old", process_pid=10)
        self.assertFalse((self.runtime / "fleet" / "attempts").exists())

    def test_vendor_adapter_cannot_be_enabled_in_slice_d(self):
        self.configure(0.0, 0.8)
        path = self.root / ".m8shift" / "model-line-routing" / "codex.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["adapter"]["enabled"] = True
        path.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaisesRegex(BoundaryIntegrationError, "disabled"):
            self.perform("run-live-refused")

    def load_runtime(self):
        path = Path(__file__).resolve().parents[1] / "m8shift-runtime.py"
        spec = importlib.util.spec_from_file_location("m8shift_runtime_slice_d", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_routed_pin_uses_the_exact_rfc070_argv_compiler(self):
        runtime = self.load_runtime()
        row = {
            "name": "codex", "provider": "openai-codex", "mode": "headless",
            "model": "model-a", "profile": "old", "effort": "medium",
            "argv": ["codex", "exec", "$M8SHIFT_PROMPT"],
        }
        profile = {
            "argv": runtime.provider_launch_argv(row, "$M8SHIFT_PROMPT"),
            "cwd": str(self.root), "env_allowlist": [], "start_on_idle": False,
            "agent_model": "model-a", "provider_row": row,
        }
        selected = ModelPin(
            "openai-codex", "subscription_cli", "scope-1", "model-b",
            profile="new", effort="high",
        )
        argv = runtime.listener_runner_argv(
            "codex", profile, "runner.py", "run-rfc070", selected_pin=selected
        )
        self.assertEqual(argv[argv.index("--cmd") + 1:], [
            "codex", "exec", "--profile", "new", "--model", "model-b",
            "--config", 'model_reasoning_effort="high"',
            runtime.LISTENER_TURN_PROMPT.format(
                agent="codex", agent_upper="CODEX"
            ),
        ])
        self.assertEqual(argv[argv.index("--agent-model") + 1], "model-b")

    def test_listener_hold_gate_runs_before_boundary_controller(self):
        runtime = self.load_runtime()
        profile = {
            "argv": ["provider", "prompt"], "cwd": str(self.root),
            "env_allowlist": [], "start_on_idle": False, "agent_model": "model-a",
        }
        with mock.patch.object(runtime, "read_listener_state", return_value={}), \
                mock.patch.object(runtime, "write_listener_state"), \
                mock.patch.object(runtime, "remove_own_listener_pid"), \
                mock.patch.object(runtime, "read_relay_lock_fields", return_value=(
                    {"state": "AWAITING_CODEX", "holder": "codex", "session": "session-1"},
                    "relay snapshot",
                )), \
                mock.patch.object(runtime, "read_usage_hold", return_value=({
                    "resets_at": utc(300)
                }, "")), \
                mock.patch.object(runtime.time, "sleep"), \
                mock.patch(
                    "examples.model_line_budget_adapter.listener.perform_listener_boundary"
                ) as boundary_call, \
                mock.patch.object(runtime.subprocess, "Popen") as popen:
            rc = runtime.run_listener_loop(
                "codex", profile, "runner.py", poll=0, max_ticks=1,
                max_retries=1, max_backoff=1,
            )
        self.assertEqual(rc, 0)
        boundary_call.assert_not_called()
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
