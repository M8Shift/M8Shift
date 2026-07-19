import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from examples.model_line_budget_adapter import (
    DECISION_SCHEMA,
    DurableCheckpoint,
    EvidenceRef,
    InvocationBoundary,
    ModelLineEvidence,
    ModelPin,
    OperatorPolicy,
    compile_dry_run_plan,
    decide_route,
    evidence_state,
    immutable_decision_path,
    reconstruct_boundary,
    write_immutable_decision,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "model_line_budget_adapter" / "fixtures"
NOW = "2026-07-18T17:01:00Z"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


class TestRFC077PureRoutePolicy(unittest.TestCase):
    def setUp(self):
        fixture = load_json(FIXTURES / "three-way-split.json")
        self.account = ModelLineEvidence.from_payload(fixture["account"])
        self.active = ModelLineEvidence.from_payload(fixture["model_a"])
        self.target_unknown = ModelLineEvidence.from_payload(fixture["model_b"])
        self.target = replace(
            self.target_unknown,
            remaining_ratio=0.75,
            used_ratio=0.25,
            signal="response_header",
            provenance="documented",
        )
        self.active_pin = ModelPin("example-provider", "api", "scope-1", "model-a")
        self.target_pin = ModelPin("example-provider", "api", "scope-1", "model-b")
        self.policy = OperatorPolicy(
            "policy-1",
            fallbacks=(self.target_pin,),
            auto_at_safe_boundary=True,
        )

    def decide(self, **overrides):
        values = {
            "active_pin": self.active_pin,
            "active_evidence": self.active,
            "target_evidence": {"model-b": self.target},
            "policy": self.policy,
            "now": NOW,
        }
        values.update(overrides)
        return decide_route(**values)

    def test_rule_zero_active_and_corrupt_holds_precede_evidence(self):
        for hold, reason in (
            ("active", "agent_usage_hold_active"),
            ("corrupt", "agent_usage_hold_corrupt"),
        ):
            with self.subTest(hold=hold):
                decision = self.decide(
                    active_evidence=None,
                    target_evidence={},
                    usage_hold=hold,
                )
                self.assertEqual(decision.action, "clean_halt")
                self.assertEqual(decision.reason_code, reason)
                self.assertEqual(decision.active_state, "not_observed")
                self.assertFalse(decision.record_allowed)

    def test_rule_one_active_available_continues(self):
        decision = self.decide(active_evidence=replace(self.active, remaining_ratio=0.8))
        self.assertEqual((decision.action, decision.reason_code),
                         ("continue", "active_available"))
        self.assertIsNone(decision.selected_pin)

    def test_rule_two_drain_selects_first_fresh_automatable_pin(self):
        first = ModelPin("example-provider", "api", "scope-1", "model-c")
        policy = replace(self.policy, fallbacks=(first, self.target_pin))
        draining = replace(self.active, remaining_ratio=0.05)
        decision = self.decide(
            active_evidence=draining,
            target_evidence={"model-c": replace(
                self.target, requested_model="model-c", fresh_until="2026-07-18T17:00:30Z"
            ), "model-b": self.target},
            policy=policy,
        )
        self.assertEqual(decision.action, "route_next_invocation")
        self.assertEqual(decision.reason_code, "active_drain_target_available")
        self.assertEqual(decision.selected_pin, self.target_pin)
        self.assertEqual(decision.candidate_states,
                         (("model-c", "stale"), ("model-b", "available")))

    def test_rule_three_exhaustion_and_safe_refusal_route_next_only(self):
        exhausted = self.decide()
        refused = self.decide(
            active_evidence=replace(self.active, remaining_ratio=0.8, signal="rejection"),
            boundary=InvocationBoundary(refusal=True),
        )
        self.assertEqual(exhausted.reason_code,
                         "active_exhausted_target_available")
        self.assertEqual(refused.reason_code,
                         "refusal_before_output_target_available")
        self.assertEqual(refused.action, "route_next_invocation")

    def test_rule_four_partial_effect_ambiguity_and_unsafe_refusal_halt(self):
        cases = (
            (InvocationBoundary(output_started=True), "partial_stream_present"),
            (InvocationBoundary(tool_effect=True), "tool_effect_present"),
            (InvocationBoundary(ambiguous_completion=True), "ambiguous_completion"),
            (InvocationBoundary(refusal=True, retry_safe=False),
             "refusal_not_retry_safe"),
        )
        for boundary, reason in cases:
            with self.subTest(reason=reason):
                decision = self.decide(boundary=boundary)
                self.assertEqual(decision.action, "clean_halt")
                self.assertEqual(decision.reason_code, reason)
                self.assertFalse(decision.retryable)

    def test_rule_four_missing_checkpoint_halts_before_selection(self):
        decision = self.decide(checkpoint_present=False)
        self.assertEqual((decision.action, decision.reason_code),
                         ("clean_halt", "checkpoint_missing"))
        self.assertTrue(decision.retryable)

    def test_rule_five_unknown_stale_and_console_targets_never_route(self):
        console = replace(
            self.target,
            remaining_ratio=None,
            provenance="console_only",
            signal="console",
        )
        cases = (self.target_unknown, console, replace(
            self.target, fresh_until="2026-07-18T17:00:30Z"
        ))
        for evidence in cases:
            with self.subTest(state=evidence_state(evidence, NOW, 0.1)):
                decision = self.decide(target_evidence={"model-b": evidence})
                self.assertEqual(decision.action, "clean_halt")
                self.assertEqual(decision.reason_code, "target_evidence_unusable")
                self.assertTrue(decision.retryable)

    def test_rule_six_active_unknown_and_stale_preserve_fail_open(self):
        cases = (replace(self.active, remaining_ratio=None), replace(
            self.active, fresh_until="2026-07-18T17:00:30Z"
        ))
        for evidence in cases:
            with self.subTest(state=evidence_state(evidence, NOW, 0.1)):
                decision = self.decide(active_evidence=evidence)
                self.assertEqual(decision.action, "observe_only")
                self.assertTrue(decision.retryable)
        strict = self.decide(
            active_evidence=replace(self.active, remaining_ratio=None),
            policy=replace(self.policy, require_known_preflight=True),
        )
        self.assertEqual(strict.action, "clean_halt")

    def test_rule_seven_subscription_cli_needs_direct_safe_refusal(self):
        active_pin = replace(self.active_pin, mode="subscription_cli")
        target_pin = replace(self.target_pin, mode="subscription_cli")
        policy = replace(self.policy, fallbacks=(target_pin,))
        active = replace(self.active, mode="subscription_cli")
        target = replace(self.target, mode="subscription_cli")
        blocked = self.decide(
            active_pin=active_pin,
            active_evidence=active,
            target_evidence={"model-b": target},
            policy=policy,
        )
        self.assertEqual(blocked.reason_code,
                         "subscription_cli_requires_direct_refusal")
        routed = self.decide(
            active_pin=active_pin,
            active_evidence=replace(active, signal="rejection"),
            target_evidence={"model-b": target},
            policy=policy,
            boundary=InvocationBoundary(refusal=True),
        )
        self.assertEqual(routed.action, "route_next_invocation")

    def test_rule_eight_cap_and_all_rejected_have_stable_causes(self):
        capped = self.decide(switches_completed=1)
        self.assertEqual(capped.reason_code, "switch_limit_reached")
        self.assertFalse(capped.retryable)
        rejected = self.decide(target_evidence={
            "model-b": replace(self.target, remaining_ratio=0.0)
        })
        self.assertEqual(rejected.reason_code, "all_candidates_rejected")
        self.assertFalse(rejected.retryable)

    def test_default_policy_is_observe_only_and_auto_needs_fallbacks(self):
        default = OperatorPolicy("default")
        decision = self.decide(
            active_evidence=replace(self.active, remaining_ratio=0.05),
            policy=default,
            target_evidence={},
        )
        self.assertEqual(decision.action, "observe_only")
        self.assertEqual(decision.reason_code, "automatic_routing_disabled")
        with self.assertRaisesRegex(ValueError, "ordered fallback"):
            OperatorPolicy("invalid", auto_at_safe_boundary=True).validate()

    def test_account_headroom_never_collapses_three_line_fixture(self):
        decision = self.decide(target_evidence={
            "account-aggregate": self.account,
            "model-b": self.target,
        })
        self.assertEqual(decision.selected_pin.model, "model-b")
        self.assertEqual(decision.active_state, "exhausted")

    def test_cross_scope_pin_and_adapter_absence_cannot_invent_target(self):
        cross_scope = replace(self.target_pin, auth_scope="scope-2")
        decision = self.decide(policy=replace(self.policy, fallbacks=(cross_scope,)))
        self.assertEqual(decision.reason_code, "all_candidates_rejected")
        self.assertEqual(decision.candidate_states, (("model-b", "scope_mismatch"),))
        absent = self.decide(target_evidence={})
        self.assertEqual(absent.reason_code, "target_evidence_unusable")

    def test_target_evidence_must_bind_exact_operator_pin(self):
        with self.assertRaisesRegex(ValueError, "target evidence"):
            self.decide(target_evidence={
                "model-b": replace(self.target, requested_model="model-c")
            })


class TestRFC077DryRunAudit(unittest.TestCase):
    def setUp(self):
        fixture = load_json(FIXTURES / "three-way-split.json")
        self.active_evidence = ModelLineEvidence.from_payload(fixture["model_a"])
        unknown = ModelLineEvidence.from_payload(fixture["model_b"])
        self.target_evidence = replace(
            unknown,
            remaining_ratio=0.8,
            used_ratio=0.2,
            provenance="documented",
            signal="response_header",
        )
        self.active_pin = ModelPin("example-provider", "api", "auth-1", "model-a")
        self.target_pin = ModelPin("example-provider", "api", "auth-1", "model-b")
        self.policy = OperatorPolicy(
            "policy-1", (self.target_pin,), auto_at_safe_boundary=True
        )
        self.decision = decide_route(
            active_pin=self.active_pin,
            active_evidence=self.active_evidence,
            target_evidence={"model-b": self.target_evidence},
            policy=self.policy,
            now=NOW,
        )
        self.attempt = b'{"model":"model-a","provider":"example-provider"}\n'
        self.turn = b"<!-- M8SHIFT:TURN 41 agent-a BEGIN -->\nclosed\n"
        self.checkpoint = DurableCheckpoint(
            ".m8shift/runtime/fleet/attempts/attempt-1.json",
            digest(self.attempt),
            "session-1",
            41,
            digest(self.turn),
            "AWAITING_AGENT-A",
            3,
            4,
        )
        self.ref = EvidenceRef(
            ".m8shift/runtime/model-line-routing/session-1/evidence/evidence-b.json",
            "a" * 64,
            self.target_evidence.captured_at,
            "fresh",
        )

    def plan(self):
        return compile_dry_run_plan(
            decision=self.decision,
            active_pin=self.active_pin,
            policy=self.policy,
            decision_id="decision-1",
            recorded_at="2026-07-18T17:01:01Z",
            session="session-1",
            run_id="run-1",
            agent="agent-a",
            evidence_refs=(self.ref,),
            adapter_name="fixture-split",
            adapter_version="1.0.0",
            checkpoint=self.checkpoint,
        )

    def test_dry_run_compiles_rfc070_pins_without_launch_or_replay(self):
        plan = self.plan()
        self.assertEqual(plan.action, "route_next_invocation")
        self.assertEqual(plan.requested_pin["model"], "model-a")
        self.assertEqual(plan.selected_pin["model"], "model-b")
        self.assertEqual(plan.applies_to_invocation, 4)
        self.assertFalse(plan.replay)
        self.assertEqual(plan.record["schema"], DECISION_SCHEMA)
        self.assertEqual(plan.record["switch_ordinal"], 1)
        self.assertNotIn("credential", json.dumps(plan.record).lower())
        self.assertNotIn("raw_body", json.dumps(plan.record))

    def test_record_matches_checked_in_schema_shape(self):
        schema = load_json(
            ROOT / "examples" / "model_line_budget_adapter" / "schema"
            / "m8shift.route-decision.v1.schema.json"
        )
        record = self.plan().record
        self.assertEqual(set(record), set(schema["required"]))
        self.assertEqual(record["selected_model"], "model-b")
        self.assertEqual(record["checkpoint"]["next_invocation"], 4)

    def test_usage_hold_has_no_model_line_record(self):
        held = decide_route(
            active_pin=self.active_pin,
            active_evidence=None,
            target_evidence={},
            policy=self.policy,
            now=NOW,
            usage_hold="active",
        )
        with self.assertRaisesRegex(ValueError, "usage-hold"):
            compile_dry_run_plan(
                decision=held,
                active_pin=self.active_pin,
                policy=self.policy,
                decision_id="decision-held",
                recorded_at="2026-07-18T17:01:01Z",
                session="session-1",
                run_id="run-1",
                agent="agent-a",
                evidence_refs=(self.ref,),
                adapter_name="fixture-split",
                adapter_version="1.0.0",
                checkpoint=self.checkpoint,
            )

    def test_immutable_writer_is_create_exclusive_and_canonical(self):
        with tempfile.TemporaryDirectory() as root:
            path = immutable_decision_path(root, "session-1", "decision-1")
            record = self.plan().record
            expected = (json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ) + "\n").encode("utf-8")
            written_hash = write_immutable_decision(path, record)
            self.assertEqual(Path(path).read_bytes(), expected)
            self.assertEqual(written_hash, digest(expected))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o400)
            with self.assertRaises(FileExistsError):
                write_immutable_decision(path, dict(record, reason_code="changed"))
            self.assertEqual(Path(path).read_bytes(), expected)

    def test_blank_agent_reconstructs_boundary_from_durable_bytes(self):
        reconstructed = reconstruct_boundary(
            self.plan().record, self.attempt, self.turn
        )
        self.assertEqual(reconstructed, {
            "provider": "example-provider",
            "requested_model": "model-a",
            "selected_model": "model-b",
            "policy_id": "policy-1",
            "reason_code": "active_exhausted_target_available",
            "switch_ordinal": 1,
            "completed_invocation": 3,
            "next_invocation": 4,
            "relay_session": "session-1",
            "relay_turn": 41,
        })
        with self.assertRaisesRegex(ValueError, "attempt plan hash mismatch"):
            reconstruct_boundary(self.plan().record, self.attempt + b"x", self.turn)
        with self.assertRaisesRegex(ValueError, "relay turn hash mismatch"):
            reconstruct_boundary(self.plan().record, self.attempt, self.turn + b"x")

    def test_writer_rejects_fields_outside_redacted_schema(self):
        record = dict(self.plan().record)
        record["raw_body"] = "forbidden"
        with tempfile.TemporaryDirectory() as root:
            path = immutable_decision_path(root, "session-1", "decision-1")
            with self.assertRaisesRegex(ValueError, "exact v1 field set"):
                write_immutable_decision(path, record)
            self.assertFalse(os.path.exists(path))

    def test_opaque_paths_reject_traversal(self):
        with self.assertRaisesRegex(ValueError, "bounded opaque"):
            immutable_decision_path("/tmp/root", "../session", "decision-1")


if __name__ == "__main__":
    unittest.main()
