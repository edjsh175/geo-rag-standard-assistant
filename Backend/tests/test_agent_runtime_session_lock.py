import asyncio
from types import SimpleNamespace

import pytest

from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.distributed_lock import SessionLockAcquisitionError


class RecordingLock:
    def __init__(self):
        self.active = set()
        self.events = []
        self.guard = asyncio.Lock()

    def lock(self, principal_id, session_id):
        return self._lock(principal_id, session_id)

    class _Lock:
        def __init__(self, owner, key):
            self.owner = owner
            self.key = key

        async def __aenter__(self):
            await self.owner.guard.acquire()
            while self.key in self.owner.active:
                self.owner.guard.release()
                await asyncio.sleep(0)
                await self.owner.guard.acquire()
            self.owner.active.add(self.key)
            self.owner.events.append(("acquire", self.key))
            self.owner.guard.release()

        async def __aexit__(self, *exc):
            async with self.owner.guard:
                self.owner.active.remove(self.key)
                self.owner.events.append(("release", self.key))

    def _lock(self, principal_id, session_id):
        return self._Lock(self, (principal_id, session_id))


def make_runtime(lock):
    runtime = object.__new__(AgentRuntime)
    runtime.session_lock = lock
    return runtime


def make_request(session_id="s1"):
    return AgentRunRequest(question="q", session_id=session_id, principal_id="p")


@pytest.mark.asyncio
async def test_same_session_runs_are_exclusive_from_before_prepare_through_completion():
    lock = RecordingLock()
    runtime = make_runtime(lock)
    active = 0
    peak = 0
    prepared_under_lock = []

    async def prepare(request, listener):
        nonlocal active, peak
        prepared_under_lock.append((request.session_id, (request.principal_id, request.session_id) in lock.active))
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return SimpleNamespace()

    runtime._prepare_turn_context = prepare
    runtime._maybe_update_conversation_memory = lambda ctx: asyncio.sleep(0)

    async def execute(ctx):
        assert ("p", "s1") in lock.active
        await asyncio.sleep(0.01)
        return "done"

    runtime._execute_planning_graph = execute

    await asyncio.gather(runtime.run(make_request()), runtime.run(make_request()))

    assert peak == 1
    assert prepared_under_lock == [("s1", True), ("s1", True)]
    assert len(lock.events) == 4


@pytest.mark.asyncio
async def test_different_sessions_can_run_in_parallel():
    lock = RecordingLock()
    runtime = make_runtime(lock)
    active = 0
    peak = 0
    both_entered = asyncio.Event()

    async def prepare(request, listener):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        active -= 1
        return SimpleNamespace()

    runtime._prepare_turn_context = prepare
    runtime._maybe_update_conversation_memory = lambda ctx: asyncio.sleep(0)
    runtime._execute_planning_graph = lambda ctx: asyncio.sleep(0, result="done")

    await asyncio.gather(runtime.run(make_request("s1")), runtime.run(make_request("s2")))

    assert peak == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("prepare failed"), asyncio.CancelledError()])
async def test_lock_is_released_when_prepare_raises_or_run_is_cancelled(failure):
    lock = RecordingLock()
    runtime = make_runtime(lock)

    async def prepare(request, listener):
        raise failure

    runtime._prepare_turn_context = prepare

    with pytest.raises(type(failure)):
        await runtime.run(make_request())

    assert lock.active == set()
    assert lock.events[-1] == ("release", ("p", "s1"))


def test_runtime_accepts_injected_session_lock():
    from app.services.agent.store import InMemoryAgentStore

    lock = RecordingLock()
    runtime = AgentRuntime(
        retrieval_port=object(),
        controller=object(),
        answer_generator=object(),
        session_store=InMemoryAgentStore(),
        session_lock=lock,
    )

    assert runtime.session_lock is lock


def test_default_local_lock_is_shared_across_runtime_instances():
    from app.services.agent.store import InMemoryAgentStore

    store = InMemoryAgentStore()
    options = dict(
        retrieval_port=object(),
        controller=object(),
        answer_generator=object(),
        session_store=store,
    )

    first = AgentRuntime(**options)
    second = AgentRuntime(**options)

    assert first.session_lock is second.session_lock


@pytest.mark.asyncio
async def test_query_route_maps_lock_timeout_to_conflict():
    from fastapi import HTTPException

    from app.api.search_routes import search_documents
    from app.core.auth import UserIdentity
    from app.models.search_models import SearchRequest

    class Application:
        async def execute(self, *args, **kwargs):
            raise SessionLockAcquisitionError("busy")

    with pytest.raises(HTTPException) as exc_info:
        await search_documents(
            SearchRequest(query="q", use_generation=True),
            UserIdentity(username="admin"),
            Application(),
            object(),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_sse_route_keeps_lock_timeout_as_409_problem_event():
    import json

    from app.api.search_routes import stream_search_documents
    from app.core.auth import UserIdentity
    from app.models.search_models import SearchRequest

    class Application:
        async def stream(self, *args, **kwargs):
            raise SessionLockAcquisitionError("busy")
            yield None

    response = await stream_search_documents(
        SearchRequest(query="q", use_generation=True),
        UserIdentity(username="admin"),
        Application(),
        object(),
    )
    chunks = [chunk async for chunk in response.body_iterator]
    body = b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in chunks)
    data = next(line[6:] for line in body.decode().splitlines() if line.startswith("data: "))

    assert json.loads(data)["status"] == 409
