from __future__ import annotations

import asyncio

import pytest

from app.services.agent.provider_health import ProviderHealthService, ProviderHealthSnapshot
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.tool_runtime import ToolCall
from app.services.agent.tools import build_default_tool_registry
from app.services.rag.contracts import RetrievalDiagnostics, RetrievalResult


class StubHealthService(ProviderHealthService):
    def __init__(self, *, clock, ttl_seconds: float = 10.0, timeout_seconds: float = 1.0):
        super().__init__(
            ttl_seconds=ttl_seconds,
            timeout_seconds=timeout_seconds,
            clock=clock,
        )
        self.probe_calls = 0

    async def _probe_provider_health(self):
        self.probe_calls += 1
        return {"postgres": True, "kb": True, "postgis": True}


@pytest.mark.asyncio
async def test_provider_health_snapshot_is_cached_by_ttl() -> None:
    now = [100.0]
    service = StubHealthService(clock=lambda: now[0], ttl_seconds=5.0)

    first = await service.snapshot()
    second = await service.snapshot()

    assert first is second
    assert first.provider_health == {"postgres": True, "kb": True, "postgis": True}
    assert service.probe_calls == 1

    now[0] = 106.0
    refreshed = await service.snapshot()
    assert refreshed is not first
    assert service.probe_calls == 2


class SlowHealthService(ProviderHealthService):
    async def _probe_provider_health(self):
        await asyncio.sleep(0.05)
        return {"postgres": True, "kb": True, "postgis": True}


@pytest.mark.asyncio
async def test_provider_health_probe_timeout_fails_closed() -> None:
    service = SlowHealthService(ttl_seconds=0, timeout_seconds=0.001)

    snapshot = await service.snapshot()

    assert snapshot.provider_health == {
        "postgres": False,
        "kb": False,
        "postgis": False,
    }


class ConcurrentHealthService(ProviderHealthService):
    def __init__(self):
        super().__init__(ttl_seconds=5.0, timeout_seconds=1.0)
        self.probe_calls = 0

    async def _probe_provider_health(self):
        self.probe_calls += 1
        await asyncio.sleep(0.01)
        return {"postgres": True, "kb": True, "postgis": True}


@pytest.mark.asyncio
async def test_concurrent_snapshot_requests_share_one_probe() -> None:
    service = ConcurrentHealthService()

    snapshots = await asyncio.gather(
        service.snapshot(),
        service.snapshot(),
        service.snapshot(),
    )

    assert service.probe_calls == 1
    assert snapshots[0] is snapshots[1] is snapshots[2]


class FakeMappings:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return FakeMappings(self.row)


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return FakeResult(self.row)


class FakeConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, row):
        self.connection = FakeConnection(row)

    def connect(self):
        return FakeConnectionContext(self.connection)


@pytest.mark.asyncio
async def test_real_probe_derives_kb_and_postgis_from_postgres_capabilities() -> None:
    engine = FakeEngine(
        {
            "policy_chunks_ready": True,
            "postgis_ready": False,
        }
    )
    service = ProviderHealthService(postgres_engine_getter=lambda: engine)

    health = await service._probe_provider_health()

    assert health == {"postgres": True, "kb": True, "postgis": False}
    assert "to_regclass('public.policy_chunks')" in engine.connection.statements[0]
    assert "extname = 'postgis'" in engine.connection.statements[0]


class EmptyRetrievalPort:
    async def retrieve(self, query):
        return RetrievalResult(
            query=query,
            candidates=(),
            diagnostics=RetrievalDiagnostics(),
        )

    async def fetch_chunks(self, chunk_ids):
        return ()


class CountingSnapshotProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def snapshot(self) -> ProviderHealthSnapshot:
        self.calls += 1
        return ProviderHealthSnapshot(
            provider_health={"postgres": True, "kb": False, "postgis": False},
            captured_at_monotonic=1.0,
        )


class HealthAwareController:
    def __init__(self) -> None:
        self.tool_registry = build_default_tool_registry()
        self.states = []

    async def decide(self, **kwargs):
        state = kwargs["action_state"]
        self.states.append(state)
        if len(self.states) == 1:
            return ToolCall(
                tool_call_id="reuse-health-1",
                name="reuse_evidence",
                arguments={"query": "history"},
            )
        return ToolCall(
            tool_call_id="limit-health-2",
            name="limitation",
            arguments={"message": "provider unavailable"},
        )


class UnusedAnswerGenerator:
    async def generate(self, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("answer generator should not run")


@pytest.mark.asyncio
async def test_runtime_uses_one_provider_snapshot_for_all_controller_steps() -> None:
    health_provider = CountingSnapshotProvider()
    controller = HealthAwareController()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=controller,
        answer_generator=UnusedAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
        provider_health_provider=health_provider,
    )

    result = await runtime.run(
        AgentRunRequest(
            question="检查 provider health",
            session_id="health-session",
            principal_id="admin:test",
        )
    )

    assert result.publication_state == "limitation"
    assert health_provider.calls == 1
    assert len(controller.states) == 2
    for state in controller.states:
        assert state.provider_health == {
            "postgres": True,
            "kb": False,
            "postgis": False,
        }
        assert "retrieve_kb" not in state.available_capabilities
        assert "query_spatial_relation" not in state.available_capabilities
        assert "spatial_overlay" not in state.available_capabilities
        assert "reuse_evidence" in state.available_capabilities


@pytest.mark.asyncio
async def test_invalid_continuation_is_rejected_before_provider_probe() -> None:
    health_provider = CountingSnapshotProvider()
    runtime = AgentRuntime(
        retrieval_port=EmptyRetrievalPort(),
        controller=HealthAwareController(),
        answer_generator=UnusedAnswerGenerator(),
        session_store=InMemoryAgentSessionStore(),
        provider_health_provider=health_provider,
    )

    with pytest.raises(ValueError, match="invalid or expired browser continuation token"):
        await runtime.run(
            AgentRunRequest(
                question="invalid continuation",
                session_id="health-invalid-continuation",
                principal_id="admin:test",
                continuation_token="not-a-valid-token",
                browser_tool_receipt={
                    "tool_call_id": "missing",
                    "tool_name": "locate_map",
                    "status": "succeeded",
                },
            )
        )

    assert health_provider.calls == 0


def test_search_application_builder_wires_server_authorities_to_correct_layers() -> None:
    from app.api.search_routes import (
        _build_search_application_service,
        _provider_health_service,
    )

    class SearchServiceStub:
        def get_retrieval_port(self):
            return EmptyRetrievalPort()

    document_repository = object()
    application_service = _build_search_application_service(
        search_service=SearchServiceStub(),
        asset_service=object(),
        contract_service=object(),
        document_repository=document_repository,
    )

    assert application_service.document_repository is document_repository
    assert application_service.agent_runtime.provider_health_provider is _provider_health_service
