from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.models.search_models import MetadataFilter, SpatialFilter
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.tool_runtime import (
    RetrievalRequestConstraints,
    RetrievalUnavailableError,
    ResourceFuse,
    ResourceFuseExceeded,
    ToolCall,
    ToolExecutionError,
    ToolRuntime,
    build_default_tool_registry,
)
from app.services.rag.contracts import (
    RetrievalCandidate,
    RetrievalChannelDiagnostic,
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


class FakeSpatialService:
    async def query_relation(self, *, left, right, relation):
        return {"operation": "relation", "relation": relation, "result": True, "left": left, "right": right}

    async def overlay(self, *, left, right, operation):
        return {"operation": operation, "geometry": {"type": "Polygon", "coordinates": []}}


def test_default_registry_exposes_graph_free_rag_browser_and_spatial_tools() -> None:
    registry = build_default_tool_registry()

    assert registry.names() == {
        "retrieve_kb",
        "reuse_evidence",
        "compose_answer",
        "clarify",
        "limitation",
        "import_vector_dataset",
        "set_layer_visibility",
        "set_vector_style",
        "fit_vector_layer",
        "locate_map",
        "inspect_layer_features",
        "get_feature_geometry",
        "query_spatial_relation",
        "spatial_overlay",
    }
    serialized = " ".join(
        f"{spec.name} {spec.description}" for spec in registry.specs()
    ).lower()
    assert "graph" not in serialized
    assert "图谱" not in serialized
    assert "多实体必须" not in serialized
    assert "检索两次" not in serialized


@pytest.mark.asyncio
async def test_spatial_relation_result_is_admitted_as_evidence() -> None:
    ledger = EvidenceLedger(session_id="session-spatial")
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
        spatial_service=FakeSpatialService(),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="spatial-1",
            name="query_spatial_relation",
            arguments={
                "left": {"geometry": {"type": "Point", "coordinates": [104, 30]}},
                "right": {"region": {"adcode": "510000"}},
                "relation": "intersects",
            },
        ),
    )

    assert observation.status == "ok"
    evidence_id = observation.payload["evidence_id"]
    assert ledger.get(evidence_id) is not None
    assert ledger.get(evidence_id).source == "postgis"


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
            arguments={"query": "重庆市滑坡监测要求"},
        ),
    )

    assert observation.status == "ok"
    assert observation.tool_name == "retrieve_kb"
    assert retrieval.queries == [
        RetrievalQuery(
            query_text="重庆市滑坡监测要求",
        )
    ]
    working = ledger.working_evidence(turn_id="turn-1")
    assert len(working) == 1
    assert observation.payload["evidence_ids"] == [working[0].evidence_id]


@pytest.mark.asyncio
async def test_retrieve_kb_preserves_request_level_retrieval_constraints() -> None:
    retrieval = FakeRetrievalPort((make_candidate("chunk-1", "证据"),))
    ledger = EvidenceLedger(session_id="session-1")
    constraints = RetrievalRequestConstraints(
        top_k=3,
        threshold=0.82,
        search_mode="semantic",
        use_rerank=False,
        metadata_filter=MetadataFilter(region="重庆"),
        spatial_filter=SpatialFilter(
            geometry={"type": "Point", "coordinates": [106.5, 29.5]},
            distance=5000,
        ),
    )
    runtime = ToolRuntime(
        retrieval_port=retrieval,
        evidence_ledger=ledger,
        retrieval_constraints=constraints,
    )

    await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="call-constraints",
            name="retrieve_kb",
            arguments={"query": "重庆滑坡监测"},
        ),
    )

    query = retrieval.queries[0]
    assert query.top_k == 3
    assert query.threshold == 0.82
    assert query.search_mode == "semantic"
    assert query.use_rerank is False
    assert query.metadata_filter.region == "重庆"
    assert query.spatial_filter.distance == 5000


@pytest.mark.asyncio
async def test_retrieve_kb_surfaces_total_retrieval_unavailability() -> None:
    class UnavailableRetrievalPort(FakeRetrievalPort):
        async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            self.queries.append(query)
            return RetrievalResult(
                candidates=(),
                embedding_available=False,
                diagnostics=RetrievalDiagnostics(
                    channels=(
                        RetrievalChannelDiagnostic(
                            channel="keyword",
                            state="unavailable",
                            detail="postgres unavailable",
                        ),
                    ),
                ),
            )

    runtime = ToolRuntime(
        retrieval_port=UnavailableRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-1"),
    )

    with pytest.raises(RetrievalUnavailableError, match="RETRIEVAL_UNAVAILABLE"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="call-unavailable",
                name="retrieve_kb",
                arguments={"query": "规划标准"},
            ),
        )


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


@pytest.mark.asyncio
async def test_limitation_is_a_structured_terminal_outcome() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-1"),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="call-limit",
            name="limitation",
            arguments={"message": "当前知识库没有足够证据支持结论。"},
        ),
    )

    assert observation.is_terminal is True
    assert observation.payload == {"message": "当前知识库没有足够证据支持结论。"}


@pytest.mark.asyncio
async def test_tool_arguments_are_validated_from_registry_schema() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-1"),
    )

    with pytest.raises(ToolExecutionError, match="invalid arguments"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="bad-call",
                name="retrieve_kb",
                arguments={"query": ""},
            ),
        )


def test_resource_fuse_counts_all_steps_without_retrieval_specific_budget() -> None:
    fuse = ResourceFuse(max_steps=2, max_elapsed_seconds=30)

    fuse.consume_step(tool_name="retrieve_kb")
    fuse.consume_step(tool_name="clarify")
    with pytest.raises(ResourceFuseExceeded, match="RESOURCE_FUSE"):
        fuse.consume_step(tool_name="reuse_evidence")

    assert not hasattr(fuse, "retrieve_attempts")
    assert not hasattr(fuse, "max_retrievals")
