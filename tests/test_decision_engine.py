"""Regression tests for the optional deterministic decision engine."""
import importlib.util
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before importing the product

MODULE = Path(__file__).resolve().parents[1] / "m8shift-decision.py"
spec = importlib.util.spec_from_file_location("m8shift_decision", MODULE)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

class DecisionTests(unittest.TestCase):
    def test_simple_task_is_economical(self):
        d = engine.decide("Locate a definition")
        self.assertEqual(d["decision"]["model_tier"], "economy")
        self.assertFalse(d["decision"]["advisor_required"])

    def test_critical_task_requires_human(self):
        d = engine.decide("Migrate production data", risk="critical", budget="economy")
        self.assertEqual(d["decision"]["effort"], "max")
        self.assertTrue(d["decision"]["human_approval_required"])
        self.assertEqual(d["decision"]["strategy"], "direct")

    def test_repeated_failures_escalate(self):
        d = engine.decide("Fix failing test", failures=2)
        self.assertTrue(d["decision"]["advisor_required"])
        self.assertEqual(d["decision"]["model_tier"], "advanced")

    def test_four_failures_use_max(self):
        self.assertEqual(engine.decide("Fix", failures=4)["decision"]["effort"], "max")

    def test_parallel_requires_independence_and_low_risk(self):
        self.assertEqual(engine.decide("Inspect modules", independent_parts=True)["decision"]["strategy"], "parallel")
        self.assertEqual(engine.decide("Inspect modules", risk="high", independent_parts=True)["decision"]["strategy"], "direct")

    def test_invalid_inputs_rejected(self):
        for kwargs in ({"failures": -1}, {"failures": True}, {"risk": "unknown"}, {"budget": "cheap"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                engine.decide("Task", **kwargs)
        with self.assertRaises(ValueError):
            engine.decide("  ")

    def test_escalated_task_never_parallelizes(self):
        for kwargs in ({"failures": 2}, {"complexity": "high"}, {"risk": "high"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(engine.decide("Task", independent_parts=True, **kwargs)["decision"]["strategy"], "direct")

    def test_task_text_is_not_returned(self):
        import json
        self.assertNotIn("PRIVATE_TASK_SENTINEL", json.dumps(engine.decide("PRIVATE_TASK_SENTINEL")))

    def test_repeatable(self):
        self.assertEqual(engine.decide("Same task", has_tests=True), engine.decide("Same task", has_tests=True))

if __name__ == "__main__":
    unittest.main()
