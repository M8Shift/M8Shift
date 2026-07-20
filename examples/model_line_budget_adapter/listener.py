"""RFC 077 Slice D listener integration at a durable safe boundary.

This module is deliberately fixture-only.  It reads no credentials, imports no
vendor SDK, opens no socket, and never writes the relay.  The listener calls it
after its usage-hold gate and immediately before compiling the next provider
argv.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .base import ModelLineEvidence
from .policy import (
    DryRunPlan,
    DurableCheckpoint,
    EvidenceRef,
    InvocationBoundary,
    ModelPin,
    OperatorPolicy,
    compile_dry_run_plan,
    decide_route,
    immutable_decision_path,
    write_immutable_decision,
)


LISTENER_POLICY_SCHEMA = "m8shift.listener.model-line-policy.v1"
ATTEMPT_SCHEMA = "m8shift.listener.route-attempt.v1"
POLICY_RELATIVE_DIR = os.path.join(".m8shift", "model-line-routing")
TURN_RE = re.compile(
    rb"<!-- M8SHIFT:TURN ([0-9]+) [a-z][a-z0-9_-]* BEGIN -->.*?"
    rb"<!-- M8SHIFT:TURN \1 [a-z][a-z0-9_-]* END -->\n?",
    re.DOTALL,
)


class BoundaryIntegrationError(ValueError):
    """Fail-closed listener-boundary validation error."""


@dataclass(frozen=True)
class ListenerBoundaryResult:
    plan: DryRunPlan
    attempt_path: str
    attempt_bytes: bytes
    relay_turn_bytes: bytes
    selected_pin: Optional[ModelPin]


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _exclusive_write(path: str, payload: bytes) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".route-boundary-", dir=parent)
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


def _safe_component(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value
    ):
        raise BoundaryIntegrationError("%s must be a bounded opaque id" % field)
    return value


def _read_json(path: str) -> Mapping[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BoundaryIntegrationError("invalid fixture boundary input") from exc
    if not isinstance(value, Mapping):
        raise BoundaryIntegrationError("fixture boundary input must be an object")
    return value


def _confined_fixture(root: str, relative: str) -> str:
    if not isinstance(relative, str) or not relative:
        raise BoundaryIntegrationError("evidence fixture path must be non-empty")
    if os.path.isabs(relative):
        raise BoundaryIntegrationError("evidence fixture path must be relative")
    root_real = os.path.realpath(root)
    path = os.path.realpath(os.path.join(root_real, relative))
    try:
        common = os.path.commonpath((root_real, path))
    except ValueError as exc:
        raise BoundaryIntegrationError("evidence fixture escapes project root") from exc
    if common != root_real or "fixtures" not in relative.replace("\\", "/").split("/"):
        raise BoundaryIntegrationError("Slice D accepts fixture evidence only")
    return path


def _pin(value: Mapping[str, Any], *, model: Optional[str] = None) -> ModelPin:
    if not isinstance(value, Mapping):
        raise BoundaryIntegrationError("model pin must be an object")
    allowed = {"provider", "mode", "auth_scope", "model", "profile", "effort"}
    if set(value) - allowed:
        raise BoundaryIntegrationError("model pin has unknown fields")
    try:
        pin = ModelPin(
            provider=value.get("provider"),
            mode=value.get("mode"),
            auth_scope=value.get("auth_scope"),
            model=model if model is not None else value.get("model"),
            profile=value.get("profile"),
            effort=value.get("effort"),
        )
        pin.validate()
    except (TypeError, ValueError) as exc:
        raise BoundaryIntegrationError("invalid RFC 070 model pin") from exc
    return pin


def load_fixture_policy(root: str, agent: str, active_model: str) -> Tuple[
    ModelPin, OperatorPolicy, Mapping[str, str], str, str
]:
    """Load explicit fixture-only policy, or the safe observe-only default."""

    path = os.path.join(root, POLICY_RELATIVE_DIR, "%s.json" % agent)
    if not os.path.exists(path):
        active = ModelPin("unconfigured", "subscription_cli", agent, active_model)
        active.validate()
        return active, OperatorPolicy("observe-only-default"), {}, "listener-none", "1"
    doc = _read_json(path)
    required = {
        "schema", "policy_id", "active", "fallbacks", "auto_at_safe_boundary",
        "adapter", "evidence_fixtures",
    }
    optional = {"max_switches", "drain_threshold", "require_known_preflight"}
    if set(doc) - required - optional or required - set(doc):
        raise BoundaryIntegrationError("listener policy has an invalid field set")
    if doc.get("schema") != LISTENER_POLICY_SCHEMA:
        raise BoundaryIntegrationError("unsupported listener policy schema")
    adapter = doc.get("adapter")
    if not isinstance(adapter, Mapping) or set(adapter) != {
        "name", "version", "enabled", "retrieval"
    }:
        raise BoundaryIntegrationError("listener policy adapter shape is invalid")
    if adapter.get("enabled") is not False or adapter.get("retrieval") != "fixture_only":
        raise BoundaryIntegrationError("Slice D vendor adapters must remain disabled and fixture-only")
    active = _pin(doc.get("active"), model=active_model)
    fallbacks_raw = doc.get("fallbacks")
    if not isinstance(fallbacks_raw, list):
        raise BoundaryIntegrationError("fallbacks must be an ordered list")
    fallbacks = tuple(_pin(value) for value in fallbacks_raw)
    try:
        policy = OperatorPolicy(
            policy_id=doc.get("policy_id"),
            fallbacks=fallbacks,
            auto_at_safe_boundary=doc.get("auto_at_safe_boundary"),
            max_switches=doc.get("max_switches", 1),
            drain_threshold=doc.get("drain_threshold", 0.1),
            require_known_preflight=doc.get("require_known_preflight", False),
        )
        policy.validate()
    except (TypeError, ValueError) as exc:
        raise BoundaryIntegrationError("invalid listener routing policy") from exc
    fixtures = doc.get("evidence_fixtures")
    if not isinstance(fixtures, Mapping) or not all(
        isinstance(model, str) and isinstance(value, str)
        for model, value in fixtures.items()
    ):
        raise BoundaryIntegrationError("evidence_fixtures must map models to paths")
    return active, policy, fixtures, str(adapter.get("name")), str(adapter.get("version"))


def _relay_checkpoint(relay_path: str) -> Tuple[Mapping[str, str], bytes, bytes]:
    try:
        with open(relay_path, "rb") as handle:
            relay = handle.read()
    except OSError as exc:
        raise BoundaryIntegrationError("relay checkpoint is unreadable") from exc
    try:
        text = relay.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BoundaryIntegrationError("relay checkpoint is not UTF-8") from exc
    begin = "<!-- M8SHIFT:LOCK:BEGIN -->"
    end = "<!-- M8SHIFT:LOCK:END -->"
    if begin not in text or end not in text:
        raise BoundaryIntegrationError("relay checkpoint has no valid lock")
    fields: Dict[str, str] = {}
    for line in text.split(begin, 1)[1].split(end, 1)[0].splitlines():
        match = re.match(r"\s*([a-z_]+):\s*(.*?)\s*$", line)
        if match:
            fields[match.group(1)] = match.group(2)
    state = fields.get("state", "")
    if state.startswith("WORKING_") or not re.fullmatch(
        r"(?:IDLE|AWAITING_[A-Z0-9_-]+|PAUSED|DONE)", state
    ):
        raise BoundaryIntegrationError("safe boundary requires a non-working relay state")
    try:
        turn = int(fields.get("turn", ""))
    except ValueError as exc:
        raise BoundaryIntegrationError("relay turn is invalid") from exc
    turn_bytes = b""
    if turn:
        for match in TURN_RE.finditer(relay):
            if int(match.group(1)) == turn:
                turn_bytes = match.group(0)
        if not turn_bytes:
            raise BoundaryIntegrationError("last closed relay turn is unavailable")
    return fields, relay, turn_bytes


def _unknown_evidence(active: ModelPin, timestamp: str) -> ModelLineEvidence:
    return ModelLineEvidence(
        provider=active.provider,
        mode=active.mode,
        requested_model=active.model,
        scope="account",
        applicability="unknown",
        provider_bucket_id=None,
        used_ratio=None,
        remaining_ratio=None,
        reset_at=None,
        signal="runtime_observation",
        provenance="unknown",
        captured_at=timestamp,
        fresh_until=timestamp,
        adapter_name="listener-none",
        adapter_version="1",
    )


def _generation_is_current(runtime_dir: str, agent: str, generation: str, pid: int) -> bool:
    if not generation:
        return True
    try:
        identity = _read_json(os.path.join(runtime_dir, "listeners", "%s.pid" % agent))
        state = _read_json(os.path.join(runtime_dir, "listeners", "%s.json" % agent))
    except BoundaryIntegrationError:
        return False
    return (
        identity.get("pid") == pid
        and identity.get("generation") == generation
        and state.get("process_pid") == pid
        and state.get("generation") == generation
    )


def perform_listener_boundary(
    *,
    root: str,
    relay_path: str,
    runtime_dir: str,
    agent: str,
    active_model: str,
    run_id: str,
    completed_invocations: int,
    switches_completed: int = 0,
    boundary: InvocationBoundary = InvocationBoundary(),
    generation: str = "",
    process_pid: Optional[int] = None,
) -> ListenerBoundaryResult:
    """Persist checkpoint + decision and return the next-invocation route plan."""

    _safe_component(agent, "agent")
    _safe_component(run_id, "run_id")
    if not isinstance(completed_invocations, int) or completed_invocations < 0:
        raise BoundaryIntegrationError("completed_invocations must be non-negative")
    pid = process_pid if process_pid is not None else os.getpid()
    if not _generation_is_current(runtime_dir, agent, generation, pid):
        raise BoundaryIntegrationError("listener generation is stale")
    fields, relay_before, relay_turn = _relay_checkpoint(relay_path)
    active, policy, fixture_paths, adapter_name, adapter_version = load_fixture_policy(
        root, agent, active_model
    )
    recorded_at = _iso_now()
    attempt = {
        "schema": ATTEMPT_SCHEMA,
        "run_id": run_id,
        "agent": agent,
        "provider": active.provider,
        "mode": active.mode,
        "auth_scope": active.auth_scope,
        "model": active.model,
        "profile": active.profile,
        "effort": active.effort,
        "completed_invocation": completed_invocations,
        "next_invocation": completed_invocations + 1,
    }
    attempt_bytes = _canonical_bytes(attempt)
    attempt_path = os.path.join(runtime_dir, "fleet", "attempts", "%s.json" % run_id)
    _exclusive_write(attempt_path, attempt_bytes)

    evidence_by_model: Dict[str, ModelLineEvidence] = {}
    if fixture_paths:
        for model, relative in fixture_paths.items():
            evidence_by_model[model] = ModelLineEvidence.from_payload(
                _read_json(_confined_fixture(root, relative))
            )
    if active.model not in evidence_by_model:
        evidence_by_model[active.model] = _unknown_evidence(active, recorded_at)
    active_evidence = evidence_by_model.get(active.model)
    target_evidence = {
        model: evidence for model, evidence in evidence_by_model.items()
        if model != active.model
    }
    decision = decide_route(
        active_pin=active,
        active_evidence=active_evidence,
        target_evidence=target_evidence,
        policy=policy,
        now=recorded_at,
        boundary=boundary,
        usage_hold="clear",
        switches_completed=switches_completed,
        checkpoint_present=True,
    )
    session = _safe_component(fields.get("session", ""), "relay session")
    evidence_refs = []
    evidence_dir = os.path.join(
        runtime_dir, "model-line-routing", session, "evidence"
    )
    for index, evidence in enumerate(evidence_by_model.values(), 1):
        payload = _canonical_bytes(evidence.to_payload())
        evidence_id = "evidence-%s-%d" % (run_id, index)
        evidence_path = os.path.join(evidence_dir, evidence_id + ".json")
        _exclusive_write(evidence_path, payload)
        evidence_refs.append(EvidenceRef(
            os.path.relpath(evidence_path, root).replace(os.sep, "/"),
            _sha256(payload),
            evidence.captured_at,
            evidence.freshness(recorded_at),
        ))
    checkpoint = DurableCheckpoint(
        os.path.relpath(attempt_path, root).replace(os.sep, "/"),
        _sha256(attempt_bytes),
        session,
        int(fields.get("turn", "0")),
        _sha256(relay_turn),
        fields.get("state", ""),
        completed_invocations,
        completed_invocations + 1,
    )
    decision_id = "route-%s" % run_id
    plan = compile_dry_run_plan(
        decision=decision,
        active_pin=active,
        policy=policy,
        decision_id=decision_id,
        recorded_at=recorded_at,
        session=session,
        run_id=run_id,
        agent=agent,
        evidence_refs=tuple(evidence_refs),
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        checkpoint=checkpoint,
    )
    decision_path = immutable_decision_path(root, session, decision_id)
    write_immutable_decision(decision_path, plan.record)
    try:
        with open(relay_path, "rb") as handle:
            relay_after = handle.read()
    except OSError as exc:
        raise BoundaryIntegrationError("relay changed during boundary decision") from exc
    if relay_after != relay_before:
        raise BoundaryIntegrationError("relay changed during boundary decision")
    return ListenerBoundaryResult(
        plan=plan,
        attempt_path=attempt_path,
        attempt_bytes=attempt_bytes,
        relay_turn_bytes=relay_turn,
        selected_pin=decision.selected_pin,
    )
