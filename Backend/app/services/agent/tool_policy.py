"""Deterministic execution policy for Agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.agent.tools import ToolSpec


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

        if spec.confirmation_required and tool_call_id not in context.confirmed_tool_call_ids:
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
    "ToolConfirmationRequired",
    "ToolExecutionContext",
    "ToolPermissionDenied",
    "ToolPolicy",
    "ToolPolicyViolation",
    "ToolSideEffectDenied",
]
