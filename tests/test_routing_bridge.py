"""Unit tests for the existing-runtime recommendation bridge."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "m8shift-routing-bridge.py"
spec = importlib.util.spec_from_file_location("routing_bridge", path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class BridgeTests(unittest.TestCase):
    def test_valid_advisory_result(self):
        policy = {"decision": {"human_approval_required": True}}
        out = bridge.merge_recommendations(policy, {
            "ok": True, "authority": "advisory", "launch": False,
            "picked": "example-model", "effort": "high"})
        self.assertEqual(out["runtime_model"], "example-model")
        self.assertTrue(out["policy"]["decision"]["human_approval_required"])
        self.assertFalse(out["launch"])

    def test_manifest_error_fails_closed(self):
        out = bridge.merge_recommendations({}, {
            "ok": False, "authority": "advisory", "launch": False,
            "reason": "routing manifest error"})
        self.assertIsNone(out["runtime_model"])
        self.assertTrue(out["requires_manual_resolution"])

    def test_refuses_runtime_launch_authority(self):
        for value in ({"authority": "executor", "launch": False},
                      {"authority": "advisory", "launch": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.merge_recommendations({}, value)

    def test_no_model_is_not_actionable(self):
        out = bridge.merge_recommendations({}, {
            "ok": True, "authority": "advisory", "launch": False, "picked": ""})
        self.assertTrue(out["requires_manual_resolution"])

if __name__ == "__main__":
    unittest.main()
