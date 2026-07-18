import json
import unittest
from pathlib import Path

from examples.model_line_budget_adapter import (
    EVIDENCE_SCHEMA,
    ModelLineBudgetAdapter,
    ModelLineEvidence,
    ProbeTarget,
    RefusalObservation,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples" / "model_line_budget_adapter"
FIXTURES = PACKAGE / "fixtures"
SCHEMAS = PACKAGE / "schema"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class FixtureAdapter(ModelLineBudgetAdapter):
    def __init__(self, payload):
        self.payload = payload

    def probe(self, target):
        return ModelLineEvidence.from_payload(self.payload)

    def classify_refusal(self, observation):
        payload = dict(self.payload)
        payload["signal"] = "rejection"
        payload["captured_at"] = observation.captured_at
        payload["fresh_until"] = observation.captured_at
        return ModelLineEvidence.from_payload(payload)


class WrongTargetAdapter(FixtureAdapter):
    def probe(self, target):
        payload = dict(self.payload)
        payload["requested_model"] = "another-model"
        return ModelLineEvidence.from_payload(payload)


class TestModelLineBudgetAdapterConformance(unittest.TestCase):
    def test_base_class_is_abstract(self):
        with self.assertRaises(TypeError):
            ModelLineBudgetAdapter()

    def test_fixture_adapter_serializes_exact_schema(self):
        payload = load_json(FIXTURES / "anthropic-null-bucket.json")
        target = ProbeTarget("anthropic", "api", "model-sonnet-example")
        normalized = FixtureAdapter(payload).probe_payload(target)
        self.assertEqual(normalized, payload)
        self.assertEqual(normalized["schema"], EVIDENCE_SCHEMA)
        self.assertIsNone(normalized["provider_bucket_id"])
        self.assertEqual(normalized["applicability"], "documented_group")

    def test_adapter_cannot_return_evidence_for_another_target(self):
        payload = load_json(FIXTURES / "anthropic-null-bucket.json")
        target = ProbeTarget("anthropic", "api", "model-sonnet-example")
        with self.assertRaisesRegex(ValueError, "does not match"):
            WrongTargetAdapter(payload).probe_payload(target)

    def test_refusal_observation_is_bounded_and_serializes_rejection(self):
        payload = load_json(FIXTURES / "anthropic-null-bucket.json")
        observation = RefusalObservation(
            target=ProbeTarget("anthropic", "api", "model-sonnet-example"),
            captured_at="2026-07-18T17:03:00Z",
            output_started=False,
            tool_effect=False,
            retry_safe=True,
            status_code=429,
            provider_code="rate_limit",
        )
        normalized = FixtureAdapter(payload).refusal_payload(observation)
        self.assertEqual(normalized["signal"], "rejection")
        self.assertNotIn("raw_body", normalized)
        self.assertNotIn("credentials", normalized)

    def test_unknown_keys_and_invalid_freshness_fail_closed(self):
        payload = load_json(FIXTURES / "anthropic-null-bucket.json")
        payload["access_token"] = "forbidden"
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            ModelLineEvidence.from_payload(payload)

        payload.pop("access_token")
        payload["fresh_until"] = "2026-07-18T16:59:59Z"
        with self.assertRaisesRegex(ValueError, "must not precede"):
            ModelLineEvidence.from_payload(payload)

    def test_freshness_is_deterministic_from_injected_time(self):
        payload = load_json(FIXTURES / "anthropic-null-bucket.json")
        evidence = ModelLineEvidence.from_payload(payload)
        self.assertEqual(evidence.freshness("2026-07-18T17:00:30Z"), "fresh")
        self.assertEqual(evidence.freshness("2026-07-18T17:01:01Z"), "stale")

    def test_three_way_regression_fixture_remains_three_independent_facts(self):
        fixture = load_json(FIXTURES / "three-way-split.json")
        account = ModelLineEvidence.from_payload(fixture["account"])
        model_a = ModelLineEvidence.from_payload(fixture["model_a"])
        model_b = ModelLineEvidence.from_payload(fixture["model_b"])

        self.assertGreater(account.remaining_ratio, 0)
        self.assertEqual(model_a.remaining_ratio, 0)
        self.assertIsNone(model_b.remaining_ratio)
        self.assertEqual(
            {account.requested_model, model_a.requested_model, model_b.requested_model},
            {"account-aggregate", "model-a", "model-b"},
        )

    def test_vendor_honesty_fixtures_do_not_promote_aggregate_or_console_data(self):
        codex = ModelLineEvidence.from_payload(
            load_json(FIXTURES / "codex-aggregate-unknown.json")
        )
        gemini = ModelLineEvidence.from_payload(
            load_json(FIXTURES / "gemini-console-only.json")
        )
        self.assertEqual(codex.applicability, "unknown")
        self.assertEqual(codex.scope, "account")
        self.assertEqual(gemini.provenance, "console_only")
        self.assertIsNone(gemini.remaining_ratio)

    def test_checked_in_schemas_and_route_fixture_pin_contract_ids(self):
        evidence_schema = load_json(
            SCHEMAS / "m8shift.model-line.evidence.v1.schema.json"
        )
        route_schema = load_json(SCHEMAS / "m8shift.route-decision.v1.schema.json")
        route = load_json(FIXTURES / "route-decision-switch.json")
        self.assertEqual(evidence_schema["$id"], EVIDENCE_SCHEMA)
        self.assertEqual(route_schema["$id"], "m8shift.route-decision.v1")
        self.assertEqual(route["schema"], route_schema["$id"])
        self.assertEqual(set(route), set(route_schema["required"]))
        self.assertEqual(route["checkpoint"]["next_invocation"], 4)
        self.assertEqual(route["switch_ordinal"], 1)


if __name__ == "__main__":
    unittest.main()
