"""End-to-end tests for browser GIS continuation persistence, recovery, and audit snapshots."""

from __future__ import annotations

import pytest

from app.services.agent.publication import PublishedResult
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tool_runtime import ToolCall
from app.services.agent.tools import build_default_tool_registry
from app.services.rag.contracts import RetrievalCandidate, RetrievalDiagnostics, RetrievalPort, RetrievalResult


class DummyRetrievalPort(RetrievalPort):
    async def retrieve(self, query):
        item = RetrievalCandidate(
            chunk_id="chunk-gis-1",
            text="杭州市西湖区控制性详细规划：容积率2.5，建筑限高50米。",
            score=0.95,
            metadata={"doc_name": "西湖控规"},
        )
        return RetrievalResult(
            query=query,
            candidates=(item,),
            diagnostics=RetrievalDiagnostics(retrieval_mode="hybrid", total_candidates=1),
        )

    async def fetch_chunks(self, chunk_ids):
        return ()


class DummyController:
    def __init__(self) -> None:
        self.step = 0
        self.tool_registry = build_default_tool_registry()

    async def decide(self, **kwargs):
        self.step += 1
        if self.step == 1:
            return ToolCall(
                name="set_layer_visibility",
                arguments={"layer_ref": "layer-xihu-zoning", "visible": True},
                tool_call_id="call-browser-1",
            )
        # In step 2, retrieve evidence and compose answer
        # Collect available evidence ids from kwargs
        working_evidence = kwargs.get("working_evidence", ())
        ev_ids = [e["evidence_id"] for e in working_evidence if "evidence_id" in e]
        return ToolCall(
            name="compose_answer",
            arguments={"evidence_ids": ev_ids},
            tool_call_id="call-compose-2",
        )


class DummyAnswerGenerator:
    async def generate(self, **kwargs):
        from app.services.agent.answer_generator import GeneratedAnswer
        return GeneratedAnswer(
            kind="direct",
            answer="已在地图上为您显示西湖区规划图层 [E1]。",
            citations=("E1",),
        )


@pytest.mark.asyncio
async def test_browser_gis_continuation_persists_and_recovers_across_restarts():
    # Shared persistent store across runtime restarts
    shared_store = InMemoryAgentStore()
    retrieval_port = DummyRetrievalPort()

    # Initial runtime instance before restart
    controller_1 = DummyController()
    runtime_1 = AgentRuntime(
        retrieval_port=retrieval_port,
        controller=controller_1,
        answer_generator=DummyAnswerGenerator(),
        session_store=shared_store,
    )

    # 1. Start session, trigger browser GIS tool
    req_1 = AgentRunRequest(
        question="请在地图上显示西湖区控规图层",
        session_id="session-recover-1",
        principal_id="user-gis-1",
    )
    result_1 = await runtime_1.run(req_1)

    assert result_1.publication_state == "tool_execution_required"
    assert result_1.continuation_token is not None
    token = result_1.continuation_token

    # Verify pending browser execution was persisted in store
    pending_in_store = await shared_store.get_pending_execution("user-gis-1", "session-recover-1")
    assert pending_in_store is not None
    assert pending_in_store.token == token
    assert pending_in_store.tool_name == "set_layer_visibility"

    # 2. Simulate Backend server restart:
    # Destroy runtime_1 and create a completely fresh runtime_2 with newly initialized memory
    controller_2 = DummyController()
    controller_2.step = 1  # Next step will compose and publish
    runtime_2 = AgentRuntime(
        retrieval_port=retrieval_port,
        controller=controller_2,
        answer_generator=DummyAnswerGenerator(),
        session_store=shared_store,
    )

    # 3. Frontend reports browser tool execution receipt with continuation_token
    receipt = {
        "tool_call_id": "call-browser-1",
        "tool_name": "set_layer_visibility",
        "status": "succeeded",
        "output": {"layer_ref": "layer-xihu-zoning", "visible": True},
        "effect": {"layers_updated": ["layer-xihu-zoning"]},
        "map_context": {"bbox": [120.1, 30.2, 120.2, 30.3]},
    }
    req_2 = AgentRunRequest(
        question="请在地图上显示西湖区控规图层",
        session_id="session-recover-1",
        principal_id="user-gis-1",
        continuation_token=token,
        browser_tool_receipt=receipt,
    )
    result_2 = await runtime_2.run(req_2)

    # 4. Verify completed successfully after recovery
    assert result_2.publication_state == "published"
    assert "西湖区规划图层" in result_2.answer.answer
    assert result_2.continuation_token is None

    # Pending execution in store must be cleared
    pending_after = await shared_store.get_pending_execution("user-gis-1", "session-recover-1")
    assert pending_after is None

    # Verify audit snapshots were recorded in the store
    snap_ctrl = await shared_store.get_latest_snapshot("user-gis-1", "session-recover-1", stage="controller")
    assert snap_ctrl is not None
    assert snap_ctrl.projection_hash != ""

    snap_ans = await shared_store.get_latest_snapshot("user-gis-1", "session-recover-1", stage="answer")
    assert snap_ans is not None
    assert snap_ans.projection_hash != ""
