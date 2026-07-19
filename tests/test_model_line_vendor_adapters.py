import json
import unittest
from pathlib import Path

from examples.model_line_budget_adapter import (
    AnthropicModelLineBudgetAdapter,
    GoogleModelLineBudgetAdapter,
    MistralModelLineBudgetAdapter,
    ModelLineBudgetAdapter,
    OpenAIModelLineBudgetAdapter,
    ProbeTarget,
    RefusalObservation,
    VENDOR_ADAPTER_REGISTRY,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "model_line_budget_adapter" / "fixtures"
FIXED_NOW = "2026-07-19T10:00:00Z"


def load_cases(vendor):
    path = FIXTURES / (vendor + "-responses.json")
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_retriever(payload):
    return lambda _target: dict(payload)


VENDORS = (
    (
        "anthropic",
        AnthropicModelLineBudgetAdapter,
        ProbeTarget("anthropic", "api", "model-sonnet-example"),
    ),
    (
        "openai",
        OpenAIModelLineBudgetAdapter,
        ProbeTarget("openai", "api", "model-gpt-example"),
    ),
    (
        "google",
        GoogleModelLineBudgetAdapter,
        ProbeTarget("google", "cloud", "model-gemini-example"),
    ),
    (
        "mistral",
        MistralModelLineBudgetAdapter,
        ProbeTarget("mistral", "api", "model-mistral-example"),
    ),
)


class TestVendorAdapterRegistration(unittest.TestCase):
    def test_all_vendor_adapters_are_external_subclasses_and_disabled(self):
        self.assertEqual(
            set(VENDOR_ADAPTER_REGISTRY),
            {
                "anthropic-model-line",
                "openai-model-line",
                "google-model-line",
                "mistral-model-line",
            },
        )
        for registration in VENDOR_ADAPTER_REGISTRY.values():
            self.assertFalse(registration.enabled)
            self.assertEqual(registration.retrieval, "fixture_only")
            self.assertTrue(issubclass(registration.adapter_class, ModelLineBudgetAdapter))


class TestVendorAdapterConformance(unittest.TestCase):
    def adapter(self, adapter_class, payload):
        return adapter_class(fixture_retriever(payload), clock=lambda: FIXED_NOW)

    def test_success_fixtures_preserve_vendor_specific_applicability(self):
        anthropic = self.adapter(
            AnthropicModelLineBudgetAdapter, load_cases("anthropic")["success"]
        ).probe_payload(ProbeTarget("anthropic", "api", "model-sonnet-example"))
        self.assertEqual(anthropic["applicability"], "documented_group")
        self.assertIsNone(anthropic["provider_bucket_id"])
        self.assertEqual(anthropic["remaining_ratio"], 0.8)

        openai = self.adapter(
            OpenAIModelLineBudgetAdapter, load_cases("openai")["success"]
        ).probe_payload(ProbeTarget("openai", "api", "model-gpt-example"))
        self.assertEqual(openai["applicability"], "documented_group")
        self.assertEqual(openai["provider_bucket_id"], "provider-group-gpt-example")
        self.assertEqual(openai["remaining_ratio"], 0.75)

        google = self.adapter(
            GoogleModelLineBudgetAdapter, load_cases("google")["success"]
        ).probe_payload(ProbeTarget("google", "cloud", "model-gemini-example"))
        self.assertEqual(google["applicability"], "exact_model")
        self.assertEqual(google["remaining_ratio"], 0.6)
        self.assertEqual(google["signal"], "quota_metric")

        mistral = self.adapter(
            MistralModelLineBudgetAdapter, load_cases("mistral")["success"]
        ).probe_payload(ProbeTarget("mistral", "api", "model-mistral-example"))
        self.assertIsNone(mistral["used_ratio"])
        self.assertIsNone(mistral["remaining_ratio"])
        self.assertEqual(mistral["estimate"]["used_ratio"], 0.6)
        self.assertEqual(mistral["estimate"]["remaining_ratio"], 0.4)

    def test_every_vendor_has_success_throttle_malformed_and_auth_absent(self):
        for vendor, adapter_class, target in VENDORS:
            with self.subTest(vendor=vendor):
                cases = load_cases(vendor)
                self.assertTrue(
                    {"success", "throttle", "malformed", "auth_absent"}.issubset(cases)
                )
                for case in ("success", "throttle", "malformed", "auth_absent"):
                    payload = self.adapter(adapter_class, cases[case]).probe_payload(target)
                    self.assertEqual(payload["schema"], "m8shift.model-line.evidence.v1")
                    self.assertEqual(payload["provider"], vendor)
                    self.assertEqual(payload["requested_model"], target.requested_model)

    def test_malformed_and_auth_absent_degrade_to_unknown_without_headroom(self):
        for vendor, adapter_class, target in VENDORS:
            for case in ("malformed", "auth_absent"):
                with self.subTest(vendor=vendor, case=case):
                    evidence = self.adapter(
                        adapter_class, load_cases(vendor)[case]
                    ).probe_payload(target)
                    self.assertEqual(evidence["applicability"], "unknown")
                    self.assertEqual(evidence["provenance"], "unknown")
                    self.assertIsNone(evidence["used_ratio"])
                    self.assertIsNone(evidence["remaining_ratio"])
                    self.assertIsNone(evidence["provider_bucket_id"])

    def test_throttle_fixtures_only_claim_applicability_when_the_surface_maps_it(self):
        expected = {
            "anthropic": ("documented_group", None),
            "openai": ("documented_group", "provider-group-gpt-example"),
            "google": (
                "exact_model",
                "generativelanguage.googleapis.com/model-example-requests",
            ),
            "mistral": ("unknown", None),
        }
        for vendor, adapter_class, target in VENDORS:
            with self.subTest(vendor=vendor):
                evidence = self.adapter(
                    adapter_class, load_cases(vendor)["throttle"]
                ).probe_payload(target)
                self.assertEqual(evidence["signal"], "rejection")
                self.assertEqual(evidence["applicability"], expected[vendor][0])
                self.assertEqual(evidence["provider_bucket_id"], expected[vendor][1])
                if vendor == "mistral":
                    self.assertIsNone(evidence["remaining_ratio"])
                else:
                    self.assertEqual(evidence["remaining_ratio"], 0.0)

    def test_subscription_aggregate_and_google_console_only_stay_diagnostic(self):
        anthropic = self.adapter(
            AnthropicModelLineBudgetAdapter, load_cases("anthropic")["success"]
        ).probe_payload(
            ProbeTarget("anthropic", "subscription_cli", "model-sonnet-example")
        )
        openai = self.adapter(
            OpenAIModelLineBudgetAdapter, load_cases("openai")["success"]
        ).probe_payload(
            ProbeTarget("openai", "subscription_cli", "model-gpt-example")
        )
        console = self.adapter(
            GoogleModelLineBudgetAdapter, load_cases("google")["console_only"]
        ).probe_payload(ProbeTarget("google", "cloud", "model-gemini-example"))
        self.assertEqual(anthropic["applicability"], "unknown")
        self.assertEqual(openai["applicability"], "unknown")
        self.assertEqual(console["applicability"], "unknown")
        self.assertEqual(console["provenance"], "console_only")
        self.assertIsNone(console["remaining_ratio"])

    def test_response_cannot_invent_an_openai_shared_group(self):
        response = dict(load_cases("openai")["success"])
        response["shared_group"] = "unlisted-group"
        response["provider_bucket_id"] = "attacker-chosen-bucket"
        evidence = self.adapter(
            OpenAIModelLineBudgetAdapter, response
        ).probe_payload(ProbeTarget("openai", "api", "model-gpt-example"))
        self.assertEqual(evidence["applicability"], "unknown")
        self.assertIsNone(evidence["provider_bucket_id"])
        self.assertIsNone(evidence["documented_mapping"])

    def test_retrieval_failure_and_bounded_refusal_degrade_honestly(self):
        def fail(_target):
            raise RuntimeError("fixture retriever failed")

        for vendor, adapter_class, target in VENDORS:
            with self.subTest(vendor=vendor):
                adapter = adapter_class(fail, clock=lambda: FIXED_NOW)
                evidence = adapter.probe_payload(target)
                self.assertEqual(evidence["applicability"], "unknown")
                self.assertIsNone(evidence["remaining_ratio"])

                refusal = adapter.refusal_payload(
                    RefusalObservation(
                        target=target,
                        captured_at=FIXED_NOW,
                        output_started=False,
                        tool_effect=False,
                        retry_safe=True,
                        status_code=429,
                        provider_code="rate_limit",
                    )
                )
                self.assertEqual(refusal["signal"], "rejection")
                self.assertEqual(refusal["applicability"], "unknown")
                self.assertNotIn("provider_code", refusal)

    def test_adapter_rejects_a_target_for_another_provider(self):
        adapter = self.adapter(
            AnthropicModelLineBudgetAdapter, load_cases("anthropic")["success"]
        )
        with self.assertRaisesRegex(ValueError, "adapter provider"):
            adapter.probe_payload(ProbeTarget("openai", "api", "model-gpt-example"))


if __name__ == "__main__":
    unittest.main()
