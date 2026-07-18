"""Vendor-neutral, fixture-only model-line evidence primitives.

Slice A deliberately contains no provider client, credential lookup, network
access, routing policy, or relay mutation.  External vendor adapters may
subclass :class:`ModelLineBudgetAdapter` in later gated slices.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional


EVIDENCE_SCHEMA = "m8shift.model-line.evidence.v1"

MODES = frozenset(("api", "subscription_cli", "cloud"))
SCOPES = frozenset(
    ("account", "organization", "project", "workspace", "model_group", "model")
)
APPLICABILITIES = frozenset(("exact_model", "documented_group", "unknown"))
SIGNALS = frozenset(
    (
        "response_header",
        "usage_report",
        "quota_metric",
        "console",
        "runtime_observation",
        "rejection",
    )
)
PROVENANCES = frozenset(
    ("documented", "runtime_observed", "console_only", "unknown")
)


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("%s must be an RFC 3339 UTC timestamp ending in Z" % field)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("%s must be an RFC 3339 UTC timestamp" % field) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("%s must be UTC" % field)
    return parsed


def _ratio(value: Optional[float], field: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be null or a number" % field)
    if value < 0 or value > 1:
        raise ValueError("%s must be between 0 and 1" % field)


def _required_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % field)


def _optional_text(value: Any, field: str) -> None:
    if value is not None:
        _required_text(value, field)


def _exact_keys(value: Mapping[str, Any], required: set, optional: set, field: str) -> None:
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing:
        raise ValueError("%s is missing: %s" % (field, ", ".join(sorted(missing))))
    if extra:
        raise ValueError("%s has unknown keys: %s" % (field, ", ".join(sorted(extra))))


@dataclass(frozen=True)
class ProbeTarget:
    provider: str
    mode: str
    requested_model: str

    def validate(self) -> None:
        _required_text(self.provider, "provider")
        _required_text(self.requested_model, "requested_model")
        if self.mode not in MODES:
            raise ValueError("mode must be one of: %s" % ", ".join(sorted(MODES)))


@dataclass(frozen=True)
class RefusalObservation:
    """Bounded terminal observation; raw provider bodies are intentionally absent."""

    target: ProbeTarget
    captured_at: str
    output_started: bool
    tool_effect: bool
    retry_safe: bool
    status_code: Optional[int] = None
    provider_code: Optional[str] = None

    def validate(self) -> None:
        self.target.validate()
        _timestamp(self.captured_at, "captured_at")
        for field in ("output_started", "tool_effect", "retry_safe"):
            if not isinstance(getattr(self, field), bool):
                raise ValueError("%s must be boolean" % field)
        if self.status_code is not None and (
            isinstance(self.status_code, bool) or not isinstance(self.status_code, int)
        ):
            raise ValueError("status_code must be null or an integer")
        _optional_text(self.provider_code, "provider_code")


@dataclass(frozen=True)
class ModelLineEvidence:
    provider: str
    mode: str
    requested_model: str
    scope: str
    applicability: str
    provider_bucket_id: Optional[str]
    used_ratio: Optional[float]
    remaining_ratio: Optional[float]
    reset_at: Optional[str]
    signal: str
    provenance: str
    captured_at: str
    fresh_until: str
    adapter_name: str
    adapter_version: str
    documented_mapping: Optional[Mapping[str, str]] = None
    estimate: Optional[Mapping[str, Any]] = None

    def validate(self) -> None:
        _required_text(self.provider, "provider")
        _required_text(self.requested_model, "requested_model")
        _required_text(self.adapter_name, "adapter.name")
        _required_text(self.adapter_version, "adapter.version")
        if self.mode not in MODES:
            raise ValueError("unsupported mode")
        if self.scope not in SCOPES:
            raise ValueError("unsupported scope")
        if self.applicability not in APPLICABILITIES:
            raise ValueError("unsupported applicability")
        if self.signal not in SIGNALS:
            raise ValueError("unsupported signal")
        if self.provenance not in PROVENANCES:
            raise ValueError("unsupported provenance")
        _optional_text(self.provider_bucket_id, "provider_bucket_id")
        _ratio(self.used_ratio, "used_ratio")
        _ratio(self.remaining_ratio, "remaining_ratio")
        captured = _timestamp(self.captured_at, "captured_at")
        fresh_until = _timestamp(self.fresh_until, "fresh_until")
        if fresh_until < captured:
            raise ValueError("fresh_until must not precede captured_at")
        if self.reset_at is not None:
            _timestamp(self.reset_at, "reset_at")

        if self.documented_mapping is not None:
            if not isinstance(self.documented_mapping, Mapping):
                raise ValueError("documented_mapping must be null or an object")
            _exact_keys(
                self.documented_mapping,
                {"reference", "version"},
                set(),
                "documented_mapping",
            )
            _required_text(self.documented_mapping["reference"], "documented_mapping.reference")
            _required_text(self.documented_mapping["version"], "documented_mapping.version")

        if self.estimate is not None:
            if not isinstance(self.estimate, Mapping):
                raise ValueError("estimate must be null or an object")
            _exact_keys(
                self.estimate,
                {"method", "captured_at", "used_ratio", "remaining_ratio", "reset_at"},
                set(),
                "estimate",
            )
            _required_text(self.estimate["method"], "estimate.method")
            _timestamp(self.estimate["captured_at"], "estimate.captured_at")
            _ratio(self.estimate["used_ratio"], "estimate.used_ratio")
            _ratio(self.estimate["remaining_ratio"], "estimate.remaining_ratio")
            if self.estimate["reset_at"] is not None:
                _timestamp(self.estimate["reset_at"], "estimate.reset_at")

    def freshness(self, now: str) -> str:
        self.validate()
        current = _timestamp(now, "now")
        deadline = _timestamp(self.fresh_until, "fresh_until")
        return "fresh" if current <= deadline else "stale"

    def to_payload(self) -> Dict[str, Any]:
        self.validate()
        return {
            "schema": EVIDENCE_SCHEMA,
            "provider": self.provider,
            "mode": self.mode,
            "requested_model": self.requested_model,
            "scope": self.scope,
            "applicability": self.applicability,
            "provider_bucket_id": self.provider_bucket_id,
            "used_ratio": self.used_ratio,
            "remaining_ratio": self.remaining_ratio,
            "reset_at": self.reset_at,
            "signal": self.signal,
            "provenance": self.provenance,
            "captured_at": self.captured_at,
            "fresh_until": self.fresh_until,
            "documented_mapping": (
                dict(self.documented_mapping) if self.documented_mapping else None
            ),
            "estimate": dict(self.estimate) if self.estimate else None,
            "adapter": {"name": self.adapter_name, "version": self.adapter_version},
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ModelLineEvidence":
        if not isinstance(payload, Mapping):
            raise ValueError("evidence must be an object")
        required = {
            "schema", "provider", "mode", "requested_model", "scope",
            "applicability", "provider_bucket_id", "used_ratio", "remaining_ratio",
            "reset_at", "signal", "provenance", "captured_at", "fresh_until",
            "documented_mapping", "estimate", "adapter",
        }
        _exact_keys(payload, required, set(), "evidence")
        if payload["schema"] != EVIDENCE_SCHEMA:
            raise ValueError("unsupported evidence schema")
        adapter = payload["adapter"]
        if not isinstance(adapter, Mapping):
            raise ValueError("adapter must be an object")
        _exact_keys(adapter, {"name", "version"}, set(), "adapter")
        evidence = cls(
            provider=payload["provider"],
            mode=payload["mode"],
            requested_model=payload["requested_model"],
            scope=payload["scope"],
            applicability=payload["applicability"],
            provider_bucket_id=payload["provider_bucket_id"],
            used_ratio=payload["used_ratio"],
            remaining_ratio=payload["remaining_ratio"],
            reset_at=payload["reset_at"],
            signal=payload["signal"],
            provenance=payload["provenance"],
            captured_at=payload["captured_at"],
            fresh_until=payload["fresh_until"],
            documented_mapping=payload["documented_mapping"],
            estimate=payload["estimate"],
            adapter_name=adapter["name"],
            adapter_version=adapter["version"],
        )
        evidence.validate()
        return evidence


class ModelLineBudgetAdapter(ABC):
    """Fact adapter boundary; subclasses cannot return routing decisions."""

    @abstractmethod
    def probe(self, target: ProbeTarget) -> ModelLineEvidence:
        """Return pre-invocation evidence for one explicit target."""

    @abstractmethod
    def classify_refusal(self, observation: RefusalObservation) -> ModelLineEvidence:
        """Normalize one bounded terminal observation without raw body retention."""

    def probe_payload(self, target: ProbeTarget) -> Dict[str, Any]:
        target.validate()
        return self._checked_payload(target, self.probe(target))

    def refusal_payload(self, observation: RefusalObservation) -> Dict[str, Any]:
        observation.validate()
        return self._checked_payload(
            observation.target, self.classify_refusal(observation)
        )

    @staticmethod
    def _checked_payload(
        target: ProbeTarget, evidence: ModelLineEvidence
    ) -> Dict[str, Any]:
        if not isinstance(evidence, ModelLineEvidence):
            raise TypeError("adapter must return ModelLineEvidence")
        if (
            evidence.provider != target.provider
            or evidence.mode != target.mode
            or evidence.requested_model != target.requested_model
        ):
            raise ValueError("adapter evidence does not match the requested target")
        return evidence.to_payload()
