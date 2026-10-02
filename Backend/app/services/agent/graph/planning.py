"""LangGraph-owned planning loop for Controller and server-side tools.

This subgraph intentionally stops at semantic terminal decisions
(direct/clarify/limitation/compose) and browser execution handoff. Durable
business facts remain outside graph state and are accessed through the
request-scoped context callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .state import AgentGraphState


PlanningTerminalKind = Literal[
    "control",
    "browser_execution_required",
    "resource_fuse",
    "retrieval_unavailable",
]


@dataclass(slots=True)
class PlanningGraphContext:
    project_context: Callable[[], Awaitable[Any]]
    decide: Callable[[Any], Awaitable[Any]]
    execute_tool: Callable[[Any], Awaitable[Any]]
    latest_projection: Any | None = None
    latest_decision: Any | None = None
    latest_tool_outcome: Any | None = None
    handle_control: Callable[[Any, Any], Awaitable[str | None]] | None = None
    should_continue: Callable[[], Awaitable[str | None]] | None = None
    after_tool: Callable[[Any], Awaitable[str | None]] | None = None
    finalize_terminal: Callable[[str, Any | None, Any | None, Any | None], Awaitable[Any]] | None = None
    terminal_result: Any | None = None


async def _project_context(
    state: AgentGraphState,
    runtime: Runtime[PlanningGraphContext],
) -> AgentGraphState:
    if runtime.context.should_continue is not None:
        terminal = await runtime.context.should_continue()
        if terminal:
            return {"publication_kind": terminal}
    runtime.context.latest_projection = await runtime.context.project_context()
    return {}


async def _plan(
    state: AgentGraphState,
    runtime: Runtime[PlanningGraphContext],
) -> AgentGraphState:
    decision = await runtime.context.decide(runtime.context.latest_projection)
    runtime.context.latest_decision = decision
    action = getattr(decision, "action", None)
    if not action:
        name = getattr(decision, "name", "")
        action = name if name in {"compose_answer", "direct_answer", "clarify", "limitation"} else "tool_call"
    update: AgentGraphState = {"decision_kind": action}
    if action == "tool_call":
        tool_name = getattr(decision, "tool", None) or getattr(decision, "name", None)
        update.update(
            tool_name=tool_name,
            tool_call_id=decision.tool_call_id,
            tool_arguments=dict(decision.arguments),
        )
    return update


async def _handle_control(
    state: AgentGraphState,
    runtime: Runtime[PlanningGraphContext],
) -> AgentGraphState:
    if runtime.context.handle_control is None:
        action = str(state.get("decision_kind") or "").strip()
        return {"publication_kind": action} if action else {}
    terminal = await runtime.context.handle_control(
        runtime.context.latest_decision,
        runtime.context.latest_projection,
    )
    if terminal:
        return {"publication_kind": terminal}
    return {}


async def _finalize_terminal(
    state: AgentGraphState,
    runtime: Runtime[PlanningGraphContext],
) -> AgentGraphState:
    kind = str(state.get("publication_kind") or "").strip()
    if not kind or runtime.context.finalize_terminal is None:
        return {}
    runtime.context.terminal_result = await runtime.context.finalize_terminal(
        kind,
        runtime.context.latest_decision,
        runtime.context.latest_projection,
        runtime.context.latest_tool_outcome,
    )
    return {}


async def _execute_tool(
    state: AgentGraphState,
    runtime: Runtime[PlanningGraphContext],
) -> AgentGraphState:
    outcome = await runtime.context.execute_tool(runtime.context.latest_decision)
    runtime.context.latest_tool_outcome = outcome
    if outcome.terminal_error:
        return {"publication_kind": outcome.terminal_error}
    observation = outcome.observation
    if runtime.context.after_tool is not None:
        terminal = await runtime.context.after_tool(outcome)
        if terminal:
            return {"publication_kind": terminal}
    if observation is not None and observation.status == "browser_execution_required":
        return {
            "tool_outcome_kind": "browser_execution_required",
            "publication_kind": "browser_execution_required",
        }
    return {"tool_outcome_kind": "server_completed"}


def _route_after_plan(state: AgentGraphState) -> str:
    if state.get("publication_kind"):
        return "finalize_terminal"
    return "execute_tool" if state.get("decision_kind") == "tool_call" else "handle_control"


def _route_after_projection(state: AgentGraphState) -> str:
    return "finalize_terminal" if state.get("publication_kind") else "plan"


def _route_after_tool(state: AgentGraphState) -> str:
    if state.get("publication_kind"):
        return "finalize_terminal"
    return "project_context"


def _route_after_control(state: AgentGraphState) -> str:
    return "finalize_terminal" if state.get("publication_kind") else "project_context"


def build_planning_graph():
    builder = StateGraph(AgentGraphState, context_schema=PlanningGraphContext)
    builder.add_node("project_context", _project_context)
    builder.add_node("plan", _plan)
    builder.add_node("execute_tool", _execute_tool)
    builder.add_node("handle_control", _handle_control)
    builder.add_node("finalize_terminal", _finalize_terminal)
    builder.add_edge(START, "project_context")
    builder.add_conditional_edges(
        "project_context",
        _route_after_projection,
        {"plan": "plan", "finalize_terminal": "finalize_terminal"},
    )
    builder.add_conditional_edges(
        "plan",
        _route_after_plan,
        {
            "execute_tool": "execute_tool",
            "handle_control": "handle_control",
            "finalize_terminal": "finalize_terminal",
        },
    )
    builder.add_conditional_edges(
        "handle_control",
        _route_after_control,
        {"project_context": "project_context", "finalize_terminal": "finalize_terminal"},
    )
    builder.add_conditional_edges(
        "execute_tool",
        _route_after_tool,
        {"project_context": "project_context", "finalize_terminal": "finalize_terminal"},
    )
    builder.add_edge("finalize_terminal", END)
    return builder.compile(name="geoai-agent-planning")


__all__ = ["PlanningGraphContext", "build_planning_graph"]
