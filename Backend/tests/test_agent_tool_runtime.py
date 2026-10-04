from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.models.search_models import MetadataFilter, SpatialFilter
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.controller_protocol import ControllerDecision
from app.services.agent.orchestration.tool_execution import ToolExecutionCoordinator
from app.services.agent.tool_runtime import (
    RetrievalRequestConstraints,
    RetrievalUnavailableError,
    ResourceFuse,
    ResourceFuseExceeded,
    ToolCall,
    ToolExecutionError,
    ToolExecutionContext,
    ToolRuntime,
    build_default_tool_registry,
)
from app.services.agent.tools import LocateMapInput, QuerySpatialRelationInput, ToolRegistry, ToolSpec
from app.services.rag.contracts import (
    RetrievalCandidate,
    RetrievalChannelDiagnostic,
    RetrievalDiagnostics,
    RetrievalQuery,
    RetrievalResult,
    StandardScopeConstraint,
)
from app.services.spatial_service import RegionAmbiguityError, RegionNotFoundError


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
    async def resolve_region(self, *, adcode=None, region_name=None):
        if adcode == "510000" or region_name == "四川":
            return {"adcode": "510000", "region_name": "四川省"}
        raise ValueError("unknown region")

    async def query_relation(self, *, left, right, relation):
        return {"operation": "relation", "relation": relation, "result": True, "left": left, "right": right}

    async def overlay(self, *, left, right, operation):
        return {"operation": operation, "geometry": {"type": "Polygon", "coordinates": [[[104.0, 30.0], [104.1, 30.0], [104.1, 30.1], [104.0, 30.0]]]}}

    async def create_buffer(self, center, distance):
        return {"type": "Polygon", "coordinates": [[[104.0, 30.0], [104.1, 30.0], [104.1, 30.1], [104.0, 30.0]]]}


class SlowSpatialService(FakeSpatialService):
    async def query_relation(self, *, left, right, relation):
        await asyncio.sleep(0.05)
        return await super().query_relation(left=left, right=right, relation=relation)


class AmbiguousRegionSpatialService(FakeSpatialService):
    async def resolve_region(self, *, adcode=None, region_name=None):
        raise RegionAmbiguityError(
            str(region_name or "成都"),
            [
                {"adcode": "510100", "region_name": "成都市"},
                {"adcode": "510199", "region_name": "成都测试区"},
            ],
        )


class MissingRegionSpatialService(FakeSpatialService):
    async def resolve_region(self, *, adcode=None, region_name=None):
        raise RegionNotFoundError("Administrative region does not exist")


class FakeStandardApplicabilityService:
    def __init__(self) -> None:
        self.calls = []

    async def list_applicable_standards(self, *, scope, query=None, limit=50, cursor=None):
        self.calls.append({"scope": scope, "query": query, "limit": limit, "cursor": cursor})
        return {
            "region": {"adcode": scope.adcode, "name": scope.region_name},
            "items": [
                {
                    "standard_key": "gb500162014",
                    "standard_code": "GB 50016-2014",
                    "title": "建筑设计防火规范",
                    "scope_type": "nationwide",
                    "basis_type": "jurisdiction_default",
                    "verification_status": "derived",
                }
            ],
            "eligible_count": 1,
            "unresolved_count": 2,
            "next_cursor": None,
            "coverage_complete": False,
        }


def spatial_registry(
    *,
    timeout: float = 30.0,
    permission: str | None = None,
    confirmation_required: bool = False,
) -> ToolRegistry:
    return ToolRegistry(
        (
            ToolSpec(
                name="query_spatial_relation",
                description="test spatial relation",
                input_model=QuerySpatialRelationInput,
                timeout=timeout,
                permission=permission,
                confirmation_required=confirmation_required,
                provider="postgis",
            ),
        )
    )


def browser_registry(*, timeout: float) -> ToolRegistry:
    return ToolRegistry(
        (
            ToolSpec(
                name="locate_map",
                description="test browser locate",
                input_model=LocateMapInput,
                timeout=timeout,
                provider="browser",
                side_effect=True,
            ),
        )
    )


def test_default_registry_exposes_graph_free_rag_browser_and_spatial_tools() -> None:
    registry = build_default_tool_registry()

    assert registry.names() == {
        "retrieve_kb",
        "list_applicable_standards",
        "reuse_evidence",
        "search_evidence_memory",
        "import_vector_dataset",
        "set_layer_visibility",
        "set_vector_style",
        "fit_vector_layer",
        "locate_map",
        "select_region",
        "inspect_layer_features",
        "get_feature_geometry",
        "query_spatial_relation",
        "spatial_overlay",
        "create_buffer",
        "render_geojson_layer",
        "query_geospatial_data",
    }
    assert "compose_answer" not in registry.names()
    assert "clarify" not in registry.names()
    assert "limitation" not in registry.names()
    assert "direct_answer" not in registry.names()
    serialized = " ".join(
        f"{spec.name} {spec.description}" for spec in registry.specs()
    ).lower()
    assert "graph" not in serialized
    assert "图谱" not in serialized
    assert "多实体必须" not in serialized
    assert "检索两次" not in serialized


@pytest.mark.asyncio
async def test_list_applicable_standards_uses_runtime_scope_and_admits_catalogue_evidence() -> None:
    ledger = EvidenceLedger(session_id="session-standard-list")
    service = FakeStandardApplicabilityService()
    scope = StandardScopeConstraint(adcode="510000", region_name="四川省")
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
        standard_scope=scope,
        standard_applicability_service=service,
    )

    observation = await runtime.execute(
        turn_id="turn-list",
        call=ToolCall(
            tool_call_id="list-sichuan",
            name="list_applicable_standards",
            arguments={"query": "防火", "limit": 20},
        ),
    )

    assert service.calls == [{"scope": scope, "query": "防火", "limit": 20, "cursor": None}]
    assert observation.status == "ok"
    assert observation.payload["eligible_count"] == 1
    assert observation.payload["coverage_complete"] is False
    assert ledger.get(observation.payload["evidence_id"]).source == "standard_catalogue"


@pytest.mark.asyncio
async def test_list_applicable_standards_requires_active_region_scope() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-no-region"),
        standard_applicability_service=FakeStandardApplicabilityService(),
    )

    observation = await runtime.execute(
        turn_id="turn-list",
        call=ToolCall(
            tool_call_id="list-no-region",
            name="list_applicable_standards",
            arguments={},
        ),
    )

    assert observation.status == "failed"
    assert observation.payload["error"] == "active_region is required"


@pytest.mark.asyncio
async def test_select_region_resolves_canonical_region_before_browser_execution() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-select-region"),
        spatial_service=FakeSpatialService(),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="select-sichuan",
            name="select_region",
            arguments={"region_name": "四川"},
        ),
    )

    assert observation.status == "browser_execution_required"
    assert observation.payload["map_action"] == {
        "type": "select_region",
        "target": "browser_map",
        "payload": {"adcode": "510000", "name": "四川省"},
        "timeout_seconds": pytest.approx(30.0),
    }


@pytest.mark.asyncio
async def test_select_region_accepts_consistent_name_and_adcode_but_keeps_resolver_authoritative() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-select-region-both"),
        spatial_service=FakeSpatialService(),
    )

    observation = await runtime.execute(
        turn_id="turn-both",
        call=ToolCall(
            tool_call_id="select-sichuan-both",
            name="select_region",
            arguments={"region_name": "四川", "adcode": "510000"},
        ),
    )

    assert observation.status == "browser_execution_required"
    assert observation.payload["map_action"]["payload"] == {
        "adcode": "510000",
        "name": "四川省",
    }


@pytest.mark.asyncio
async def test_select_region_rejects_conflicting_name_and_adcode_after_canonical_resolution() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-select-region-conflict"),
        spatial_service=FakeSpatialService(),
    )

    observation = await runtime.execute(
        turn_id="turn-conflict",
        call=ToolCall(
            tool_call_id="select-conflicting-region",
            name="select_region",
            arguments={"region_name": "四川", "adcode": "500000"},
        ),
    )

    assert observation.status == "failed"
    assert observation.payload["error_code"] == "REGION_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_tool_execution_coordinator_adapts_controller_decision_to_tool_call() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-controller-decision"),
        spatial_service=FakeSpatialService(),
    )
    coordinator = ToolExecutionCoordinator(runtime)

    outcome = await coordinator.execute(
        turn_id="turn-1",
        session_id="session-controller-decision",
        trace_id="trace-controller-decision",
        call=ControllerDecision(
            action="tool_call",
            tool="select_region",
            arguments={"region_name": "四川"},
            tool_call_id="select-controller-decision",
        ),
    )

    assert isinstance(outcome.call, ToolCall)
    assert outcome.call.name == "select_region"
    assert outcome.observation is not None
    assert outcome.observation.status == "browser_execution_required"


@pytest.mark.asyncio
async def test_select_region_ambiguity_reuses_runtime_identity_resolution_contract() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-ambiguous-region"),
        spatial_service=AmbiguousRegionSpatialService(),
    )
    coordinator = ToolExecutionCoordinator(runtime)

    outcome = await coordinator.execute(
        turn_id="turn-ambiguous",
        session_id="session-ambiguous-region",
        trace_id="trace-ambiguous",
        call=ToolCall(
            tool_call_id="select-ambiguous",
            name="select_region",
            arguments={"region_name": "成都"},
        ),
    )

    assert outcome.observation is not None
    assert outcome.observation.status == "failed"
    assert outcome.observation.payload["error_code"] == "REGION_AMBIGUOUS"
    assert outcome.identity_resolution is not None
    assert outcome.identity_resolution.requires_confirmation is True
    assert [item.entity_ref for item in outcome.identity_resolution.candidate_refs] == [
        "region:510100",
        "region:510199",
    ]


@pytest.mark.asyncio
async def test_select_region_not_found_is_observed_failure_not_runtime_crash() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-missing-region"),
        spatial_service=MissingRegionSpatialService(),
    )
    coordinator = ToolExecutionCoordinator(runtime)

    outcome = await coordinator.execute(
        turn_id="turn-missing",
        session_id="session-missing-region",
        trace_id="trace-missing",
        call=ToolCall(
            tool_call_id="select-missing",
            name="select_region",
            arguments={"region_name": "不存在行政区"},
        ),
    )

    assert outcome.observation is not None
    assert outcome.observation.status == "failed"
    assert outcome.observation.payload["error_code"] == "REGION_NOT_FOUND"
    assert outcome.identity_resolution is None


@pytest.mark.asyncio
async def test_browser_action_carries_effective_tool_timeout_to_browser_runtime() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-browser-timeout"),
        registry=browser_registry(timeout=1.25),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="locate-timeout",
            name="locate_map",
            arguments={"longitude": 104.0, "latitude": 30.0, "zoom": 8},
        ),
    )

    assert observation.status == "browser_execution_required"
    assert observation.payload["map_action"]["timeout_seconds"] == pytest.approx(1.25)


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
async def test_tool_permission_is_enforced_before_execution() -> None:
    ledger = EvidenceLedger(session_id="session-policy")
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
        spatial_service=FakeSpatialService(),
        registry=spatial_registry(permission="spatial.execute"),
    )

    with pytest.raises(ToolExecutionError, match="TOOL_PERMISSION_DENIED"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="spatial-policy-1",
                name="query_spatial_relation",
                arguments={
                    "left": {"geometry": {"type": "Point", "coordinates": [104, 30]}},
                    "right": {"region": {"adcode": "510000"}},
                    "relation": "intersects",
                },
            ),
        )

    assert ledger.all_items() == ()


@pytest.mark.asyncio
async def test_tool_permission_allows_authorized_execution() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-policy-allowed"),
        spatial_service=FakeSpatialService(),
        registry=spatial_registry(permission="spatial.execute"),
        execution_context=ToolExecutionContext(
            permissions=frozenset({"spatial.execute"})
        ),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="spatial-policy-allowed",
            name="query_spatial_relation",
            arguments={
                "left": {"geometry": {"type": "Point", "coordinates": [104, 30]}},
                "right": {"region": {"adcode": "510000"}},
                "relation": "intersects",
            },
        ),
    )

    assert observation.status == "ok"


@pytest.mark.asyncio
async def test_confirmation_required_tool_is_denied_without_confirmation() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-confirm"),
        spatial_service=FakeSpatialService(),
        registry=spatial_registry(confirmation_required=True),
    )

    with pytest.raises(ToolExecutionError, match="TOOL_CONFIRMATION_REQUIRED"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="needs-confirmation",
                name="query_spatial_relation",
                arguments={
                    "left": {"geometry": {"type": "Point", "coordinates": [104, 30]}},
                    "right": {"region": {"adcode": "510000"}},
                    "relation": "intersects",
                },
            ),
        )


@pytest.mark.asyncio
async def test_confirmation_required_tool_accepts_exact_call_confirmation() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-confirm-allowed"),
        spatial_service=FakeSpatialService(),
        registry=spatial_registry(confirmation_required=True),
        execution_context=ToolExecutionContext(
            confirmed_tool_call_ids=frozenset({"confirmed-call"})
        ),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="confirmed-call",
            name="query_spatial_relation",
            arguments={
                "left": {"geometry": {"type": "Point", "coordinates": [104, 30]}},
                "right": {"region": {"adcode": "510000"}},
                "relation": "intersects",
            },
        ),
    )

    assert observation.status == "ok"


@pytest.mark.asyncio
async def test_tool_timeout_is_enforced_by_runtime_boundary() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-timeout"),
        spatial_service=SlowSpatialService(),
        registry=spatial_registry(timeout=0.01),
    )

    with pytest.raises(ToolExecutionError, match="TOOL_TIMEOUT"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="slow-call",
                name="query_spatial_relation",
                arguments={
                    "left": {"geometry": {"type": "Point", "coordinates": [104, 30]}},
                    "right": {"region": {"adcode": "510000"}},
                    "relation": "intersects",
                },
            ),
        )


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
async def test_retrieve_kb_adds_runtime_standard_scope_without_persisting_it() -> None:
    port = FakeRetrievalPort()
    runtime = ToolRuntime(
        retrieval_port=port,
        evidence_ledger=EvidenceLedger(session_id="session-standard-scope"),
        standard_scope=StandardScopeConstraint(
            adcode="510000",
            region_name="四川省",
        ),
    )

    await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="retrieve-sichuan",
            name="retrieve_kb",
            arguments={"query": "地质灾害监测"},
        ),
    )

    assert port.queries[0].standard_scope == StandardScopeConstraint(
        adcode="510000",
        region_name="四川省",
    )


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
async def test_compose_answer_is_rejected_by_tool_runtime_and_freezes_via_ledger() -> None:
    ledger = EvidenceLedger(session_id="session-1")
    current = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[make_candidate("chunk-1", "当前证据")],
    )[0]
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
    )

    with pytest.raises(ToolExecutionError, match="'compose_answer' is a control action"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="call-3",
                name="compose_answer",
                arguments={"selected_evidence_ids": [current.evidence_id]},
            ),
        )

    snapshot = ledger.freeze(turn_id="turn-1", evidence_ids=[current.evidence_id])
    assert snapshot.evidence_ids == (current.evidence_id,)


@pytest.mark.asyncio
async def test_clarify_is_rejected_by_tool_runtime() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-1"),
    )

    with pytest.raises(ToolExecutionError, match="'clarify' is a control action"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="call-4",
                name="clarify",
                arguments={"question": "你指的是哪个行政区？"},
            ),
        )


@pytest.mark.asyncio
async def test_limitation_is_rejected_by_tool_runtime() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-1"),
    )

    with pytest.raises(ToolExecutionError, match="'limitation' is a control action"):
        await runtime.execute(
            turn_id="turn-1",
            call=ToolCall(
                tool_call_id="call-limit",
                name="limitation",
                arguments={"message": "当前知识库没有足够证据支持结论。"},
            ),
        )


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


@pytest.mark.asyncio
async def test_create_buffer_is_exposed_as_postgis_tool_and_admits_result_as_evidence() -> None:
    ledger = EvidenceLedger(session_id="session-buffer")
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
        spatial_service=FakeSpatialService(),
    )

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="buffer-1",
            name="create_buffer",
            arguments={"center": [104.0, 30.0], "distance_m": 500.0},
        ),
    )

    assert observation.status == "ok"
    assert observation.payload["result"]["geometry"]["type"] == "Polygon"
    evidence_id = observation.payload["evidence_id"]
    assert ledger.get(evidence_id) is not None
    assert ledger.get(evidence_id).source == "postgis"


@pytest.mark.asyncio
async def test_render_geojson_layer_is_a_browser_handoff_not_a_server_side_map_mutation() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-render"),
    )
    geojson = {"type": "Point", "coordinates": [104.0, 30.0]}

    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="render-1",
            name="render_geojson_layer",
            arguments={"geojson": geojson, "name": "缓冲区结果"},
        ),
    )

    assert observation.status == "browser_execution_required"
    assert observation.payload["map_action"]["type"] == "render_geojson_layer"
    assert observation.payload["map_action"]["payload"]["geojson"] == geojson


@pytest.mark.asyncio
@pytest.mark.parametrize("source_tool", ["create_buffer", "spatial_overlay"])
async def test_spatial_geometry_result_can_flow_into_single_render_geojson_layer_tool(source_tool: str) -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id=f"session-{source_tool}-render"),
        spatial_service=FakeSpatialService(),
    )
    if source_tool == "create_buffer":
        source_arguments = {"center": [104.0, 30.0], "distance_m": 500.0}
    else:
        source_arguments = {
            "left": {"geometry": {"type": "Point", "coordinates": [104.0, 30.0]}},
            "right": {"region": {"adcode": "510000"}},
            "operation": "intersection",
        }
    source = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(tool_call_id=f"{source_tool}-1", name=source_tool, arguments=source_arguments),
    )
    geometry = source.payload["result"]["geometry"]
    render = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id=f"render-{source_tool}-1",
            name="render_geojson_layer",
            arguments={"geojson": geometry, "name": f"{source_tool} result"},
        ),
    )
    assert render.status == "browser_execution_required"
    assert render.payload["map_action"]["payload"]["geojson"] == geometry


class FakeGeoSQLExecutor:
    async def execute(self, _compiled):
        return [
            {"adcode": "510100", "region_name": "Chengdu", "geometry": {"type": "Point", "coordinates": [104.0, 30.0]}},
            {"adcode": "510000", "region_name": "Sichuan", "geometry": {"type": "Point", "coordinates": [104.1, 30.1]}},
        ]


@pytest.mark.asyncio
async def test_query_geospatial_data_executes_controlled_plan_and_admits_evidence() -> None:
    ledger = EvidenceLedger(session_id="session-geosql")
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=ledger,
        geosql_executor=FakeGeoSQLExecutor(),
    )
    observation = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="geosql-1",
            name="query_geospatial_data",
            arguments={
                "operation": "select",
                "target_table": "spatial_regions",
                "select_fields": ["adcode", "region_name", "geometry"],
                "filters": [],
                "limit": 2,
            },
        ),
    )
    assert observation.status == "ok"
    result = observation.payload["result"]
    assert result["row_count"] == 2
    assert result["rows"] == [
        {"adcode": "510100", "region_name": "Chengdu"},
        {"adcode": "510000", "region_name": "Sichuan"},
    ]
    assert result["geojson"]["type"] == "GeometryCollection"
    assert len(result["geojson"]["geometries"]) == 2
    evidence = ledger.get(observation.payload["evidence_id"])
    assert evidence is not None
    assert evidence.source == "postgis"


@pytest.mark.asyncio
async def test_geosql_geometry_requires_explicit_render_tool_for_map_side_effect() -> None:
    runtime = ToolRuntime(
        retrieval_port=FakeRetrievalPort(),
        evidence_ledger=EvidenceLedger(session_id="session-geosql-render"),
        geosql_executor=FakeGeoSQLExecutor(),
    )
    query = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="geosql-1",
            name="query_geospatial_data",
            arguments={
                "operation": "select",
                "target_table": "spatial_regions",
                "select_fields": ["geometry"],
                "limit": 2,
            },
        ),
    )
    assert query.is_terminal is False
    render = await runtime.execute(
        turn_id="turn-1",
        call=ToolCall(
            tool_call_id="render-geosql-1",
            name="render_geojson_layer",
            arguments={"geojson": query.payload["result"]["geojson"], "name": "GeoSQL result"},
        ),
    )
    assert render.status == "browser_execution_required"
