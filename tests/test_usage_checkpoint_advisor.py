"""Regression tests for optional read-only quota checkpoint advice."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ambient_env  # noqa: E402,F401 - purge before product import

MODULE = Path(__file__).resolve().parents[1] / "m8shift-usage-advisor.py"
spec = importlib.util.spec_from_file_location("m8shift_usage_advisor", MODULE)
advisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(advisor)


class CheckpointAdviceTests(unittest.TestCase):
    def report(self, classification="near_limit", stale=False, ratio=0.87):
        return {"verdict": classification, "agents": [
            {"agent": "claude", "classification": classification,
             "stale": stale, "decision_ratio": ratio}]}

    def test_fresh_near_limit_emits_unnamed_advice(self):
        result = advisor.advice(self.report())
        self.assertFalse(result["launch"])
        self.assertFalse(result["write_authorized"])
        self.assertEqual(len(result["advisories"]), 1)
        row = result["advisories"][0]
        self.assertEqual(row["action"], "checkpoint_or_cooldown")
        self.assertIsNone(row["target_agent"])
        self.assertIsNone(row["task_type"])

    def test_unknown_stale_and_limit_hit_never_emit(self):
        for state in ("unknown", "limit_hit", "ok"):
            with self.subTest(state=state):
                self.assertEqual(advisor.advice(self.report(state))["advisories"], [])
        self.assertEqual(advisor.advice(self.report(stale=True))["advisories"], [])
        self.assertEqual(advisor.advice(self.report(ratio=None))["advisories"], [])

    def test_malformed_and_duplicate_agent_refused(self):
        for report in ({"agents": []},
                       {"verdict": "near_limit", "agents": [{}]},
                       {"verdict": "near_limit", "agents": [
                           {"agent": "claude", "classification": "near_limit"},
                           {"agent": "claude", "classification": "near_limit"}]}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                advisor.advice(report)

    def test_different_windows_produce_different_keys(self):
        first = self.report()
        second = self.report()
        first["agents"][0]["decision_window"] = {"kind": "weekly", "resets_at": "2026-11-01T00:00:00Z"}
        second["agents"][0]["decision_window"] = {"kind": "weekly", "resets_at": "2026-11-08T00:00:00Z"}
        a = advisor.advice(first)["advisories"][0]["recommendation_key"]
        b = advisor.advice(second)["advisories"][0]["recommendation_key"]
        self.assertNotEqual(a, b)

    def test_inconsistent_ok_verdict_is_rejected(self):
        report = self.report()
        report["verdict"] = "ok"
        with self.assertRaisesRegex(ValueError, "inconsistent_guard_verdict"):
            advisor.advice(report)

    def test_nonfinite_ratio_never_advises(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                self.assertEqual(advisor.advice(self.report(ratio=value))["advisories"], [])

    def test_unknown_verdict_with_near_limit_row_refused(self):
        report = self.report()
        report["verdict"] = "unknown"
        with self.assertRaisesRegex(ValueError, "inconsistent_guard_verdict"):
            advisor.advice(report)

    def test_stable_recommendation_key(self):
        a = advisor.advice(self.report())["advisories"][0]
        b = advisor.advice(self.report(ratio=0.9))["advisories"][0]
        self.assertEqual(a["recommendation_key"], b["recommendation_key"])


if __name__ == "__main__":
    unittest.main()
