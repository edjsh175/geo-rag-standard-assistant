"""LangChain-facing tool contracts for the GeoAI Agent.

LangChain owns the generic tool schema/message shape. GeoAI remains the only
execution authority: these tools are schema carriers and must never execute a
domain capability directly. Actual execution always goes through ToolRuntime.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.services.agent.controller_protocol import (
    TOOL_CALL_ACTION,
    ControllerDecision,
    ExecutableActionState,
)
from app.services.agent.tools import ToolRegistry, ToolSpec


def _tool_description(spec: ToolSpec) -> str:
    parts = [spec.description.strip()]
    if spec.use_when:
        parts.append(f"Use when: {spec.use_when.strip()}")
    if spec.avoid_when:
        parts.append(f"Avoid when: {spec.avoid_when.strip()}")
    return "\n".join(part for part in parts if part)


def _schema_only_tool(spec: ToolSpec) -> BaseTool:
    def _blocked_sync(**_: Any) -> None:
        raise RuntimeError(
            f"LangChain tool '{spec.name}' is schema-only; execute through GeoAI ToolRuntime"
        )

    async def _blocked_async(**_: Any) -> None:
        raise RuntimeError(
            f"LangChain tool '{spec.name}' is schema-only; execute through GeoAI ToolRuntime"
        )

    return StructuredTool.from_function(
        func=_blocked_sync,
        coroutine=_blocked_async,
        name=spec.name,
        description=_tool_description(spec),
        args_schema=spec.input_model,
    )


def build_langchain_tools(
    registry: ToolRegistry,
    available_capabilities: Sequence[str] | set[str] | frozenset[str],
) -> tuple[BaseTool, ...]:
    """Project the current executable capability surface into LangChain tools."""

    return tuple(
        _schema_only_tool(spec)
        for spec in registry.specs_for(set(available_capabilities))
    )


def openai_tool_schemas(tools: Sequence[BaseTool]) -> tuple[dict[str, Any], ...]:
    """Convert LangChain tools to the provider-neutral OpenAI tool schema shape."""

    return tuple(dict(convert_to_openai_tool(tool)) for tool in tools)


def controller_decision_from_tool_call(
    tool_call: Mapping[str, Any],
    *,
    state: ExecutableActionState,
    registry: ToolRegistry,
) -> ControllerDecision:
    """Adapt one standard LangChain ToolCall into GeoAI's canonical decision.

    The adapter is intentionally thin: current capability availability and
    Pydantic argument validation remain authoritative in GeoAI.
    """

    name = str(tool_call.get("name") or "").strip()
    if not name or name not in state.available_capabilities:
        raise ValueError(
            f"malformed_tool_call: tool '{name}' is not available in current state"
        )

    raw_args = tool_call.get("args")
    if not isinstance(raw_args, Mapping):
        raise ValueError("malformed_tool_call: args must be an object")

    validated_args = registry.validate_arguments(name, raw_args)
    call_id = str(tool_call.get("id") or "").strip() or str(uuid4())
    return ControllerDecision(
        action=TOOL_CALL_ACTION,
        tool=name,
        arguments=dict(validated_args),
        tool_call_id=call_id,
    )
