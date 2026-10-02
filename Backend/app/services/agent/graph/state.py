"""Minimal transient LangGraph state.

Durable business facts stay in AgentStore / EvidenceLedger / browser receipts.
The graph keeps only stable identifiers and transient routing facts.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


DecisionKind = Literal[
    "tool_call",
    "compose_answer",
    "direct_answer",
    "clarify",
    "limitation",
]
ToolOutcomeKind = Literal[
    "server_completed",
    "browser_execution_required",
]


class AgentGraphState(TypedDict, total=False):
    principal_id: str
    session_id: str
    turn_id: str
    trace_id: str
    question: str

    # Transient orchestration facts only. Payload-bearing durable state is
    # intentionally referenced by IDs and reloaded from authoritative stores.
    decision_kind: DecisionKind
    tool_name: str
    tool_call_id: str
    tool_arguments: dict[str, Any]
    tool_outcome_kind: ToolOutcomeKind
    selected_evidence_ids: tuple[str, ...]
    publication_kind: str
