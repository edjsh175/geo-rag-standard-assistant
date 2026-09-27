"""Test Phase S: S-05 tool timeout, S-06 trace observability API, S-07 durable ModelCallAudit, S-08 budget truth."""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.search_models import SearchResponse
from app.services.agent.events import AgentEvent
from app.services.agent.model_client import (
    LLMConfigStageModelClient,
    ModelCallAudit,
    ModelRequest,
)
from app.services.agent.runtime import AgentRunResult
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tool_policy import ToolPolicy, ToolPolicyViolation
from app.services.agent.tool_runtime import ToolCall, ToolExecutionError, ToolRuntime
from app.services.agent.tools import ToolRegistry, ToolSpec
from app.services.agent.trace_service import AgentTraceService


# ---------------------------------------------------------------------------
# S-05: Tool Timeout Enforcement
# ---------------------------------------------------------------------------

from pydantic import BaseModel

class DummyInput(BaseModel):
    pass

def test_s05_tool_policy_effective_timeout():
    """Verify ToolPolicy.effective_timeout_seconds clamps to minimum of spec.timeout and runtime_remaining_seconds."""
    spec = ToolSpec(name="test_tool", description="desc", input_model=DummyInput, timeout=10.0)

    # When runtime has plenty of time, use tool timeout
    assert ToolPolicy.effective_timeout_seconds(spec=spec, runtime_remaining_seconds=30.0) == 10.0

    # When runtime has less time than tool timeout, clamp to remaining runtime
    assert ToolPolicy.effective_timeout_seconds(spec=spec, runtime_remaining_seconds=3.5) == 3.5

    # When runtime has no deadline, use tool timeout
    assert ToolPolicy.effective_timeout_seconds(spec=spec, runtime_remaining_seconds=None) == 10.0

    # When runtime has expired, raise ToolPolicyViolation
    with pytest.raises(ToolPolicyViolation, match="RESOURCE_FUSE: runtime deadline exhausted"):
        ToolPolicy.effective_timeout_seconds(spec=spec, runtime_remaining_seconds=0.0)


@pytest.mark.asyncio
async def test_s05_tool_runtime_enforces_timeout():
    """Verify ToolRuntime.execute times out and raises ToolExecutionError when tool execution exceeds timeout."""
    spec = ToolSpec(name="slow_tool", description="desc", input_model=DummyInput, timeout=0.05)
    registry = ToolRegistry((spec,))

    runtime = ToolRuntime(
        retrieval_port=MagicMock(),
        evidence_ledger=MagicMock(),
        registry=registry,
    )

    # Monkey patch _execute_validated to sleep longer than 0.05s
    async def slow_execution(*args, **kwargs):
        await asyncio.sleep(0.5)

    runtime._execute_validated = slow_execution

    call = ToolCall(tool_call_id="call-1", name="slow_tool", arguments={})

    with pytest.raises(ToolExecutionError, match="TOOL_TIMEOUT: 'slow_tool' exceeded"):
        await runtime.execute(turn_id="turn-1", call=call)


# ---------------------------------------------------------------------------
# S-07: Durable ModelCallAudit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s07_model_client_invokes_durable_call_audit_sink():
    """Verify LLMConfigStageModelClient completes and invokes call_audit_sink with audit record and context."""
    llm_mock = MagicMock()
    llm_mock.chat_completion = AsyncMock(return_value="decision payload")
    llm_mock.resolve_main_model = MagicMock(return_value="gpt-4o")

    recorded_audits = []

    async def test_call_audit_sink(audit: ModelCallAudit, audit_context):
        recorded_audits.append((audit, audit_context))

    client = LLMConfigStageModelClient(
        llm_config=llm_mock,
        audit_sink=AsyncMock(),
        call_audit_sink=test_call_audit_sink,
    )

    request = ModelRequest(
        stage="controller",
        messages=({"role": "user", "content": "hi"},),
        call_id="call-test-77",
        audit_context={
            "principal_id": "user-audit",
            "session_id": "sess-audit",
            "turn_id": "turn-1",
            "trace_id": "trace-xyz",
            "context_snapshot_id": "snap-999",
        },
    )

    response = await client.complete(request)
    assert response.content == "decision payload"
    assert len(recorded_audits) == 1

    audit_entry, ctx = recorded_audits[0]
    assert audit_entry.call_id == "call-test-77"
    assert audit_entry.stage == "controller"
    assert audit_entry.outcome == "success"
    assert audit_entry.elapsed_seconds >= 0.0
    assert ctx["trace_id"] == "trace-xyz"
    assert ctx["context_snapshot_id"] == "snap-999"


# ---------------------------------------------------------------------------
# S-06: Trace Observability Query API & Service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_s06_trace_service_aggregates_turn_and_trace_by_id():
    """Verify AgentTraceService aggregates turn events, model audits, snapshots, and can look up by trace_id."""
    store = InMemoryAgentStore()
    principal_id = "admin:alice"
    session_id = "sess-obs-1"
    turn_id = "turn-1"
    trace_id = "trace-obs-123"

    events = [
        AgentEvent(
            event_id="evt-1",
            event_type="user_message",
            session_id=session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={"text": "search area A"},
            sequence=1,
            created_at=datetime.now(timezone.utc),
        ),
        AgentEvent(
            event_id="evt-2",
            event_type="model_call_audited",
            session_id=session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={
                "call_id": "call-1",
                "stage": "controller",
                "attempt": 1,
                "model_name": "qwen",
                "elapsed_seconds": 0.45,
                "outcome": "success",
                "context_snapshot_id": "snap-c1",
            },
            sequence=2,
            created_at=datetime.now(timezone.utc),
        ),
        AgentEvent(
            event_id="evt-3",
            event_type="browser_tool_requested",
            session_id=session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={
                "tool_name": "locate_map",
                "tool_call_id": "tc-loc-1",
                "arguments": {"longitude": 120.0, "latitude": 30.0},
            },
            sequence=3,
            created_at=datetime.now(timezone.utc),
        ),
        AgentEvent(
            event_id="evt-4",
            event_type="publication_completed",
            session_id=session_id,
            turn_id=turn_id,
            trace_id=trace_id,
            payload={
                "publication_state": "tool_execution_required",
                "visible_text": "Locating map...",
            },
            sequence=4,
            created_at=datetime.now(timezone.utc),
        ),
    ]

    for ev in events:
        await store.append_event(principal_id=principal_id, event=ev)

    trace_service = AgentTraceService(session_store=store)

    # 1. Get turn trace
    trace_data = await trace_service.get_turn_trace(
        principal_id=principal_id,
        session_id=session_id,
        turn_id=turn_id,
    )
    assert trace_data is not None
    assert trace_data["session_id"] == session_id
    assert trace_data["turn_id"] == turn_id
    assert trace_data["trace_id"] == trace_id
    assert trace_data["total_events"] == 4
    assert len(trace_data["ordered_events"]) == 4
    assert len(trace_data["model_call_audits"]) == 1
    assert trace_data["model_call_audits"][0]["call_id"] == "call-1"
    assert trace_data["context_snapshot_ids"] == ["snap-c1"]
    assert len(trace_data["tool_calls"]) == 1
    assert trace_data["tool_calls"][0]["tool_name"] == "locate_map"
    assert trace_data["publication_result"]["publication_state"] == "tool_execution_required"

    # 2. Get trace by trace_id
    by_trace_id = await trace_service.get_trace_by_id(
        principal_id=principal_id,
        trace_id=trace_id,
    )
    assert by_trace_id is not None
    assert by_trace_id["trace_id"] == trace_id
    assert by_trace_id["turn_id"] == turn_id


# ---------------------------------------------------------------------------
# S-08: Budget Truth & Propagated Remaining Steps/Seconds
# ---------------------------------------------------------------------------

def test_s08_agent_run_result_and_search_response_budget_fields():
    """Verify remaining_steps and remaining_seconds exist and serialize cleanly on AgentRunResult and SearchResponse."""
    from app.services.agent.contracts import MapAction
    from app.services.agent.publication import BrowserToolExecutionRequired

    result = AgentRunResult(
        session_id="sess-b",
        turn_id="turn-1",
        trace_id="tr-1",
        result=BrowserToolExecutionRequired(
            tool_call_id="call-b",
            tool_name="locate_map",
            continuation_token="token-b",
            map_action=MapAction(type="locate_map", target="map"),
        ),
        frozen_evidence=None,
        review=None,
        events=(),
        remaining_steps=5,
        remaining_seconds=42.123,
    )
    assert result.remaining_steps == 5
    assert result.remaining_seconds == 42.123

    resp = SearchResponse(
        query="find roads",
        remaining_steps=result.remaining_steps,
        remaining_seconds=result.remaining_seconds,
    )
    assert resp.remaining_steps == 5
    assert resp.remaining_seconds == 42.123

    dumped = resp.model_dump()
    assert dumped["remaining_steps"] == 5
    assert dumped["remaining_seconds"] == 42.123


@pytest.mark.asyncio
async def test_s06_agent_routes_handler():
    """Verify get_turn_trace route handler enforces principal defaulting and 404 on missing trace."""
    from app.api.agent_routes import get_turn_trace
    from app.core.auth import AdminIdentity
    from fastapi import HTTPException

    admin = AdminIdentity(username="alice", role="admin")
    mock_service = MagicMock()
    mock_service.get_turn_trace = AsyncMock(return_value={"turn_id": "turn-1", "events": []})

    resp = await get_turn_trace(
        session_id="s-1",
        turn_id="turn-1",
        principal_id=None,
        current_admin=admin,
        trace_service=mock_service,
    )
    assert resp["turn_id"] == "turn-1"
    mock_service.get_turn_trace.assert_awaited_once_with(
        principal_id="admin:alice",
        session_id="s-1",
        turn_id="turn-1",
    )

    mock_service.get_turn_trace = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc_info:
        await get_turn_trace(
            session_id="s-1",
            turn_id="turn-none",
            principal_id=None,
            current_admin=admin,
            trace_service=mock_service,
        )
    assert exc_info.value.status_code == 404

