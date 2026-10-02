"""Regression tests for Phase 1 physical orchestration boundaries."""

from __future__ import annotations

import pytest

from app.services.agent.context import ContextEngine
from app.services.agent.orchestration import (
    BrowserContinuationHandler,
    ContextProjector,
    Publisher,
    SessionLoader,
)
from app.services.agent.session import PendingBrowserExecution
from app.services.agent.store import InMemoryAgentStore
from app.services.agent.tools import build_default_tool_registry


@pytest.mark.asyncio
async def test_session_loader_resolves_session_and_pending_execution_without_semantic_work() -> None:
    store = InMemoryAgentStore()
    session = await store.get_or_create_session("user-1", "session-1")
    pending = PendingBrowserExecution(
        token="continuation-1",
        question="导入这个文件",
        turn_id="turn-1",
        trace_id="trace-1",
        tool_call_id="call-1",
        tool_name="import_vector_dataset",
        observations=(),
        request_context={},
        reviewer_enabled=False,
        thinking=False,
        max_steps=12,
        steps_used=1,
        max_elapsed_seconds=30.0,
        retrieval_constraints=None,
        main_model_name=None,
        session_id="session-1",
    )
    session.pending_browser_execution = pending

    loaded = await SessionLoader(store).load(
        principal_id="user-1",
        session_id="session-1",
    )

    assert loaded.session is session
    assert loaded.pending_execution is pending


@pytest.mark.asyncio
async def test_context_projector_owns_controller_projection_and_dynamic_action_surface() -> None:
    store = InMemoryAgentStore()
    session = await store.get_or_create_session("user-1", "session-1")
    projector = ContextProjector(ContextEngine())

    projected = projector.project_controller(
        session=session,
        principal_id="user-1",
        turn_id="turn-1",
        question="查询滑坡监测标准",
        request_context={},
        registry=build_default_tool_registry(),
        provider_health={},
        reviewer_enabled=False,
    )

    assert projected.controller_projection.user_question == "查询滑坡监测标准"
    assert projected.action_state.has_evidence is False
    assert "compose_answer" not in projected.action_state.available_control_actions
    assert "retrieve_kb" in projected.action_state.available_capabilities
    assert projected.all_ledger_items == ()


@pytest.mark.asyncio
async def test_browser_continuation_handler_consumes_pending_and_materializes_receipt_evidence() -> None:
    store = InMemoryAgentStore()
    session = await store.get_or_create_session("user-1", "session-1")
    pending = PendingBrowserExecution(
        token="continuation-1",
        question="导入这个文件",
        turn_id="turn-1",
        trace_id="trace-1",
        tool_call_id="call-1",
        tool_name="import_vector_dataset",
        observations=(),
        request_context={},
        reviewer_enabled=False,
        thinking=False,
        max_steps=12,
        steps_used=1,
        max_elapsed_seconds=30.0,
        retrieval_constraints=None,
        main_model_name="main-model",
        session_id="session-1",
    )
    session.pending_browser_execution = pending
    await store.save_pending_execution("user-1", pending, ttl_seconds=60)

    resumed = await BrowserContinuationHandler(store).resume(
        session=session,
        principal_id="user-1",
        session_id="session-1",
        pending=pending,
        continuation_token="continuation-1",
        receipt={
            "tool_call_id": "call-1",
            "tool_name": "import_vector_dataset",
            "status": "succeeded",
            "output": {"layer_ref": "ul-1"},
            "effect": {"status": "applied", "state_revision": 2},
            "map_context": {"schema_version": 2, "revision": 2},
        },
    )

    assert session.pending_browser_execution is None
    assert resumed.turn_id == "turn-1"
    assert resumed.observations[-1].status == "browser_succeeded"
    assert resumed.observations[-1].payload["evidence_id"]
    assert resumed.completion_event.event_type == "browser_tool_completed"
    assert await store.get_pending_execution("user-1", "session-1") is None


@pytest.mark.asyncio
async def test_publisher_persists_one_terminal_publication_without_duplication() -> None:
    store = InMemoryAgentStore()
    session = await store.get_or_create_session("user-1", "session-1")
    turn_events = []
    observed = []

    await Publisher(store).publish(
        principal_id="user-1",
        session=session,
        turn_events=turn_events,
        turn_id="turn-1",
        trace_id="trace-1",
        publication_state="published",
        text="已完成。",
        payload={"source": "controller_direct"},
        event_listener=observed.append,
        persist_evidence=True,
    )

    durable_events = await store.list_events("user-1", "session-1")
    assert [event.event_type for event in durable_events] == [
        "publication_completed",
        "assistant_message",
    ]
    assert durable_events[0].payload == {
        "state": "published",
        "source": "controller_direct",
    }
    assert durable_events[1].payload == {"text": "已完成。"}
    assert [event.event_type for event in turn_events] == ["publication_completed"]
    assert [event.event_type for event in observed] == ["publication_completed"]


@pytest.mark.asyncio
async def test_turn_lifecycle_coordinator_prepares_new_turn_without_agent_semantics() -> None:
    from types import SimpleNamespace
    from app.services.agent.orchestration import TurnLifecycleCoordinator

    store = InMemoryAgentStore()
    turn_events = []
    session_only_events = []

    async def append_turn_event(event):
        turn_events.append(event)

    async def append_session_event(event):
        session_only_events.append(event)

    async def persist_evidence():
        raise AssertionError('new turn must not persist receipt evidence')

    request = SimpleNamespace(
        question='  查询成都规划标准  ', principal_id='user-1', session_id='session-1',
        request_context={'user_ui_selections': {'layer_ref': 'ul-1'}}, reviewer_enabled=True,
        thinking=True, retrieval_constraints=None, max_steps=8, max_elapsed_seconds=20.0,
        continuation_token=None, browser_tool_receipt=None,
        legacy_history=({'role': 'user', 'content': '历史问题'},),
    )
    prepared = await TurnLifecycleCoordinator(store).prepare(
        request=request, append_turn_event=append_turn_event, append_session_event=append_session_event,
        persist_evidence=persist_evidence, resolve_main_model=lambda thinking: 'main-thinking' if thinking else 'main',
    )
    assert prepared.question == '查询成都规划标准'
    assert prepared.initial_steps == 0
    assert prepared.main_model_name == 'main-thinking'
    assert prepared.observations == ()
    assert prepared.request_context == request.request_context
    assert [event.event_type for event in session_only_events] == ['user_message']
    assert session_only_events[0].turn_id == 'legacy-1'
    assert [event.event_type for event in turn_events] == ['user_message']
    assert turn_events[0].payload['user_ui_selections'] == {'layer_ref': 'ul-1'}


@pytest.mark.asyncio
async def test_turn_lifecycle_coordinator_resumes_browser_turn_and_preserves_authoritative_ids() -> None:
    from types import SimpleNamespace
    from app.services.agent.orchestration import TurnLifecycleCoordinator

    store = InMemoryAgentStore()
    session = await store.get_or_create_session('user-1', 'session-1')
    pending = PendingBrowserExecution(
        token='continuation-1', question='导入这个文件', turn_id='turn-1', trace_id='trace-1',
        tool_call_id='call-1', tool_name='import_vector_dataset', observations=(),
        request_context={'source': 'original'}, reviewer_enabled=False, thinking=False, max_steps=12,
        steps_used=3, max_elapsed_seconds=18.0, retrieval_constraints=None, main_model_name='main-model',
        session_id='session-1',
    )
    session.pending_browser_execution = pending
    await store.save_pending_execution('user-1', pending, ttl_seconds=60)
    turn_events = []
    evidence_persisted = []

    async def append_turn_event(event):
        turn_events.append(event)

    async def append_session_event(_event):
        raise AssertionError('continuation must not seed legacy history')

    async def persist_evidence(_session):
        evidence_persisted.append(True)

    request = SimpleNamespace(
        question='ignored on continuation', principal_id='user-1', session_id='session-1', request_context={},
        reviewer_enabled=True, thinking=True, retrieval_constraints=None, max_steps=99, max_elapsed_seconds=99.0,
        continuation_token='continuation-1',
        browser_tool_receipt={'tool_call_id':'call-1','tool_name':'import_vector_dataset','status':'succeeded',
                              'output':{'layer_ref':'ul-1'},'effect':{'status':'applied'},'map_context':{'revision':2}},
        legacy_history=(),
    )
    prepared = await TurnLifecycleCoordinator(store).prepare(
        request=request, append_turn_event=append_turn_event, append_session_event=append_session_event,
        persist_evidence=persist_evidence, resolve_main_model=lambda _thinking: 'must-not-be-used',
    )
    assert prepared.session is session
    assert prepared.question == '导入这个文件'
    assert prepared.turn_id == 'turn-1'
    assert prepared.trace_id == 'trace-1'
    assert prepared.initial_steps == 3
    assert prepared.main_model_name == 'main-model'
    assert prepared.observations[-1].status == 'browser_succeeded'
    assert prepared.request_context['browser_observations']['map_context'] == {'revision': 2}
    assert evidence_persisted == [True]
    assert [event.event_type for event in turn_events] == ['browser_tool_completed']
