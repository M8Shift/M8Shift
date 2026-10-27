"""Unit tests for the existing-runtime recommendation bridge."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "m8shift-routing-bridge.py"
spec = importlib.util.spec_from_file_location("routing_bridge", path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class BridgeTests(unittest.TestCase):
    @staticmethod
    def policy(effort="high"):
        return {"schema": "m8shift.routing.v1", "decision": {"effort": effort, "advisor_required": False, "human_approval_required": False}}

    def test_valid_advisory_result(self):
        policy = {"schema": "m8shift.routing.v1", "decision": {"human_approval_required": True, "advisor_required": True, "effort": "xhigh"}}
        out = bridge.merge_recommendations(policy, {
            "ok": True, "authority": "advisory", "launch": False,
            "picked": "example-model", "effort": "high"})
        self.assertEqual(out["runtime_model"], "example-model")
        self.assertTrue(out["policy"]["decision"]["human_approval_required"])
        self.assertFalse(out["launch"])
        self.assertEqual(out["effective_effort"], "xhigh")
        self.assertTrue(out["requires_manual_resolution"])

    def test_manifest_error_fails_closed(self):
        out = bridge.merge_recommendations(self.policy(), {
            "ok": False, "authority": "advisory", "launch": False,
            "reason": "routing manifest error"})
        self.assertIsNone(out["runtime_model"])
        self.assertTrue(out["requires_manual_resolution"])

    def test_refuses_runtime_launch_authority(self):
        for value in ({"authority": "executor", "launch": False},
                      {"authority": "advisory", "launch": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.merge_recommendations(self.policy(), value)

    def test_stronger_runtime_effort_wins(self):
        out = bridge.merge_recommendations(self.policy("low"), {
            "ok": True, "authority": "advisory", "launch": False,
            "picked": "example-model", "effort": "max"})
        self.assertEqual(out["effective_effort"], "max")

    def test_invalid_runtime_effort_fails_closed(self):
        out = bridge.merge_recommendations(self.policy(), {
            "ok": True, "authority": "advisory", "launch": False,
            "picked": "example-model", "effort": "unknown"})
        self.assertIsNone(out["effective_effort"])
        self.assertIn("invalid_runtime_effort", out["resolution_reasons"])

    def test_no_model_is_not_actionable(self):
        out = bridge.merge_recommendations(self.policy(), {
            "ok": True, "authority": "advisory", "launch": False, "picked": ""})
        self.assertTrue(out["requires_manual_resolution"])

if __name__ == "__main__":
    unittest.main()
