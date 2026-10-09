"""Tests for Phase 3: Distributed Agent Event Bus and serialization."""

from __future__ import annotations

import asyncio
from datetime import datetime
import pytest

from app.services.agent.event_bus import (
    CompositeAgentEventBus,
    LocalAgentEventBus,
    RedisAgentEventBus,
    deserialize_agent_event,
    get_agent_event_bus,
    serialize_agent_event,
)
from app.services.agent.events import AgentEvent


def test_agent_event_serialization_roundtrip() -> None:
    now = datetime.now()
    ev = AgentEvent(
        event_id="ev_001",
        event_type="action_approval_required",
        session_id="session_test",
        turn_id="turn_1",
        trace_id="trace_xyz",
        payload={"risk_level": "HIGH_RISK", "tool_name": "import_vector_dataset"},
        created_at=now,
        sequence=42,
    )

    serialized = serialize_agent_event(ev)
    assert isinstance(serialized, str)
    assert "action_approval_required" in serialized

    deserialized = deserialize_agent_event(serialized)
    assert deserialized.event_id == ev.event_id
    assert deserialized.event_type == ev.event_type
    assert deserialized.session_id == ev.session_id
    assert deserialized.turn_id == ev.turn_id
    assert deserialized.sequence == 42
    assert deserialized.payload["risk_level"] == "HIGH_RISK"


@pytest.mark.asyncio
async def test_local_agent_event_bus_fan_out() -> None:
    bus = LocalAgentEventBus()
    session_id = "sess_fanout"

    received_sub1 = []
    received_sub2 = []

    async def sub1():
        async for ev in bus.subscribe(session_id):
            received_sub1.append(ev.event_id)
            if len(received_sub1) == 2:
                break

    async def sub2():
        async for ev in bus.subscribe(session_id):
            received_sub2.append(ev.event_id)
            if len(received_sub2) == 2:
                break

    t1 = asyncio.create_task(sub1())
    t2 = asyncio.create_task(sub2())
    await asyncio.sleep(0.01)

    ev1 = AgentEvent(
        event_id="e1",
        event_type="test_event",
        session_id=session_id,
        turn_id="t1",
        trace_id="",
        payload={},
        created_at=datetime.now(),
    )
    ev2 = AgentEvent(
        event_id="e2",
        event_type="test_event",
        session_id=session_id,
        turn_id="t1",
        trace_id="",
        payload={},
        created_at=datetime.now(),
    )

    await bus.publish(session_id, ev1)
    await bus.publish(session_id, ev2)

    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)

    assert received_sub1 == ["e1", "e2"]
    assert received_sub2 == ["e1", "e2"]


@pytest.mark.asyncio
async def test_composite_agent_event_bus() -> None:
    bus = CompositeAgentEventBus()
    session_id = "sess_composite"
    stream = bus.subscribe(session_id)

    async def receiver():
        try:
            async for ev in stream:
                return ev
        finally:
            await stream.aclose()

    task = asyncio.create_task(receiver())
    await asyncio.sleep(0.01)

    ev = AgentEvent(
        event_id="comp_1",
        event_type="status",
        session_id=session_id,
        turn_id="t1",
        trace_id="",
        payload={"ok": True},
        created_at=datetime.now(),
    )
    await bus.publish(session_id, ev)

    received = await asyncio.wait_for(task, timeout=1.0)
    assert received.event_id == "comp_1"


@pytest.mark.asyncio
async def test_composite_subscribe_receives_remote_and_deduplicates_local_echo() -> None:
    class PubSub:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.closed = False
            self.ready = asyncio.Event()
        async def subscribe(self, channel):
            self.channel = channel
            self.ready.set()
        async def listen(self):
            while True: yield await self.queue.get()
        async def unsubscribe(self, channel): pass
        async def close(self): self.closed = True
    class Redis:
        def __init__(self): self.pubsub_instance = PubSub()
        def pubsub(self): return self.pubsub_instance
        async def publish(self, channel, raw):
            await self.pubsub_instance.queue.put({"type":"message", "data":raw})

    redis = Redis()
    bus = CompositeAgentEventBus(redis_bus=RedisAgentEventBus(redis))
    session_id = "remote"
    received = []
    same_received = asyncio.Event()
    stream = bus.subscribe(session_id)
    async def receiver():
        try:
            async for event in stream:
                received.append(event.event_id)
                if event.event_id == "same":
                    same_received.set()
                if event.event_id == "sentinel": return
        finally:
            await stream.aclose()
    task = asyncio.create_task(receiver())
    await asyncio.wait_for(redis.pubsub_instance.ready.wait(), timeout=1)
    while not bus.local_bus._subscribers.get(session_id):
        await asyncio.sleep(0)
    duplicate = AgentEvent(event_type="status", session_id=session_id, turn_id="t", event_id="same")
    sentinel = AgentEvent(event_type="status", session_id=session_id, turn_id="t", event_id="sentinel")
    await bus.redis_bus.publish(session_id, duplicate)
    await asyncio.wait_for(same_received.wait(), timeout=1)
    await bus.local_bus.publish(session_id, duplicate)
    await bus.local_bus.publish(session_id, sentinel)
    await asyncio.wait_for(task, timeout=1)
    assert received == ["same", "sentinel"]
    assert redis.pubsub_instance.closed
    assert bus.local_bus._subscribers == {}


@pytest.mark.asyncio
async def test_composite_subscribe_cancellation_closes_both_subscriptions() -> None:
    class PubSub:
        def __init__(self): self.queue = asyncio.Queue(); self.closed = False
        async def subscribe(self, channel): pass
        async def listen(self):
            while True: yield await self.queue.get()
        async def unsubscribe(self, channel): pass
        async def close(self): self.closed = True
    class Redis:
        def __init__(self): self.ps = PubSub()
        def pubsub(self): return self.ps
    redis = Redis()
    bus = CompositeAgentEventBus(redis_bus=RedisAgentEventBus(redis))
    stream = bus.subscribe("cancel")
    task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    await stream.aclose()
    assert redis.ps.closed
    assert bus.local_bus._subscribers == {}


def test_get_agent_event_bus_singleton() -> None:
    b1 = get_agent_event_bus()
    b2 = get_agent_event_bus()
    assert b1 is b2
