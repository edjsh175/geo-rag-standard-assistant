from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.models.search_models import MetadataFilter, SpatialFilter
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.store import PostgresAgentStore
from app.services.agent.tool_runtime import RetrievalRequestConstraints, ToolObservation
from app.services.rag.contracts import RetrievalChannelDiagnostic, RetrievalDiagnostics


class FakeMappings:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return FakeMappings(self.row)


class FakePostgresSession:
    def __init__(self):
        self.saved = None
        self.clear_requests = []

    async def execute(self, sql, params):
        if "UPDATE geoai_pending_browser_executions" in str(sql):
            self.clear_requests.append(dict(params))
            return FakeResult()
        if "INSERT INTO geoai_pending_browser_executions" in str(sql):
            self.saved = dict(params)
            return FakeResult()
        if (
            self.saved is None
            or params["principal_id"] != self.saved["principal_id"]
            or params["session_id"] != self.saved["session_id"]
        ):
            return FakeResult()
        return FakeResult(
            {
                "token": self.saved["token"],
                "session_id": self.saved["session_id"],
                "question": self.saved["question"],
                "turn_id": self.saved["turn_id"],
                "trace_id": self.saved["trace_id"],
                "tool_call_id": self.saved["tool_call_id"],
                "tool_name": self.saved["tool_name"],
                "observations": self.saved["observations"],
                "request_context": self.saved["request_context"],
                "reviewer_enabled": self.saved["reviewer_enabled"],
                "thinking": self.saved["thinking"],
                "max_steps": self.saved["max_steps"],
                "steps_used": self.saved["steps_used"],
                "max_elapsed_seconds": self.saved["max_elapsed_seconds"],
                "retrieval_constraints": self.saved["retrieval_constraints"],
                "main_model_name": self.saved["main_model_name"],
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            }
        )


class FakePostgresManager:
    def __init__(self):
        self.postgres_sessionmaker = object()
        self.session = FakePostgresSession()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.session


@pytest.mark.asyncio
async def test_pending_execution_roundtrip_preserves_typed_observations_and_constraints():
    manager = FakePostgresManager()
    store = PostgresAgentStore(manager=manager)
    diagnostics = RetrievalDiagnostics(
        keyword_count=3,
        channels=(RetrievalChannelDiagnostic("keyword", "succeeded"),),
    )
    pending = PendingBrowserExecution(
        token="continue-1",
        question="导入并查询图层",
        turn_id="turn-1",
        trace_id="trace-1",
        tool_call_id="browser-call-1",
        tool_name="import_vector_dataset",
        observations=(
            ToolObservation(
                tool_call_id="prior-call",
                tool_name="retrieve_kb",
                status="ok",
                payload={"diagnostics": diagnostics, "evidence_ids": ["e1"]},
            ),
            ToolObservation(
                tool_call_id="browser-call-1",
                tool_name="import_vector_dataset",
                status="browser_execution_required",
                payload={"map_action": {"type": "import_vector_dataset"}},
                is_terminal=True,
            ),
        ),
        request_context={"map_context": {"ready": True}},
        reviewer_enabled=False,
        thinking=True,
        max_steps=8,
        steps_used=2,
        max_elapsed_seconds=90.0,
        retrieval_constraints=RetrievalRequestConstraints(
            top_k=4,
            threshold=0.84,
            search_mode="semantic",
            use_rerank=False,
            metadata_filter=MetadataFilter(region="杭州", keywords=["控规"]),
            spatial_filter=SpatialFilter(
                geometry={"type": "Point", "coordinates": [120.1, 30.2]},
                distance=2500,
                spatial_relation="near",
            ),
        ),
        main_model_name="model-main",
        session_id="session-1",
    )

    await store.save_pending_execution("principal-1", pending)

    saved_observations = json.loads(manager.session.saved["observations"])
    saved_constraints = json.loads(manager.session.saved["retrieval_constraints"])
    assert isinstance(saved_observations[0], dict)
    assert saved_observations[0]["tool_name"] == "retrieve_kb"
    assert isinstance(saved_constraints, dict)
    assert manager.session.saved["session_id"] == "session-1"

    recovered = await store.get_pending_execution("principal-1", "session-1")

    assert recovered is not None
    assert recovered.session_id == "session-1"
    assert all(isinstance(item, ToolObservation) for item in recovered.observations)
    assert recovered.observations[0].payload["diagnostics"] == {
        "exact_count": 0,
        "keyword_count": 3,
        "vector_count": 0,
        "channels": [{"channel": "keyword", "state": "succeeded", "detail": None}],
    }
    assert isinstance(recovered.retrieval_constraints, RetrievalRequestConstraints)
    assert isinstance(recovered.retrieval_constraints.metadata_filter, MetadataFilter)
    assert isinstance(recovered.retrieval_constraints.spatial_filter, SpatialFilter)
    assert recovered.retrieval_constraints.metadata_filter.region == "杭州"
    assert recovered.retrieval_constraints.spatial_filter.geometry["coordinates"] == [120.1, 30.2]

    assert await store.get_pending_execution("principal-1", "another-session") is None
    await store.clear_pending_execution("principal-1", "another-session")
    assert manager.session.clear_requests == [
        {"principal_id": "principal-1", "session_id": "another-session"}
    ]


@pytest.mark.asyncio
async def test_pending_execution_rejects_legacy_string_observations_without_evaluating_them():
    manager = FakePostgresManager()
    store = PostgresAgentStore(manager=manager)
    pending = PendingBrowserExecution(
        token="legacy-1",
        question="继续",
        turn_id="turn-1",
        trace_id="trace-1",
        tool_call_id="browser-call-1",
        tool_name="import_vector_dataset",
        observations=(
            ToolObservation(
                tool_call_id="browser-call-1",
                tool_name="import_vector_dataset",
                status="browser_execution_required",
                payload={},
            ),
        ),
        request_context={},
        reviewer_enabled=False,
        thinking=False,
        max_steps=5,
        steps_used=1,
        max_elapsed_seconds=60,
        retrieval_constraints=None,
        main_model_name=None,
        session_id="session-legacy",
    )
    await store.save_pending_execution("principal-1", pending)
    manager.session.saved["observations"] = json.dumps(["ToolObservation(...)"], ensure_ascii=False)

    assert await store.get_pending_execution("principal-1", "session-legacy") is None
