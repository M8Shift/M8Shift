"""Disabled, fixture-backed vendor evidence adapters for RFC 077 Slice B.

These adapters normalize already-retrieved, bounded response mappings.  They do
not import provider SDKs, discover credentials, open sockets, or make routing
decisions.  A later, separately authorized slice may supply a bounded external
retriever; the checked-in registrations remain disabled until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Type

from .base import (
    ModelLineBudgetAdapter,
    ModelLineEvidence,
    ProbeTarget,
    RefusalObservation,
)


Retriever = Callable[[ProbeTarget], Mapping[str, Any]]
Clock = Callable[[], str]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


def _ratio(limit: Any, remaining: Any) -> Optional[Tuple[float, float]]:
    if (
        isinstance(limit, bool)
        or isinstance(remaining, bool)
        or not isinstance(limit, (int, float))
        or not isinstance(remaining, (int, float))
        or limit <= 0
        or remaining < 0
        or remaining > limit
    ):
        return None
    remaining_ratio = float(remaining) / float(limit)
    return (1.0 - remaining_ratio, remaining_ratio)


def _usage_ratio(limit: Any, used: Any) -> Optional[Tuple[float, float]]:
    if (
        isinstance(limit, bool)
        or isinstance(used, bool)
        or not isinstance(limit, (int, float))
        or not isinstance(used, (int, float))
        or limit <= 0
        or used < 0
        or used > limit
    ):
        return None
    used_ratio = float(used) / float(limit)
    return (used_ratio, 1.0 - used_ratio)


def _documented_mapping(
    mappings: Mapping[str, Mapping[str, Any]],
    mapping_key: Any,
    requested_model: str,
) -> Optional[Mapping[str, str]]:
    if not isinstance(mapping_key, str):
        return None
    mapping = mappings.get(mapping_key)
    if mapping is None or requested_model not in mapping["models"]:
        return None
    return {
        "reference": mapping["reference"],
        "version": mapping["version"],
    }


class FixtureBackedVendorAdapter(ModelLineBudgetAdapter):
    """Common fail-closed retrieval boundary for disabled vendor subclasses."""

    provider = ""
    adapter_name = ""
    adapter_version = "1.0.0"

    def __init__(self, retriever: Retriever, clock: Optional[Clock] = None):
        if not callable(retriever):
            raise TypeError("retriever must be callable")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._retriever = retriever
        self._clock = clock or _utc_now

    def probe(self, target: ProbeTarget) -> ModelLineEvidence:
        target.validate()
        if target.provider != self.provider:
            raise ValueError("target provider does not match adapter provider")
        try:
            response = self._retriever(target)
        except Exception:
            return self._unknown(target, self._clock())
        if not isinstance(response, Mapping):
            return self._unknown(target, self._clock())
        captured_at = response.get("captured_at")
        if not _valid_timestamp(captured_at):
            captured_at = self._clock()
        try:
            return self._map_response(target, response, captured_at)
        except (KeyError, TypeError, ValueError):
            return self._unknown(target, captured_at)

    def classify_refusal(self, observation: RefusalObservation) -> ModelLineEvidence:
        observation.validate()
        if observation.target.provider != self.provider:
            raise ValueError("target provider does not match adapter provider")
        # The bounded observation deliberately contains no provider body, headers,
        # quota metric, or shared-group identity.  A status/code alone therefore
        # diagnoses a rejection but cannot prove model-line applicability.
        return self._unknown(
            observation.target,
            observation.captured_at,
            signal="rejection",
        )

    def _map_response(
        self,
        target: ProbeTarget,
        response: Mapping[str, Any],
        captured_at: str,
    ) -> ModelLineEvidence:
        if response.get("status") == "auth_absent":
            return self._unknown(target, captured_at)
        if response.get("status") == "throttle":
            return self._map_throttle(target, response, captured_at)
        if response.get("status") != "success":
            return self._unknown(target, captured_at)
        return self._map_success(target, response, captured_at)

    def _map_success(
        self,
        target: ProbeTarget,
        response: Mapping[str, Any],
        captured_at: str,
    ) -> ModelLineEvidence:
        raise NotImplementedError

    def _map_throttle(
        self,
        target: ProbeTarget,
        response: Mapping[str, Any],
        captured_at: str,
    ) -> ModelLineEvidence:
        return self._unknown(target, captured_at, signal="rejection")

    def _evidence(
        self,
        target: ProbeTarget,
        captured_at: str,
        *,
        scope: str,
        applicability: str,
        provider_bucket_id: Optional[str],
        used_ratio: Optional[float],
        remaining_ratio: Optional[float],
        reset_at: Optional[str],
        signal: str,
        provenance: str,
        fresh_until: Optional[str] = None,
        documented_mapping: Optional[Mapping[str, str]] = None,
        estimate: Optional[Mapping[str, Any]] = None,
    ) -> ModelLineEvidence:
        evidence = ModelLineEvidence(
            provider=target.provider,
            mode=target.mode,
            requested_model=target.requested_model,
            scope=scope,
            applicability=applicability,
            provider_bucket_id=provider_bucket_id,
            used_ratio=used_ratio,
            remaining_ratio=remaining_ratio,
            reset_at=reset_at,
            signal=signal,
            provenance=provenance,
            captured_at=captured_at,
            fresh_until=fresh_until or captured_at,
            documented_mapping=documented_mapping,
            estimate=estimate,
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
        )
        evidence.validate()
        return evidence

    def _unknown(
        self,
        target: ProbeTarget,
        captured_at: str,
        *,
        signal: str = "runtime_observation",
    ) -> ModelLineEvidence:
        return self._evidence(
            target,
            captured_at,
            scope="account",
            applicability="unknown",
            provider_bucket_id=None,
            used_ratio=None,
            remaining_ratio=None,
            reset_at=None,
            signal=signal,
            provenance="unknown",
        )


class AnthropicModelLineBudgetAdapter(FixtureBackedVendorAdapter):
    provider = "anthropic"
    adapter_name = "anthropic-model-line-fixture"
    documented_groups = {
        "sonnet-example": {
            "models": frozenset(("model-sonnet-example", "model-sonnet-example-2")),
            "reference": "provider-docs/anthropic-rate-limit-model-groups",
            "version": "2026-07-19",
        }
    }

    def _mapping_for_model(self, requested_model):
        for mapping in self.documented_groups.values():
            if requested_model in mapping["models"]:
                return {
                    "reference": mapping["reference"],
                    "version": mapping["version"],
                }
        return None

    def _map_success(self, target, response, captured_at):
        ratios = _ratio(response.get("limit_tokens"), response.get("remaining_tokens"))
        mapping = self._mapping_for_model(target.requested_model)
        if (
            target.mode != "api"
            or response.get("surface") != "response_headers"
            or ratios is None
            or mapping is None
        ):
            return self._unknown(target, captured_at)
        return self._evidence(
            target,
            captured_at,
            scope="model_group",
            applicability="documented_group",
            provider_bucket_id=None,
            used_ratio=ratios[0],
            remaining_ratio=ratios[1],
            reset_at=_text(response.get("reset_at")),
            signal="response_header",
            provenance="documented",
            fresh_until=_text(response.get("fresh_until")),
            documented_mapping=mapping,
        )

    def _map_throttle(self, target, response, captured_at):
        mapping = self._mapping_for_model(target.requested_model)
        if (
            target.mode != "api"
            or response.get("surface") != "response_headers"
            or mapping is None
        ):
            return super()._map_throttle(target, response, captured_at)
        return self._evidence(
            target,
            captured_at,
            scope="model_group",
            applicability="documented_group",
            provider_bucket_id=None,
            used_ratio=1.0,
            remaining_ratio=0.0,
            reset_at=_text(response.get("reset_at")),
            signal="rejection",
            provenance="documented",
            documented_mapping=mapping,
        )


class OpenAIModelLineBudgetAdapter(FixtureBackedVendorAdapter):
    provider = "openai"
    adapter_name = "openai-model-line-fixture"
    documented_groups = {
        "gpt-example-shared": {
            "models": frozenset(("model-gpt-example", "model-gpt-example-mini")),
            "reference": "provider-docs/openai-shared-limit-groups",
            "version": "2026-07-19",
        }
    }

    def _shared_group(self, target, response):
        mapping = _documented_mapping(
            self.documented_groups,
            response.get("shared_group"),
            target.requested_model,
        )
        bucket_id = _text(response.get("provider_bucket_id"))
        if target.mode != "api" or mapping is None or bucket_id is None:
            return None, None
        return bucket_id, mapping

    def _map_success(self, target, response, captured_at):
        ratios = _ratio(
            response.get("limit_requests"), response.get("remaining_requests")
        )
        bucket_id, mapping = self._shared_group(target, response)
        if (
            response.get("surface") != "response_headers"
            or ratios is None
            or bucket_id is None
        ):
            return self._unknown(target, captured_at)
        return self._evidence(
            target,
            captured_at,
            scope="model_group",
            applicability="documented_group",
            provider_bucket_id=bucket_id,
            used_ratio=ratios[0],
            remaining_ratio=ratios[1],
            reset_at=_text(response.get("reset_at")),
            signal="response_header",
            provenance="documented",
            fresh_until=_text(response.get("fresh_until")),
            documented_mapping=mapping,
        )

    def _map_throttle(self, target, response, captured_at):
        bucket_id, mapping = self._shared_group(target, response)
        if response.get("surface") != "response_headers" or bucket_id is None:
            return super()._map_throttle(target, response, captured_at)
        return self._evidence(
            target,
            captured_at,
            scope="model_group",
            applicability="documented_group",
            provider_bucket_id=bucket_id,
            used_ratio=1.0,
            remaining_ratio=0.0,
            reset_at=_text(response.get("reset_at")),
            signal="rejection",
            provenance="documented",
            documented_mapping=mapping,
        )


class GoogleModelLineBudgetAdapter(FixtureBackedVendorAdapter):
    provider = "google"
    adapter_name = "google-model-line-fixture"
    documented_metrics = {
        "generativelanguage.googleapis.com/model-example-requests": {
            "models": frozenset(("model-gemini-example",)),
            "reference": "provider-docs/google-model-dimensioned-quota",
            "version": "2026-07-19",
        }
    }

    def _map_success(self, target, response, captured_at):
        if response.get("surface") == "console":
            return self._evidence(
                target,
                captured_at,
                scope="model",
                applicability="unknown",
                provider_bucket_id=None,
                used_ratio=None,
                remaining_ratio=None,
                reset_at=None,
                signal="console",
                provenance="console_only",
            )
        ratios = _ratio(response.get("limit"), response.get("remaining"))
        metric = _text(response.get("quota_metric"))
        mapping = _documented_mapping(
            self.documented_metrics, metric, target.requested_model
        )
        if (
            target.mode != "cloud"
            or response.get("surface") != "quota_metric"
            or response.get("model_dimension") != target.requested_model
            or ratios is None
            or metric is None
            or mapping is None
        ):
            return self._unknown(target, captured_at)
        return self._evidence(
            target,
            captured_at,
            scope="model",
            applicability="exact_model",
            provider_bucket_id=metric,
            used_ratio=ratios[0],
            remaining_ratio=ratios[1],
            reset_at=_text(response.get("reset_at")),
            signal="quota_metric",
            provenance="documented",
            fresh_until=_text(response.get("fresh_until")),
            documented_mapping=mapping,
        )

    def _map_throttle(self, target, response, captured_at):
        metric = _text(response.get("quota_metric"))
        mapping = _documented_mapping(
            self.documented_metrics, metric, target.requested_model
        )
        if (
            target.mode != "cloud"
            or response.get("surface") != "quota_failure"
            or response.get("model_dimension") != target.requested_model
            or metric is None
            or mapping is None
        ):
            return super()._map_throttle(target, response, captured_at)
        return self._evidence(
            target,
            captured_at,
            scope="model",
            applicability="exact_model",
            provider_bucket_id=metric,
            used_ratio=1.0,
            remaining_ratio=0.0,
            reset_at=_text(response.get("reset_at")),
            signal="rejection",
            provenance="documented",
            documented_mapping=mapping,
        )


class MistralModelLineBudgetAdapter(FixtureBackedVendorAdapter):
    provider = "mistral"
    adapter_name = "mistral-model-line-fixture"
    documented_models = {
        "model-mistral-example": {
            "models": frozenset(("model-mistral-example",)),
            "reference": "provider-docs/mistral-per-model-limits",
            "version": "2026-07-19",
        }
    }

    def _map_success(self, target, response, captured_at):
        ratios = _usage_ratio(
            response.get("configured_limit"), response.get("observed_usage")
        )
        mapping = _documented_mapping(
            self.documented_models, response.get("model"), target.requested_model
        )
        if (
            target.mode != "api"
            or response.get("surface") != "admin_history"
            or response.get("model") != target.requested_model
            or ratios is None
            or mapping is None
        ):
            return self._unknown(target, captured_at)
        # Admin history supports a warning/forecast only.  Provider-reported live
        # remaining capacity deliberately stays null.
        estimate = {
            "method": "configured-limit-minus-admin-history",
            "captured_at": captured_at,
            "used_ratio": ratios[0],
            "remaining_ratio": ratios[1],
            "reset_at": _text(response.get("history_reset_at")),
        }
        return self._evidence(
            target,
            captured_at,
            scope="model",
            applicability="exact_model",
            provider_bucket_id=None,
            used_ratio=None,
            remaining_ratio=None,
            reset_at=None,
            signal="usage_report",
            provenance="documented",
            fresh_until=_text(response.get("fresh_until")),
            documented_mapping=mapping,
            estimate=estimate,
        )


@dataclass(frozen=True)
class VendorAdapterRegistration:
    name: str
    adapter_class: Type[FixtureBackedVendorAdapter]
    enabled: bool = False
    retrieval: str = "fixture_only"


VENDOR_ADAPTER_REGISTRY: Dict[str, VendorAdapterRegistration] = {
    "anthropic-model-line": VendorAdapterRegistration(
        "anthropic-model-line", AnthropicModelLineBudgetAdapter
    ),
    "openai-model-line": VendorAdapterRegistration(
        "openai-model-line", OpenAIModelLineBudgetAdapter
    ),
    "google-model-line": VendorAdapterRegistration(
        "google-model-line", GoogleModelLineBudgetAdapter
    ),
    "mistral-model-line": VendorAdapterRegistration(
        "mistral-model-line", MistralModelLineBudgetAdapter
    ),
}
