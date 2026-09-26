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


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    permissions: frozenset[str] = field(default_factory=frozenset)
    confirmed_tool_call_ids: frozenset[str] = field(default_factory=frozenset)


class ToolPolicy:
    """Pure policy checks applied immediately before physical execution."""

    def authorize(
        self,
        *,
        spec: ToolSpec,
        tool_call_id: str,
        context: ToolExecutionContext,
    ) -> None:
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
]
