"""Pure RFC 077 Slice C routing policy and immutable dry-run audit records.

This module consumes already-normalized evidence.  It does not invoke an
adapter, launch a provider command, read credentials, or mutate relay state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .base import MODES, ModelLineEvidence, _required_text, _timestamp


DECISION_SCHEMA = "m8shift.route-decision.v1"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+~-]{0,127}$")
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
AUTOMATABLE_APPLICABILITY = frozenset(("exact_model", "documented_group"))
NON_AUTOMATABLE_PROVENANCE = frozenset(("console_only", "unknown"))
ACTIONS = frozenset(
    ("continue", "observe_only", "route_next_invocation", "clean_halt")
)
HOLD_STATES = frozenset(("clear", "active", "corrupt"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class ModelPin:
    """An operator-declared RFC 070 pin; no target can be synthesized."""

    provider: str
    mode: str
    auth_scope: str
    model: str
    profile: Optional[str] = None
    effort: Optional[str] = None

    def validate(self) -> None:
        for field_name in ("provider", "auth_scope"):
            _required_text(getattr(self, field_name), field_name)
        if self.mode not in MODES:
            raise ValueError("mode must be api, subscription_cli, or cloud")
        if not isinstance(self.model, str) or not MODEL_ID_RE.fullmatch(self.model):
            raise ValueError("model must be a valid RFC 070 model pin")
        for field_name in ("profile", "effort"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str) or not MODEL_ID_RE.fullmatch(value)
            ):
                raise ValueError("%s must be a valid RFC 070 safe token" % field_name)

    def compiled(self) -> Dict[str, Any]:
        self.validate()
        return {
            "provider": self.provider,
            "mode": self.mode,
            "auth_scope": self.auth_scope,
            "model": self.model,
            "profile": self.profile,
            "effort": self.effort,
        }


@dataclass(frozen=True)
class OperatorPolicy:
    policy_id: str
    fallbacks: Tuple[ModelPin, ...] = ()
    auto_at_safe_boundary: bool = False
    max_switches: int = 1
    drain_threshold: float = 0.1
    require_known_preflight: bool = False

    def validate(self) -> None:
        _required_text(self.policy_id, "policy_id")
        for field_name in ("auto_at_safe_boundary", "require_known_preflight"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError("%s must be boolean" % field_name)
        if isinstance(self.max_switches, bool) or not isinstance(self.max_switches, int):
            raise ValueError("max_switches must be an integer")
        if self.max_switches < 0:
            raise ValueError("max_switches must be non-negative")
        if (
            isinstance(self.drain_threshold, bool)
            or not isinstance(self.drain_threshold, (int, float))
            or self.drain_threshold < 0
            or self.drain_threshold > 1
        ):
            raise ValueError("drain_threshold must be between zero and one")
        if not isinstance(self.fallbacks, tuple):
            raise ValueError("fallbacks must be an explicit ordered tuple")
        if self.auto_at_safe_boundary and not self.fallbacks:
            raise ValueError("automatic routing requires an ordered fallback list")
        seen = set()
        for pin in self.fallbacks:
            if not isinstance(pin, ModelPin):
                raise ValueError("fallbacks must contain ModelPin values")
            pin.validate()
            identity = (pin.provider, pin.mode, pin.auth_scope, pin.model)
            if identity in seen:
                raise ValueError("fallback pins must be unique and ordered")
            seen.add(identity)


@dataclass(frozen=True)
class InvocationBoundary:
    refusal: bool = False
    output_started: bool = False
    tool_effect: bool = False
    ambiguous_completion: bool = False
    retry_safe: bool = True

    def validate(self) -> None:
        for field_name in (
            "refusal",
            "output_started",
            "tool_effect",
            "ambiguous_completion",
            "retry_safe",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError("%s must be boolean" % field_name)

    def unsafe_reason(self) -> Optional[str]:
        if self.tool_effect:
            return "tool_effect_present"
        if self.output_started:
            return "partial_stream_present"
        if self.ambiguous_completion:
            return "ambiguous_completion"
        if self.refusal and not self.retry_safe:
            return "refusal_not_retry_safe"
        return None


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    sha256: str
    captured_at: str
    freshness: str

    def payload(self) -> Dict[str, str]:
        _required_text(self.path, "evidence path")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("evidence sha256 must be lowercase hexadecimal")
        _timestamp(self.captured_at, "captured_at")
        if self.freshness not in ("fresh", "stale", "unknown"):
            raise ValueError("invalid evidence freshness")
        return {
            "path": self.path,
            "sha256": self.sha256,
            "captured_at": self.captured_at,
            "freshness": self.freshness,
        }


@dataclass(frozen=True)
class DurableCheckpoint:
    attempt_plan_ref: str
    attempt_plan_sha256: str
    relay_session: str
    relay_turn: int
    relay_turn_sha256: str
    relay_state: str
    completed_invocation: int
    next_invocation: int

    def payload(self) -> Dict[str, Any]:
        for field_name in ("attempt_plan_ref", "relay_session"):
            _required_text(getattr(self, field_name), field_name)
        for field_name in ("attempt_plan_sha256", "relay_turn_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, field_name)):
                raise ValueError("%s must be lowercase SHA-256" % field_name)
        if not re.fullmatch(r"(?:IDLE|AWAITING_[A-Z0-9_-]+|PAUSED|DONE)", self.relay_state):
            raise ValueError("checkpoint relay state must be non-working")
        for field_name in ("relay_turn", "completed_invocation", "next_invocation"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("%s must be a non-negative integer" % field_name)
        if self.next_invocation != self.completed_invocation + 1:
            raise ValueError("checkpoint invocation ordinals must name one boundary")
        return {
            "attempt_plan_ref": self.attempt_plan_ref,
            "attempt_plan_sha256": self.attempt_plan_sha256,
            "relay_session": self.relay_session,
            "relay_turn": self.relay_turn,
            "relay_turn_sha256": self.relay_turn_sha256,
            "relay_state": self.relay_state,
            "completed_invocation": self.completed_invocation,
            "next_invocation": self.next_invocation,
        }


@dataclass(frozen=True)
class RouteDecision:
    action: str
    reason_code: str
    active_state: str
    selected_pin: Optional[ModelPin] = None
    switch_ordinal: int = 0
    retryable: bool = False
    warnings: Tuple[str, ...] = ()
    candidate_states: Tuple[Tuple[str, str], ...] = ()
    record_allowed: bool = True

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError("invalid route action")
        _required_text(self.reason_code, "reason_code")


@dataclass(frozen=True)
class DryRunPlan:
    action: str
    reason_code: str
    requested_pin: Mapping[str, Any]
    selected_pin: Optional[Mapping[str, Any]]
    applies_to_invocation: Optional[int]
    replay: bool
    record: Mapping[str, Any]


def evidence_state(
    evidence: ModelLineEvidence, now: str, drain_threshold: float
) -> str:
    """Classify only provider-reported, applicable, fresh line evidence."""

    evidence.validate()
    _timestamp(now, "now")
    if evidence.freshness(now) == "stale":
        return "stale"
    if (
        evidence.applicability not in AUTOMATABLE_APPLICABILITY
        or evidence.provenance in NON_AUTOMATABLE_PROVENANCE
        or evidence.remaining_ratio is None
    ):
        return "unknown"
    if evidence.remaining_ratio <= 0:
        return "exhausted"
    if evidence.remaining_ratio <= drain_threshold:
        return "drain"
    return "available"


def _halt(reason: str, active_state: str, retryable: bool = False,
          candidates: Sequence[Tuple[str, str]] = ()) -> RouteDecision:
    return RouteDecision(
        action="clean_halt",
        reason_code=reason,
        active_state=active_state,
        retryable=retryable,
        candidate_states=tuple(candidates),
    )


def decide_route(
    *,
    active_pin: ModelPin,
    active_evidence: Optional[ModelLineEvidence],
    target_evidence: Mapping[str, ModelLineEvidence],
    policy: OperatorPolicy,
    now: str,
    boundary: InvocationBoundary = InvocationBoundary(),
    usage_hold: str = "clear",
    switches_completed: int = 0,
    checkpoint_present: bool = True,
) -> RouteDecision:
    """Evaluate the eight RFC 077 rules without I/O or adapter invocation.

    Hold admission is deliberately checked before validating any evidence.  A
    caller can therefore prove that an active/corrupt hold prevents probing by
    supplying no evidence at all.
    """

    active_pin.validate()
    policy.validate()
    boundary.validate()
    _timestamp(now, "now")
    if usage_hold not in HOLD_STATES:
        raise ValueError("usage_hold must be clear, active, or corrupt")
    if usage_hold == "active":
        return RouteDecision(
            "clean_halt", "agent_usage_hold_active", "not_observed",
            record_allowed=False,
        )
    if usage_hold == "corrupt":
        return RouteDecision(
            "clean_halt", "agent_usage_hold_corrupt", "not_observed",
            record_allowed=False,
        )
    if isinstance(switches_completed, bool) or not isinstance(switches_completed, int) \
            or switches_completed < 0:
        raise ValueError("switches_completed must be a non-negative integer")
    if not isinstance(checkpoint_present, bool):
        raise ValueError("checkpoint_present must be boolean")

    if active_evidence is None:
        active_state = "unknown"
    else:
        if (
            active_evidence.provider != active_pin.provider
            or active_evidence.mode != active_pin.mode
            or active_evidence.requested_model != active_pin.model
        ):
            raise ValueError("active evidence does not match the active pin")
        active_state = evidence_state(active_evidence, now, policy.drain_threshold)

    unsafe = boundary.unsafe_reason()
    if unsafe:
        return _halt(unsafe, active_state, retryable=False)

    if active_state == "available" and not boundary.refusal:
        return RouteDecision("continue", "active_available", active_state)

    if active_state in ("unknown", "stale") and not boundary.refusal:
        if policy.require_known_preflight:
            return _halt("active_evidence_%s" % active_state, active_state, True)
        return RouteDecision(
            "observe_only",
            "active_evidence_%s" % active_state,
            active_state,
            retryable=True,
            warnings=("active line evidence is %s" % active_state,),
        )

    if not policy.auto_at_safe_boundary:
        if active_state == "drain" and not boundary.refusal:
            return RouteDecision(
                "observe_only", "automatic_routing_disabled", active_state,
                warnings=("active line is draining",),
            )
        return _halt("automatic_routing_disabled", active_state, True)

    if switches_completed >= policy.max_switches:
        return _halt("switch_limit_reached", active_state, False)
    if not checkpoint_present:
        return _halt("checkpoint_missing", active_state, True)

    if active_pin.mode == "subscription_cli" and not (
        boundary.refusal
        and active_evidence is not None
        and active_evidence.signal == "rejection"
    ):
        return _halt("subscription_cli_requires_direct_refusal", active_state, True)

    candidates = []
    selected = None
    for pin in policy.fallbacks:
        if (
            pin.provider != active_pin.provider
            or pin.mode != active_pin.mode
            or pin.auth_scope != active_pin.auth_scope
        ):
            candidates.append((pin.model, "scope_mismatch"))
            continue
        evidence = target_evidence.get(pin.model)
        if evidence is None:
            candidates.append((pin.model, "unknown"))
            continue
        if (
            evidence.provider != pin.provider
            or evidence.mode != pin.mode
            or evidence.requested_model != pin.model
        ):
            raise ValueError("target evidence does not match its operator pin")
        state = evidence_state(evidence, now, policy.drain_threshold)
        candidates.append((pin.model, state))
        if state == "available":
            selected = pin
            break

    if selected is None:
        retryable = any(state in ("unknown", "stale") for _model, state in candidates)
        reason = "target_evidence_unusable" if retryable else "all_candidates_rejected"
        return _halt(reason, active_state, retryable, candidates)

    if boundary.refusal:
        reason = "refusal_before_output_target_available"
    elif active_state == "drain":
        reason = "active_drain_target_available"
    else:
        reason = "active_exhausted_target_available"
    return RouteDecision(
        action="route_next_invocation",
        reason_code=reason,
        active_state=active_state,
        selected_pin=selected,
        switch_ordinal=switches_completed + 1,
        candidate_states=tuple(candidates),
    )


def compile_dry_run_plan(
    *,
    decision: RouteDecision,
    active_pin: ModelPin,
    policy: OperatorPolicy,
    decision_id: str,
    recorded_at: str,
    session: str,
    run_id: str,
    agent: str,
    evidence_refs: Sequence[EvidenceRef],
    adapter_name: str,
    adapter_version: str,
    checkpoint: DurableCheckpoint,
) -> DryRunPlan:
    """Compile a route plan and schema-shaped record without launching it."""

    if not decision.record_allowed:
        raise ValueError("usage-hold admission stops before a route record")
    active_pin.validate()
    policy.validate()
    if not OPAQUE_ID_RE.fullmatch(decision_id):
        raise ValueError("decision_id must be a bounded opaque id")
    for field_name, value in (
        ("session", session), ("run_id", run_id), ("agent", agent),
        ("adapter_name", adapter_name), ("adapter_version", adapter_version),
    ):
        _required_text(value, field_name)
    _timestamp(recorded_at, "recorded_at")
    refs = [ref.payload() for ref in evidence_refs]
    if not refs:
        raise ValueError("a route record requires hashed evidence references")
    checkpoint_payload = checkpoint.payload()
    if session != checkpoint.relay_session:
        raise ValueError("record session disagrees with durable checkpoint")
    selected_pin = decision.selected_pin
    if decision.action == "route_next_invocation" and selected_pin is None:
        raise ValueError("route action requires an operator-declared selected pin")
    if selected_pin is not None and (
        selected_pin.provider != active_pin.provider
        or selected_pin.mode != active_pin.mode
        or selected_pin.auth_scope != active_pin.auth_scope
    ):
        raise ValueError("selected pin changes provider, mode, or auth scope")
    selected_model = selected_pin.model if selected_pin else (
        active_pin.model if decision.action in ("continue", "observe_only") else None
    )
    record = {
        "schema": DECISION_SCHEMA,
        "decision_id": decision_id,
        "recorded_at": recorded_at,
        "session": session,
        "run_id": run_id,
        "agent": agent,
        "provider": active_pin.provider,
        "requested_model": active_pin.model,
        "selected_model": selected_model,
        "policy_id": policy.policy_id,
        "reason_code": decision.reason_code,
        "switch_ordinal": decision.switch_ordinal,
        "adapter": {"name": adapter_name, "version": adapter_version},
        "evidence_refs": refs,
        "checkpoint": checkpoint_payload,
    }
    applies_to = (
        checkpoint.next_invocation
        if decision.action == "route_next_invocation"
        else None
    )
    return DryRunPlan(
        action=decision.action,
        reason_code=decision.reason_code,
        requested_pin=active_pin.compiled(),
        selected_pin=selected_pin.compiled() if selected_pin else None,
        applies_to_invocation=applies_to,
        replay=False,
        record=record,
    )


def immutable_decision_path(root: str, session: str, decision_id: str) -> str:
    """Return the RFC 077 sidecar path using bounded opaque components."""

    for field_name, value in (("session", session), ("decision_id", decision_id)):
        if not isinstance(value, str) or not OPAQUE_ID_RE.fullmatch(value):
            raise ValueError("%s must be a bounded opaque id" % field_name)
    physical_root = os.path.realpath(root)
    return os.path.join(
        physical_root, ".m8shift", "runtime", "model-line-routing", session,
        "decisions", decision_id + ".json",
    )


def write_immutable_decision(path: str, record: Mapping[str, Any]) -> str:
    """Persist canonical JSON once, atomically; an existing id is immutable."""

    _validate_decision_record(record)
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    payload = _canonical_bytes(record)
    descriptor, temporary = tempfile.mkstemp(prefix=".route-decision-", dir=parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o400)
        os.link(temporary, path)
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return _sha256(payload)


def _validate_decision_record(record: Mapping[str, Any]) -> None:
    """Enforce the checked-in v1 shape before any durable write."""

    required = {
        "schema", "decision_id", "recorded_at", "session", "run_id", "agent",
        "provider", "requested_model", "selected_model", "policy_id",
        "reason_code", "switch_ordinal", "adapter", "evidence_refs", "checkpoint",
    }
    if not isinstance(record, Mapping) or set(record) != required:
        raise ValueError("route decision must match the exact v1 field set")
    if record["schema"] != DECISION_SCHEMA:
        raise ValueError("unsupported route decision schema")
    if not isinstance(record["decision_id"], str) or not OPAQUE_ID_RE.fullmatch(
        record["decision_id"]
    ):
        raise ValueError("invalid route decision id")
    _timestamp(record["recorded_at"], "recorded_at")
    for field_name in (
        "session", "run_id", "agent", "provider", "requested_model",
        "policy_id", "reason_code",
    ):
        _required_text(record[field_name], field_name)
    if record["selected_model"] is not None:
        _required_text(record["selected_model"], "selected_model")
    ordinal = record["switch_ordinal"]
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("switch_ordinal must be a non-negative integer")
    adapter = record["adapter"]
    if not isinstance(adapter, Mapping) or set(adapter) != {"name", "version"}:
        raise ValueError("adapter must contain only name and version")
    _required_text(adapter["name"], "adapter.name")
    _required_text(adapter["version"], "adapter.version")
    refs = record["evidence_refs"]
    if not isinstance(refs, list) or not refs:
        raise ValueError("evidence_refs must be a non-empty array")
    for ref in refs:
        if not isinstance(ref, Mapping) or set(ref) != {
            "path", "sha256", "captured_at", "freshness"
        }:
            raise ValueError("invalid evidence reference shape")
        EvidenceRef(**dict(ref)).payload()
    checkpoint = record["checkpoint"]
    if not isinstance(checkpoint, Mapping):
        raise ValueError("checkpoint must be an object")
    expected_checkpoint = {
        "attempt_plan_ref", "attempt_plan_sha256", "relay_session", "relay_turn",
        "relay_turn_sha256", "relay_state", "completed_invocation", "next_invocation",
    }
    if set(checkpoint) != expected_checkpoint:
        raise ValueError("invalid checkpoint shape")
    DurableCheckpoint(**dict(checkpoint)).payload()
    if checkpoint["relay_session"] != record["session"]:
        raise ValueError("record session disagrees with checkpoint")


def reconstruct_boundary(
    record: Mapping[str, Any], attempt_plan_bytes: bytes, relay_turn_bytes: bytes
) -> Dict[str, Any]:
    """Reconstruct and verify the switch point from durable artifacts alone."""

    _validate_decision_record(record)
    checkpoint = record.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise ValueError("route decision checkpoint is missing")
    if _sha256(attempt_plan_bytes) != checkpoint.get("attempt_plan_sha256"):
        raise ValueError("attempt plan hash mismatch")
    if _sha256(relay_turn_bytes) != checkpoint.get("relay_turn_sha256"):
        raise ValueError("relay turn hash mismatch")
    try:
        attempt = json.loads(attempt_plan_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("attempt plan is not valid UTF-8 JSON") from exc
    old_model = attempt.get("model")
    if not isinstance(old_model, str) or old_model != record.get("requested_model"):
        raise ValueError("attempt plan model disagrees with route decision")
    provider = attempt.get("provider")
    if not isinstance(provider, str) or provider != record.get("provider"):
        raise ValueError("attempt plan provider disagrees with route decision")
    return {
        "provider": provider,
        "requested_model": old_model,
        "selected_model": record.get("selected_model"),
        "policy_id": record.get("policy_id"),
        "reason_code": record.get("reason_code"),
        "switch_ordinal": record.get("switch_ordinal"),
        "completed_invocation": checkpoint.get("completed_invocation"),
        "next_invocation": checkpoint.get("next_invocation"),
        "relay_session": checkpoint.get("relay_session"),
        "relay_turn": checkpoint.get("relay_turn"),
    }
