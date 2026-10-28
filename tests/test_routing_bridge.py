"""Adverse cases and genuine native-runtime integration for the advisory bridge."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before importing the product

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "m8shift-routing-bridge.py"
spec = importlib.util.spec_from_file_location("routing_bridge", PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
engine = bridge.load_decision()


def catalog():
    return {
        "schema": "m8shift.routing.models.v1", "authority": "advisory", "enabled": True,
        "tiers": ["economy", "balanced", "flagship"],
        "cost_bands": ["$", "$$", "$$$", "$$$$"],
        "latency_bands": ["fast", "medium", "slow"],
        "context_classes": ["small", "large", "xlarge"],
        "models": [
            {"id": "fixture-small", "provider": "fixture-a", "tier": "economy",
             "cost_band": "$", "latency": "fast", "context_class": "small",
             "capabilities": ["read_repo"]},
            {"id": "fixture-balanced", "provider": "fixture-b", "tier": "balanced",
             "cost_band": "$$", "latency": "medium", "context_class": "large",
             "capabilities": ["read_repo", "write_repo", "review"]},
            {"id": "fixture-large", "provider": "fixture-c", "tier": "flagship",
             "cost_band": "$$$", "latency": "slow", "context_class": "xlarge",
             "capabilities": ["read_repo", "write_repo", "review"]},
        ],
    }


def native_result():
    rows = catalog()["models"]
    return {
        "ok": True, "route": "recommend", "authority": "advisory", "launch": False,
        "task_type": "fixture-edit", "picked": rows[0]["id"], "effort": "low",
        "floor": "economy", "downgradable": True,
        "required_capabilities": ["read_repo"], "required_context_class": "small",
        "feasible": [{key: row[key] for key in ("id", "tier", "cost_band", "latency", "context_class")}
                     for row in rows], "findings": [],
    }


class BridgeTests(unittest.TestCase):
    def merge(self, policy=None, runtime=None, models=None):
        return bridge.merge_recommendations(
            policy if policy is not None else engine.decide("Task"),
            runtime if runtime is not None else native_result(),
            models_manifest=models if models is not None else catalog())

    def test_resolved_plan_remains_non_executable(self):
        result = self.merge()
        self.assertEqual(result["resolution_status"], "resolved")
        self.assertFalse(result["launch"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["requires_manual_resolution"])
        self.assertEqual(result["compatible_model"], "fixture-small")
        self.assertEqual(result["compatibility_evidence"]["provider_availability"], "not_probed")

    def test_risk_escalation_selects_flagship_and_preserves_review(self):
        result = self.merge(engine.decide("Task", risk="critical", budget="economy"))
        self.assertEqual(result["compatible_model"], "fixture-large")
        self.assertEqual(result["effective_effort"], "max")
        self.assertEqual(result["resolution_status"], "review_required")
        self.assertIn("human_approval_required", result["resolution_reasons"])
        self.assertIn("advisor_required", result["resolution_reasons"])

    def test_all_effort_pairs_never_downgrade(self):
        for left in bridge.EFFORT_ORDER:
            for right in bridge.EFFORT_ORDER:
                with self.subTest(left=left, right=right):
                    policy, runtime = engine.decide("Task"), native_result()
                    policy["decision"]["effort"], runtime["effort"] = left, right
                    result = self.merge(policy, runtime)
                    self.assertEqual(result["effective_effort"],
                                     max((left, right), key=bridge.EFFORT_ORDER.index))

    def test_native_floor_is_not_lowered(self):
        runtime = native_result()
        runtime["floor"] = "flagship"
        result = self.merge(runtime=runtime)
        self.assertEqual(result["required_tier"], "flagship")
        self.assertEqual(result["compatible_model"], "fixture-large")

    def test_pinned_native_route_requires_advisor_and_direct_strategy(self):
        runtime = native_result()
        runtime["downgradable"] = False
        result = self.merge(engine.decide("Task", independent_parts=True), runtime)
        self.assertEqual(result["effective_strategy"], "direct")
        self.assertIn("advisor_required", result["resolution_reasons"])

    def test_capability_requirement_is_checked_against_catalog(self):
        runtime = native_result()
        runtime["required_capabilities"] = ["write_repo"]
        self.assertEqual(self.merge(runtime=runtime)["compatible_model"], "fixture-balanced")
        runtime["required_capabilities"] = ["not_available"]
        result = self.merge(runtime=runtime)
        self.assertIsNone(result["compatible_model"])
        self.assertEqual(result["resolution_status"], "blocked")

    def test_context_requirement_is_checked_against_catalog(self):
        runtime = native_result()
        runtime["required_context_class"] = "xlarge"
        self.assertEqual(self.merge(runtime=runtime)["compatible_model"], "fixture-large")

    def test_tier_without_catalog_is_not_evidence(self):
        result = bridge.merge_recommendations(engine.decide("Task"), native_result())
        self.assertIsNone(result["compatible_model"])
        self.assertEqual(result["resolution_status"], "blocked")

    def test_rejects_forged_or_duplicate_feasible_rows(self):
        for mutation in ("unknown", "tier", "context", "duplicate"):
            runtime = native_result()
            row = runtime["feasible"][0]
            if mutation == "unknown":
                row["id"] = "fabricated"
            elif mutation == "tier":
                row["tier"] = "flagship"
            elif mutation == "context":
                row["context_class"] = "xlarge"
            else:
                runtime["feasible"].append(copy.deepcopy(row))
            with self.subTest(mutation=mutation):
                result = self.merge(runtime=runtime)
                self.assertIn("feasible_catalog_mismatch", result["resolution_reasons"])
                self.assertIsNone(result["compatible_model"])

    def test_success_shaped_runtime_failure_is_blocked(self):
        for mutation in ("empty_feasible", "missing_model", "error_finding", "bad_effort"):
            runtime = native_result()
            if mutation == "empty_feasible":
                runtime["feasible"] = []
            elif mutation == "missing_model":
                runtime["picked"] = ""
            elif mutation == "error_finding":
                runtime["findings"] = [{"severity": "error"}]
            else:
                runtime["effort"] = "invented"
            with self.subTest(mutation=mutation):
                self.assertEqual(self.merge(runtime=runtime)["resolution_status"], "blocked")

    def test_authority_and_boolean_types_are_strict(self):
        for key, value in (("authority", "executor"), ("launch", 0), ("launch", True),
                           ("ok", 1), ("ok", "true"), ("route", "execute")):
            runtime = native_result()
            runtime[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.merge(runtime=runtime)
        for key in ("advisor_required", "human_approval_required"):
            policy = engine.decide("Task")
            policy["decision"][key] = "false"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge(policy=policy)

    def test_unknown_order_and_disabled_catalog_refuse(self):
        for key, value in (("tiers", ["flagship", "balanced", "economy"]),
                           ("tiers", None), ("enabled", False), ("enabled", "true")):
            models = catalog()
            models[key] = value
            with self.subTest(key=key, value=value):
                self.assertEqual(self.merge(models=models)["resolution_status"], "blocked")

    def test_malformed_policy_has_named_refusal(self):
        for key, value in (("model_tier", []), ("effort", None), ("strategy", "shell")):
            policy = engine.decide("Task")
            policy["decision"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "invalid_decision_policy"):
                self.merge(policy=policy)

    def test_json_refuses_ambiguous_or_oversized_values(self):
        for data in (b'{"ok": true, "ok": false}', b'{"x": NaN}', b'[]',
                     b'{' * 10000, b' ' * (bridge.MAX_JSON_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                bridge._decode_json(data)

    def test_inputs_are_not_mutated(self):
        policy, runtime, models = engine.decide("Task"), native_result(), catalog()
        before = copy.deepcopy((policy, runtime, models))
        self.merge(policy, runtime, models)
        self.assertEqual((policy, runtime, models), before)

    def test_timeout_and_token_bounds_reject_before_runtime(self):
        for timeout in (True, 0, -1, 61, float("inf"), float("nan"), "15"):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "invalid_timeout"):
                bridge.recommend("Task", "fixture-edit", timeout=timeout)
        for tokens in (True, -1, 1.5, 10000001):
            with self.subTest(tokens=tokens), self.assertRaisesRegex(ValueError, "invalid_input_tokens"):
                bridge.recommend("Task", "fixture-edit", input_tokens=tokens)

    def test_native_subprocess_timeout_is_bounded(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            bridge._run_runtime([sys.executable, "-c", "import time; time.sleep(10)"], REPO, 0.1)

    def test_native_exit_status_must_match_json(self):
        for rc, ok in ((0, False), (1, True)):
            command = [sys.executable, "-c", f"print('{{\"ok\": {str(ok).lower()}}}'); raise SystemExit({rc})"]
            with self.subTest(rc=rc), self.assertRaisesRegex(RuntimeError, "runtime_exit_status_mismatch"):
                bridge._run_runtime(command, REPO, 5)


class BridgeNativeIntegrationTests(unittest.TestCase):
    """Exercise the shipped core and runtime, not a replacement router."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m8shift-bridge-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy2(REPO / "m8shift.py", self.root / "m8shift.py")
        env = {k: v for k, v in os.environ.items() if not k.startswith("M8SHIFT_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run([sys.executable, "-B", str(self.root / "m8shift.py"),
                               "init", "--name", "bridge-fixture", "--agents", "alpha,beta"],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.routing = self.root / ".m8shift" / "routing"
        self.routing.mkdir(parents=True, exist_ok=True)
        self.models = catalog()
        self.write_models()
        self.skills = {
            "schema": "m8shift.routing.skills.v1", "authority": "advisory", "enabled": True,
            "defaults": {"min_model": "economy", "optimum_model": "balanced", "effort": "low",
                         "downgradable": True, "required_capabilities": ["read_repo"],
                         "required_context_class": "small", "verify": ["scoped tests"]},
            "task_types": {"fixture-edit": {}, "fixture-write": {"required_capabilities": ["write_repo"]},
                           "adversarial-verify": {"min_model": "flagship", "optimum_model": "flagship",
                                                  "effort": "xhigh", "downgradable": False,
                                                  "required_capabilities": ["review"]}},
        }
        (self.routing / "skills.json").write_text(json.dumps(self.skills), encoding="utf-8")

    def write_models(self):
        (self.routing / "models.json").write_text(json.dumps(self.models), encoding="utf-8")

    def fingerprint(self):
        return {str(path.relative_to(self.root)): (hashlib.sha256(path.read_bytes()).hexdigest(),
                                                   path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def cli(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("M8SHIFT_")}
        return subprocess.run([sys.executable, "-B", str(PATH), "PRIVATE_TASK_SENTINEL",
                               "--project-root", str(self.root), "--task-type", "fixture-edit", *args],
                              cwd=REPO, env=env, capture_output=True, text=True, timeout=20)

    def test_real_cli_resolves_without_writes_or_task_disclosure(self):
        before = self.fingerprint()
        proc = self.cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["compatible_model"], "fixture-small")
        self.assertEqual(result["resolution_status"], "resolved")
        self.assertFalse(result["launch"])
        self.assertNotIn("PRIVATE_TASK_SENTINEL", proc.stdout + proc.stderr)
        self.assertNotIn(str(self.root), proc.stdout + proc.stderr)
        self.assertEqual(self.fingerprint(), before)
        self.assertEqual(result["manifest_digests"]["models"],
                         hashlib.sha256((self.routing / "models.json").read_bytes()).hexdigest())

    def test_real_runtime_honors_tokens_and_capabilities(self):
        result = bridge.recommend("Task", "fixture-write", project_root=self.root, input_tokens=100000)
        self.assertEqual(result["compatible_model"], "fixture-large")
        self.assertIn("write_repo", result["compatibility_evidence"]["capabilities"])
        self.assertEqual(result["compatibility_evidence"]["context_class"], "xlarge")

    def test_critical_risk_exits_review_required_not_success(self):
        proc = self.cli("--risk", "critical")
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["compatible_model"], "fixture-large")

    def test_native_pinned_task_requires_review_even_with_low_hint(self):
        result = bridge.recommend("Task", "adversarial-verify", project_root=self.root)
        self.assertEqual(result["resolution_status"], "review_required")
        self.assertEqual(result["effective_effort"], "xhigh")
        self.assertEqual(result["effective_strategy"], "direct")

    def test_native_fallback_cannot_be_success(self):
        proc = self.cli("--task-type", "unknown-task")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["resolution_status"], "blocked")

    def test_unavailable_tier_cannot_be_success(self):
        self.models["models"] = self.models["models"][:1]
        self.write_models()
        proc = self.cli("--complexity", "high")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIsNone(json.loads(proc.stdout)["compatible_model"])

    def test_disabled_and_corrupt_manifests_refuse_without_writes(self):
        for content in ('{"schema":"wrong"}', '{"enabled":true,"enabled":false}', 'null'):
            (self.routing / "models.json").write_text(content)
            before = self.fingerprint()
            proc = self.cli()
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertEqual(self.fingerprint(), before)

    def test_conflicting_instance_binding_refuses_before_subprocess(self):
        with mock.patch.dict(os.environ, {"M8SHIFT_ROOT": str(REPO)}), \
                mock.patch.object(bridge, "_run_runtime") as run:
            with self.assertRaisesRegex(ValueError, "conflicting_project_roots"):
                bridge.recommend("Task", "fixture-edit", project_root=self.root)
            run.assert_not_called()

    def test_manifests_changed_during_native_call_refuse(self):
        def changed(*args):
            self.models["models"][0]["capabilities"].append("unexpected")
            self.write_models()
            return native_result()
        with mock.patch.object(bridge, "_run_runtime", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "routing_manifest_changed_during_read"):
                bridge.recommend("Task", "fixture-edit", project_root=self.root)

    def test_task_type_mismatch_refuses(self):
        bad = native_result()
        bad["task_type"] = "other"
        with mock.patch.object(bridge, "_run_runtime", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "runtime_task_type_mismatch"):
                bridge.recommend("Task", "fixture-edit", project_root=self.root)

    def test_ambient_empty_root_refuses(self):
        with mock.patch.dict(os.environ, {"M8SHIFT_ROOT": " "}):
            with self.assertRaisesRegex(ValueError, "empty_environment_root"):
                bridge.recommend("Task", "fixture-edit", project_root=self.root)

    def test_no_implicit_fallback_to_engine_directory(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(ValueError, "project_root_not_initialized"):
                bridge.recommend("Task", "fixture-edit", project_root=empty)


if __name__ == "__main__":
    unittest.main()
