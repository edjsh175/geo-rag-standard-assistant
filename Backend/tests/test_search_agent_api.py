from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.models.search_models import (
    AgentCancelRequest,
    DocumentResult,
    FollowUpContext,
    SearchRequest,
)
from app.api.search_routes import cancel_agent_run
from app.services.agent.publication import PublishedResult
from app.services.agent.context import ContextEngine
from app.services.search_application_service import SearchApplicationService


def make_result(doc_id: str = "chunk-1") -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title="规划标准",
        content="标准内容",
        similarity=0.9,
        metadata={"chunk_id": doc_id, "document_name": "规划标准"},
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


class SearchServiceStub:
    def __init__(self) -> None:
        self.search_calls = 0

    async def search(self, **kwargs):
        self.search_calls += 1
        return [make_result()]


class RelaxedSearchServiceStub(SearchServiceStub):
    def __init__(self) -> None:
        super().__init__()
        self.thresholds: list[float] = []

    async def search(self, **kwargs):
        self.search_calls += 1
        self.thresholds.append(float(kwargs["threshold"]))
        if len(self.thresholds) == 1:
            return []
        return [make_result()]


class AssetServiceStub:
    async def enrich_search_results(self, results):
        return results

    async def get_document_detail_payload(self, doc_id):
        if doc_id == "14741":
            return {"id": "14741", "metadata": {"title": "服务端权威标题"}}
        return None


class ContractServiceStub:
    async def filter_deleted_results(self, results):
        return results

    async def apply_document_overrides(self, doc_id, detail):
        return detail


class RetrievalPortStub:
    def __init__(self) -> None:
        self.fetch_calls = []

    async def fetch_chunks(self, chunk_ids):
        self.fetch_calls.append(tuple(chunk_ids))
        return [SimpleNamespace(source_result=make_result(chunk_ids[0]))] if chunk_ids else []


class AgentRuntimeStub:
    def __init__(self) -> None:
        self.requests = []
        self.cancellation_requests = []
        self.linear_publication_calls = []
        self.context_engine = ContextEngine()
        self.reviewer = None
        self.answer_generator = SimpleNamespace(generate=self._generate)
        self.answer_publication_pipeline = SimpleNamespace(run=self._run_linear_publication)

    async def _generate(self, **kwargs):
        return SimpleNamespace(answer="linear answer", map_action=None)

    async def _run_linear_publication(self, **kwargs):
        self.linear_publication_calls.append(kwargs)
        answer = await self._generate(**kwargs)
        if kwargs.get("reviewer_enabled"):
            if self.reviewer is None:
                return SimpleNamespace(answer=answer, review=None, terminal_state="review_failed", message="review failed")
            review = await self.reviewer.review(question=kwargs["question"], answer=answer, snapshot=kwargs["snapshot"])
            verdict = str(getattr(review, "verdict", "")).strip().upper()
            if verdict not in {"SUPPORTED", "PASS", "PASSED"}:
                return SimpleNamespace(answer=answer, review=review, terminal_state="review_rejected", message="答案未通过证据审查，未发布。")
        return SimpleNamespace(answer=answer, review=None, terminal_state=None, message=None)

    async def run(self, request):
        self.requests.append(request)
        item = SimpleNamespace(chunk_id="chunk-1")
        snapshot = SimpleNamespace(items=(item,))
        answer = SimpleNamespace(answer="agent answer")
        return SimpleNamespace(
            session_id=request.session_id,
            trace_id="trace-1",
            publication_state="published",
            answer=answer,
            clarification=None,
            frozen_evidence=snapshot,
            published_result=PublishedResult.publish(
                text="agent answer",
                publication_state="published",
                map_action=None,
            ),
        )

    async def request_cancellation(self, **kwargs):
        self.cancellation_requests.append(kwargs)
        return SimpleNamespace(event_id="cancel-event-1")


class FailingStreamingRuntime(AgentRuntimeStub):
    async def stream(self, request):
        self.requests.append(request)
        if False:  # pragma: no cover - keeps this an async generator
            yield None
        raise ValueError("synthetic retrieval failure")


@pytest.mark.asyncio
async def test_generation_false_uses_deterministic_search_without_agent() -> None:
    search = SearchServiceStub()
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=search,
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    response = await service.execute(
        SearchRequest(query="规划标准", use_generation=False),
        generation_allowed=False,
        principal_id="admin:test",
    )

    assert search.search_calls == 1
    assert runtime.requests == []
    assert response.generated_answer is None
    assert response.results[0].id == "chunk-1"


@pytest.mark.asyncio
async def test_deterministic_search_preserves_single_relaxed_threshold_retry() -> None:
    search = RelaxedSearchServiceStub()
    service = SearchApplicationService(
        search_service=search,
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=AgentRuntimeStub(),
        retrieval_port=RetrievalPortStub(),
    )

    response = await service.execute(
        SearchRequest(
            query="规划标准",
            use_generation=False,
            threshold=0.7,
        ),
        generation_allowed=False,
        principal_id="admin:test",
    )

    assert search.thresholds == [0.7, 0.35]
    assert response.results[0].id == "chunk-1"


@pytest.mark.asyncio
async def test_generation_true_defaults_to_agent_runtime_without_intent_router() -> None:
    search = SearchServiceStub()
    runtime = AgentRuntimeStub()
    retrieval = RetrievalPortStub()
    service = SearchApplicationService(
        search_service=search,
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=retrieval,
    )

    response = await service.execute(
        SearchRequest(
            query="规划标准有什么要求？",
            use_generation=True,
            session_id="session-42",
            reviewer_enabled=True,
            thinking=True,
        ),
        generation_allowed=True,
        principal_id="admin:test",
    )

    assert search.search_calls == 0
    assert len(runtime.requests) == 1
    assert runtime.requests[0].session_id == "session-42"
    assert runtime.requests[0].reviewer_enabled is True
    assert runtime.requests[0].thinking is True
    assert runtime.requests[0].principal_id == "admin:test"
    assert retrieval.fetch_calls == [("chunk-1",)]
    assert response.generated_answer == "agent answer"
    assert response.session_id == "session-42"
    assert response.trace_id == "trace-1"
    assert response.final_mode == "agent"
    assert response.publication_state == "published"


@pytest.mark.asyncio
async def test_agent_stream_failure_returns_terminal_runtime_error_response() -> None:
    runtime = FailingStreamingRuntime()
    service = SearchApplicationService(
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    frames = [
        frame
        async for frame in service.stream(
            SearchRequest(query="测试异常终态", use_generation=True, session_id="session-fail"),
            generation_allowed=True,
            principal_id="admin:test",
        )
    ]

    assert len(frames) == 1
    response = frames[0].response
    assert response is not None
    assert response.session_id == "session-fail"
    assert response.final_mode == "agent"
    assert response.publication_state == "runtime_error"
    assert response.generated_answer == "查询处理失败，请稍后重试。"


@pytest.mark.asyncio
async def test_application_service_delegates_agent_cancellation_to_runtime() -> None:
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    event = await service.request_cancellation(
        principal_id="admin:test",
        session_id="session-42",
        turn_id="turn-3",
        reason="user_requested",
    )

    assert event.event_id == "cancel-event-1"
    assert runtime.cancellation_requests == [
        {
            "principal_id": "admin:test",
            "session_id": "session-42",
            "turn_id": "turn-3",
            "reason": "user_requested",
        }
    ]


@pytest.mark.asyncio
async def test_cancel_route_uses_authenticated_principal_and_returns_event_id() -> None:
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    response = await cancel_agent_run(
        AgentCancelRequest(session_id="session-42", turn_id="turn-3"),
        SimpleNamespace(role="admin", username="alice", visitor_id=None),
        service,
    )

    assert response.status == "cancel_requested"
    assert response.event_id == "cancel-event-1"
    assert runtime.cancellation_requests[0]["principal_id"] == "admin:alice"


@pytest.mark.asyncio
async def test_agent_request_materializes_selected_document_as_server_authoritative_fact() -> None:
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    await service.execute(
        SearchRequest(
            query="这个文档主要讲什么？",
            use_generation=True,
            follow_up_context=FollowUpContext(
                target_document_id="14741",
                candidate_documents=[],
                resolution_source="explicit_text",
            ),
        ),
        generation_allowed=True,
        principal_id="admin:test",
    )

    context = runtime.requests[0].request_context
    assert "follow_up_context" not in context
    assert context["user_ui_selections"]["document"] == {
        "document_id": "14741",
        "title": "服务端权威标题",
        "source": "server_materialized_selected_document",
    }


@pytest.mark.asyncio
async def test_agent_request_rejects_unresolvable_selected_document_context() -> None:
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    await service.execute(
        SearchRequest(
            query="这个文档主要讲什么？",
            use_generation=True,
            follow_up_context=FollowUpContext(
                target_document_id="missing",
                candidate_documents=[],
                resolution_source="selected_document",
            ),
        ),
        generation_allowed=True,
        principal_id="admin:test",
    )

    assert runtime.requests[0].request_context.get("user_ui_selections") is None
    assert runtime.requests[0].request_context["client_hints"]["document_selection"] == {
        "document_id": "missing",
        "resolution_source": "selected_document",
        "admission_status": "rejected",
    }


@pytest.mark.asyncio
async def test_explicit_linear_mode_is_compatibility_path_without_intent_detection() -> None:
    search = SearchServiceStub()
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=search,
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    response = await service.execute(
        SearchRequest(query="规划标准", use_generation=True, mode="linear"),
        generation_allowed=True,
        principal_id="admin:test",
    )

    assert search.search_calls == 1
    assert runtime.requests == []
    assert response.generated_answer == "linear answer"
    assert response.final_mode == "linear"


@pytest.mark.asyncio
async def test_linear_mode_honors_explicit_reviewer_and_blocks_rejected_answer() -> None:
    class RejectingReviewer:
        async def review(self, **kwargs):
            return SimpleNamespace(verdict="UNSUPPORTED", findings=())

    search = SearchServiceStub()
    runtime = AgentRuntimeStub()
    runtime.reviewer = RejectingReviewer()
    service = SearchApplicationService(
        search_service=search,
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    response = await service.execute(
        SearchRequest(
            query="规划标准",
            use_generation=True,
            mode="linear",
            reviewer_enabled=True,
        ),
        generation_allowed=True,
        principal_id="admin:test",
    )

    assert response.generated_answer == "答案未通过证据审查，未发布。"
    assert response.publication_state == "review_rejected"


@pytest.mark.asyncio
async def test_agent_mode_forwards_search_constraints_to_runtime() -> None:
    runtime = AgentRuntimeStub()
    service = SearchApplicationService(
        search_service=SearchServiceStub(),
        asset_service=AssetServiceStub(),
        contract_service=ContractServiceStub(),
        agent_runtime=runtime,
        retrieval_port=RetrievalPortStub(),
    )

    await service.execute(
        SearchRequest(
            query="重庆标准",
            use_generation=True,
            top_k=4,
            threshold=0.81,
            search_mode="semantic",
            use_rerank=False,
            metadata_filter={"region": "重庆"},
            spatial_filter={
                "geometry": {"type": "Point", "coordinates": [106.5, 29.5]},
                "distance": 3000,
            },
        ),
        generation_allowed=True,
        principal_id="admin:test",
    )

    constraints = runtime.requests[0].retrieval_constraints
    assert constraints.top_k == 4
    assert constraints.threshold == 0.81
    assert constraints.search_mode == "semantic"
    assert constraints.use_rerank is False
    assert constraints.metadata_filter.region == "重庆"
    assert constraints.spatial_filter.distance == 3000
