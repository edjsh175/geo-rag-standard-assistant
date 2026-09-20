from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.tool_runtime import (
    ResourceFuse,
    ResourceFuseExceeded,
    ToolCall,
    ToolRuntime,
    build_default_tool_registry,
)
from app.services.rag.contracts import (
    RetrievalCandidate,
    RetrievalDiagnostics,
    RetrievalQuery,
    RetrievalResult,
)


def make_candidate(chunk_id: str, text: str) -> RetrievalCandidate:
    result = DocumentResult(
        id=chunk_id,
        title="规划标准",
        content=text,
        similarity=0.9,
        metadata={
            "chunk_id": chunk_id,
            "document_name": "规划标准",
            "match_type": "keyword",
        },
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )
    return RetrievalCandidate.from_document_result(result)


class FakeRetrievalPort:
    def __init__(self, candidates: tuple[RetrievalCandidate, ...] = ()) -> None:
        self.candidates = candidates
        self.queries: list[RetrievalQuery] = []

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        self.queries.append(query)
        return RetrievalResult(
            candidates=self.candidates,
            embedding_available=False,
            diagnostics=RetrievalDiagnostics(keyword_count=len(self.candidates)),
        )

    async def fetch_chunks(self, chunk_ids):
        return [candidate for candidate in self.candidates if candidate.chunk_id in chunk_ids]


def test_default_registry_exposes_only_graph_free_agent_tools() -> None:
    registry = build_default_tool_registry()

    assert registry.names() == {
        "retrieve_kb",
        "reuse_evidence",
        "compose_answer",
        "clarify",
    }
    serialized = " ".join(
        f"{spec.name} {spec.description}" for spec in registry.specs()
    ).lower()
    assert "graph" not in serialized
    assert "图谱" not in serialized
    assert "多实体必须" not in serialized
    assert "检索两次" not in serialized


@pytest.mark.asyncio
async def test_retrieve_kb_adds_candidates_to_current_working_evidence() -> None:
    candidate = make_candidate("chunk-1", "重庆市滑坡监测要求")
    retrieval = FakeRetrievalPort((candidate,))
    ledger = EvidenceLedger(session_id="session-1")
    runtime = ToolRuntime(retrieval_port=retrieval, evidence_ledger=ledger)

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="call-1",
            name="retrieve_kb",
            arguments={
                "query": "重庆市滑坡监测要求",
                "top_k": 6,
                "search_mode": "keyword",
            },
        ),
    )

    assert observation.status == "ok"
    assert observation.tool_name == "retrieve_kb"
    assert retrieval.queries == [
        RetrievalQuery(
            query_text="重庆市滑坡监测要求",
            top_k=6,
            search_mode="keyword",
        )
    ]
    working = ledger.working_evidence(turn_id="turn-1")
    assert len(working) == 1
    assert observation.payload["evidence_ids"] == [working[0].evidence_id]


@pytest.mark.asyncio
async def test_reuse_evidence_requires_explicit_tool_execution_to_activate_history() -> None:
    ledger = EvidenceLedger(session_id="session-1")
    historical = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[make_candidate("chunk-history", "历史滑坡监测要求")],
    )[0]
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
    )

    observation = await runtime.execute(
        turn_id="turn-2",
        call=ToolCall(
            tool_call_id="call-2",
            name="reuse_evidence",
            arguments={"query": "滑坡监测", "limit": 5},
        ),
    )

    assert observation.status == "ok"
    assert observation.payload["evidence_ids"] == [historical.evidence_id]
    assert ledger.working_evidence(turn_id="turn-2")[0].evidence_id == historical.evidence_id


@pytest.mark.asyncio
async def test_compose_answer_freezes_only_selected_current_evidence() -> None:
    ledger = EvidenceLedger(session_id="session-1")
    current = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[make_candidate("chunk-1", "当前证据")],
    )[0]
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="call-3",
            name="compose_answer",
            arguments={"evidence_ids": [current.evidence_id]},
        ),
    )

    snapshot = observation.payload["snapshot"]
    assert observation.status == "ok"
    assert snapshot.evidence_ids == (current.evidence_id,)


@pytest.mark.asyncio
async def test_clarify_returns_structured_terminal_observation() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-1"),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="call-4",
            name="clarify",
            arguments={"question": "你指的是哪个行政区？"},
        ),
    )

    assert observation.status == "ok"
    assert observation.is_terminal is True
    assert observation.payload == {"question": "你指的是哪个行政区？"}


def test_resource_fuse_counts_all_steps_without_retrieval_specific_budget() -> None:
    fuse = ResourceFuse(max_steps=2, max_elapsed_seconds=30)

    fuse.consume_step(tool_name="retrieve_kb")
    fuse.consume_step(tool_name="clarify")
    with pytest.raises(ResourceFuseExceeded, match="RESOURCE_FUSE"):
        fuse.consume_step(tool_name="reuse_evidence")

    assert not hasattr(fuse, "retrieve_attempts")
    assert not hasattr(fuse, "max_retrievals")
