"""Distributed agent event bus supporting in-memory fan-out and Redis Pub/Sub horizontal scaling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections import deque
from datetime import datetime
import json
import logging
from typing import AsyncIterator, Optional, Set
from uuid import uuid4

from app.services.agent.events import AgentEvent

logger = logging.getLogger(__name__)


def serialize_agent_event(event: AgentEvent) -> str:
    """Serialize an AgentEvent to JSON string."""
    payload = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "session_id": event.session_id,
        "turn_id": event.turn_id,
        "trace_id": event.trace_id,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
        "sequence": getattr(event, "sequence", 0),
    }
    return json.dumps(payload, ensure_ascii=False)


def deserialize_agent_event(raw: str | bytes) -> AgentEvent:
    """Deserialize a JSON string or bytes to an AgentEvent."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    created_at = datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
    return AgentEvent(
        event_id=data.get("event_id", ""),
        event_type=data.get("event_type", ""),
        session_id=data.get("session_id", ""),
        turn_id=data.get("turn_id", ""),
        trace_id=data.get("trace_id", ""),
        payload=data.get("payload", {}),
        created_at=created_at,
        sequence=data.get("sequence", 0),
    )


class AgentEventBus(ABC):
    """Abstract interface for event publishing and subscription."""

    @abstractmethod
    async def publish(self, session_id: str, event: AgentEvent) -> None:
        """Publish an agent event for a given session."""
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """Subscribe to live agent events for a given session."""
        raise NotImplementedError


class LocalAgentEventBus(AgentEventBus):
    """In-memory asyncio.Queue based event bus for single-process operation."""

    def __init__(self) -> None:
        self._subscribers: dict[str, Set[asyncio.Queue[AgentEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, session_id: str, event: AgentEvent) -> None:
        key = session_id.strip()
        async with self._lock:
            queues = list(self._subscribers.get(key, ()))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event queue full for session %s, dropping event %s", key, event.event_id)

    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        key = session_id.strip()
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=500)
        async with self._lock:
            self._subscribers.setdefault(key, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                queues = self._subscribers.get(key)
                if queues:
                    queues.discard(queue)
                    if not queues:
                        self._subscribers.pop(key, None)


class RedisAgentEventBus(AgentEventBus):
    """Redis Pub/Sub backed event bus for multi-pod/multi-instance cluster fan-out."""

    def __init__(self, redis_client=None) -> None:
        self._redis_client = redis_client

    @property
    def _client(self):
        if self._redis_client is not None:
            return self._redis_client
        from app.core.database import db_manager

        return getattr(db_manager, "redis_client", None)

    def _channel_name(self, session_id: str) -> str:
        return f"geoai:events:{session_id.strip()}"

    async def publish(self, session_id: str, event: AgentEvent) -> None:
        client = self._client
        if client is None:
            return
        channel = self._channel_name(session_id)
        raw = serialize_agent_event(event)
        try:
            await client.publish(channel, raw)
        except Exception as exc:
            logger.warning("Failed to publish event to Redis channel %s: %s", channel, exc)

    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        client = self._client
        if client is None:
            return
        channel = self._channel_name(session_id)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if data:
                        try:
                            yield deserialize_agent_event(data)
                        except Exception as exc:
                            logger.error("Failed to parse event from Redis: %s", exc)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception as exc:
                logger.warning("Error closing Redis pubsub channel %s: %s", channel, exc)


class CompositeAgentEventBus(AgentEventBus):
    """Composite event bus delivering to local subscribers AND broadcasting to Redis."""

    def __init__(
        self,
        local_bus: Optional[LocalAgentEventBus] = None,
        redis_bus: Optional[RedisAgentEventBus] = None,
    ) -> None:
        self.local_bus = local_bus or LocalAgentEventBus()
        self.redis_bus = redis_bus or RedisAgentEventBus()

    async def publish(self, session_id: str, event: AgentEvent) -> None:
        # Publish locally first
        await self.local_bus.publish(session_id, event)
        # Fan out to Redis cluster
        if self.redis_bus._client is not None:
            await self.redis_bus.publish(session_id, event)

    async def subscribe(self, session_id: str) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=500)
        seen_ids: set[str] = set()
        recent_ids: deque[str] = deque()

        async def forward(source: AsyncIterator[AgentEvent]) -> None:
            async for event in source:
                await queue.put(event)

        sources = [self.local_bus.subscribe(session_id)]
        if self.redis_bus._client is not None:
            sources.append(self.redis_bus.subscribe(session_id))
        tasks = [asyncio.create_task(forward(source)) for source in sources]
        try:
            while True:
                event = await queue.get()
                if event.event_id and event.event_id in seen_ids:
                    continue
                if event.event_id:
                    seen_ids.add(event.event_id)
                    recent_ids.append(event.event_id)
                    if len(recent_ids) > 5000:
                        seen_ids.discard(recent_ids.popleft())
                yield event
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for source in sources:
                close = getattr(source, "aclose", None)
                if close is not None:
                    await close()


_default_bus: Optional[AgentEventBus] = None


def get_agent_event_bus() -> AgentEventBus:
    """Singleton getter for the system agent event bus."""
    global _default_bus
    if _default_bus is None:
        _default_bus = CompositeAgentEventBus()
    return _default_bus
