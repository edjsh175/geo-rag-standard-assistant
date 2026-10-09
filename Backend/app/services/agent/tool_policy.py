"""Deterministic execution policy for Agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from app.services.agent.tools import ToolSpec


class ToolRiskLevel(str, Enum):
    """Risk tier of a tool for Human-in-the-loop (HITL) approval governance."""

    READ_ONLY = "READ_ONLY"
    MUTATING = "MUTATING"
    HIGH_RISK = "HIGH_RISK"


DEFAULT_TOOL_RISK_MAP: dict[str, ToolRiskLevel] = {
    "retrieve_kb": ToolRiskLevel.READ_ONLY,
    "list_applicable_standards": ToolRiskLevel.READ_ONLY,
    "reuse_evidence": ToolRiskLevel.READ_ONLY,
    "limitation": ToolRiskLevel.READ_ONLY,
    "inspect_layer_features": ToolRiskLevel.READ_ONLY,
    "get_feature_geometry": ToolRiskLevel.READ_ONLY,
    "locate_map": ToolRiskLevel.MUTATING,
    "select_region": ToolRiskLevel.MUTATING,
    "set_layer_visibility": ToolRiskLevel.MUTATING,
    "set_vector_style": ToolRiskLevel.MUTATING,
    "fit_vector_layer": ToolRiskLevel.MUTATING,
    "render_geojson_layer": ToolRiskLevel.MUTATING,
    "import_vector_dataset": ToolRiskLevel.HIGH_RISK,
}


def classify_tool_risk(tool_name: str, spec: ToolSpec | None = None) -> ToolRiskLevel:
    """Classify the risk level of a tool invocation."""
    if spec is not None and getattr(spec, "risk_level", None):
        return getattr(spec, "risk_level")
    if spec is not None and spec.confirmation_required:
        return ToolRiskLevel.HIGH_RISK
    if tool_name in DEFAULT_TOOL_RISK_MAP:
        return DEFAULT_TOOL_RISK_MAP[tool_name]
    if spec is not None and spec.side_effect:
        return ToolRiskLevel.MUTATING
    return ToolRiskLevel.READ_ONLY


class ToolPolicyViolation(RuntimeError):
    """Base error for execution-policy violations."""


class ToolPermissionDenied(ToolPolicyViolation):
    """Raised when a caller lacks a ToolSpec permission."""


class ToolConfirmationRequired(ToolPolicyViolation):
    """Raised when a ToolSpec requires explicit call confirmation."""


class ToolSideEffectDenied(ToolPolicyViolation):
    """Raised when a side-effect tool is called in an execution context that prohibits side effects."""


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    permissions: frozenset[str] = field(default_factory=frozenset)
    confirmed_tool_call_ids: frozenset[str] = field(default_factory=frozenset)
    allow_side_effects: bool = True
    allowed_providers: frozenset[str] | None = None
    require_approval_levels: frozenset[ToolRiskLevel] = field(default_factory=frozenset)


class ToolPolicy:
    """Pure policy checks applied immediately before physical execution."""

    def authorize(
        self,
        *,
        spec: ToolSpec,
        tool_call_id: str,
        context: ToolExecutionContext,
    ) -> None:
        if spec.side_effect and not context.allow_side_effects:
            raise ToolSideEffectDenied(
                f"TOOL_SIDE_EFFECT_DENIED: '{spec.name}' has side-effects which are "
                "disallowed in the current execution context"
            )

        if context.allowed_providers is not None and spec.provider not in context.allowed_providers:
            raise ToolPermissionDenied(
                f"TOOL_PROVIDER_DENIED: '{spec.name}' provider '{spec.provider}' is not "
                "permitted in the current execution context"
            )

        required_permission = (spec.permission or "").strip()
        if required_permission and required_permission not in context.permissions:
            raise ToolPermissionDenied(
                f"TOOL_PERMISSION_DENIED: '{spec.name}' requires permission "
                f"'{required_permission}'"
            )

        risk_level = classify_tool_risk(spec.name, spec)
        needs_confirmation = (
            spec.confirmation_required
            or (risk_level in context.require_approval_levels)
        )
        if needs_confirmation and tool_call_id not in context.confirmed_tool_call_ids:
            raise ToolConfirmationRequired(
                f"TOOL_CONFIRMATION_REQUIRED: '{spec.name}' requires explicit confirmation"
            )

    @staticmethod
    def effective_timeout_seconds(
        *,
        spec: ToolSpec,
        runtime_remaining_seconds: float | None,
    ) -> float:
        tool_timeout = float(spec.timeout)
        if tool_timeout <= 0:
            raise ToolPolicyViolation(
                f"TOOL_POLICY_INVALID: '{spec.name}' timeout must be positive"
            )
        if runtime_remaining_seconds is None:
            return tool_timeout
        if runtime_remaining_seconds <= 0:
            raise ToolPolicyViolation(
                "RESOURCE_FUSE: runtime deadline exhausted before tool execution"
            )
        return min(tool_timeout, float(runtime_remaining_seconds))


__all__ = [
    "DEFAULT_TOOL_RISK_MAP",
    "ToolConfirmationRequired",
    "ToolExecutionContext",
    "ToolPermissionDenied",
    "ToolPolicy",
    "ToolPolicyViolation",
    "ToolRiskLevel",
    "ToolSideEffectDenied",
    "classify_tool_risk",
]
