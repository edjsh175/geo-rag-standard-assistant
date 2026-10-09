"""Tests for Phase 3: Distributed Session Lock and Postgres Advisory Lock derivation."""

from __future__ import annotations

import asyncio
import pytest

from app.services.agent.distributed_lock import (
    AutoSelectingSessionLock,
    LocalAsyncioSessionLock,
    PostgresAdvisorySessionLock,
    RedisDistributedSessionLock,
    SessionLockAcquisitionError,
    derive_advisory_lock_id,
    get_session_lock,
)


class _Provider:
    def __init__(self, available=True, result=False, raises=None):
        self._is_available = available
        self._client = object() if available else None
        self.result = result
        self.raises = raises
        self.calls = 0

    async def acquire(self, *args, **kwargs):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.result

    async def release(self, *args, **kwargs):
        pass


def test_derive_advisory_lock_id_in_signed_64bit_range() -> None:
    for principal, sess in [
        ("user_1", "session_abc"),
        ("visitor_xyz", "session_1234567890"),
        ("", ""),
        ("a" * 100, "b" * 100),
    ]:
        val = derive_advisory_lock_id(principal, sess)
        assert isinstance(val, int)
        assert -(2**63) <= val <= (2**63 - 1)


def test_derive_advisory_lock_id_deterministic() -> None:
    id1 = derive_advisory_lock_id("user_1", "sess_alpha")
    id2 = derive_advisory_lock_id("user_1", "sess_alpha")
    id3 = derive_advisory_lock_id("user_2", "sess_alpha")
    assert id1 == id2
    assert id1 != id3


@pytest.mark.asyncio
async def test_local_asyncio_session_lock_mutual_exclusion() -> None:
    lock_mgr = LocalAsyncioSessionLock()
    principal = "test_user"
    session_id = "test_session"

    order = []

    async def worker_1():
        async with lock_mgr.lock(principal, session_id):
            order.append("w1_start")
            await asyncio.sleep(0.05)
            order.append("w1_end")

    async def worker_2():
        await asyncio.sleep(0.01)  # Ensure w1 acquires first
        async with lock_mgr.lock(principal, session_id):
            order.append("w2_start")
            order.append("w2_end")

    await asyncio.gather(worker_1(), worker_2())
    assert order == ["w1_start", "w1_end", "w2_start", "w2_end"]


@pytest.mark.asyncio
async def test_session_lock_timeout_raises_error() -> None:
    lock_mgr = LocalAsyncioSessionLock()
    principal = "test_user"
    session_id = "test_session_timeout"

    acquired = await lock_mgr.acquire(principal, session_id, timeout_seconds=1.0)
    assert acquired is True

    # Second acquisition with 0.05s timeout must fail and raise error
    with pytest.raises(SessionLockAcquisitionError):
        async with lock_mgr.lock(principal, session_id, timeout_seconds=0.05):
            pass

    await lock_mgr.release(principal, session_id)


@pytest.mark.asyncio
async def test_auto_selecting_session_lock_fallback_to_local() -> None:
    auto_lock = AutoSelectingSessionLock()
    principal = "p_auto"
    session_id = "s_auto"

    async with auto_lock.lock(principal, session_id):
        # Successfully acquired via available provider (local fallback in test env)
        pass


@pytest.mark.asyncio
async def test_auto_lock_does_not_fallback_after_distributed_lock_timeout() -> None:
    pg = _Provider(result=False)
    redis = _Provider(result=True)
    local = _Provider(available=True, result=True)
    lock = AutoSelectingSessionLock(pg, redis, local)

    assert await lock.acquire("p", "s", timeout_seconds=0) is False
    assert pg.calls == 1
    assert redis.calls == local.calls == 0


@pytest.mark.asyncio
async def test_auto_lock_fails_closed_when_configured_provider_errors() -> None:
    pg = _Provider(raises=RuntimeError("database unavailable"))
    redis = _Provider(available=False)
    local = _Provider(available=True, result=True)
    lock = AutoSelectingSessionLock(pg, redis, local)

    assert await lock.acquire("p", "s") is False
    assert local.calls == 0


@pytest.mark.asyncio
async def test_postgres_same_key_acquires_are_serialized_without_overwriting_connection() -> None:
    class Result:
        def mappings(self):
            return self
        def first(self):
            return {"locked": True}

    class Connection:
        closed = False
        async def execute(self, *args, **kwargs):
            return Result()
        async def rollback(self):
            pass
        async def close(self):
            self.closed = True

    class Engine:
        def __init__(self): self.connections = []
        async def connect(self):
            conn = Connection()
            self.connections.append(conn)
            return conn

    class Manager:
        def __init__(self): self.postgres_engine = Engine()

    manager = Manager()
    lock = PostgresAdvisorySessionLock(manager)
    assert await lock.acquire("p", "s")
    held = lock._held_connections[("p", "s")][0]
    waiter = asyncio.create_task(lock.acquire("p", "s", timeout_seconds=1))
    await asyncio.sleep(0.01)
    assert not waiter.done()
    assert lock._held_connections[("p", "s")][0] is held
    await lock.release("p", "s")
    assert await waiter
    assert lock._held_connections[("p", "s")][0] is not held
    await lock.release("p", "s")


@pytest.mark.asyncio
async def test_redis_same_key_acquire_does_not_overwrite_token() -> None:
    class Redis:
        def __init__(self): self.values = {}
        async def set(self, key, value, **kwargs):
            self.values[key] = value
            return True
        async def eval(self, script, count, key, token):
            if self.values.get(key) == token: del self.values[key]

    redis = Redis()
    lock = RedisDistributedSessionLock(redis)
    assert await lock.acquire("p", "s", timeout_seconds=0)
    token = lock._tokens[("p", "s")]
    redis.values.clear()  # Simulate lease expiry while this instance still owns it.
    assert await lock.acquire("p", "s", timeout_seconds=0) is False
    assert lock._tokens[("p", "s")] == token
    await lock.release("p", "s")


@pytest.mark.asyncio
async def test_postgres_lock_context_cancellation_releases_local_ownership() -> None:
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": True}
    class Connection:
        async def execute(self, *args, **kwargs): return Result()
        async def rollback(self): pass
        async def close(self): pass
    class Engine:
        async def connect(self): return Connection()
    class Manager:
        postgres_engine = Engine()

    lock = PostgresAdvisorySessionLock(Manager())
    started = asyncio.Event()
    async def holder():
        async with lock.lock("p", "cancel"):
            started.set()
            await asyncio.Future()
    task = asyncio.create_task(holder())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await lock.acquire("p", "cancel", timeout_seconds=0)
    await lock.release("p", "cancel")


@pytest.mark.asyncio
async def test_postgres_releases_transaction_before_returning_connection_to_pool() -> None:
    calls = []
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": True}
    class Connection:
        async def execute(self, statement, *args, **kwargs):
            calls.append(str(statement))
            return Result()
        async def rollback(self): calls.append("ROLLBACK")
        async def close(self): calls.append("CLOSE")
    class Engine:
        async def connect(self): return Connection()
    class Manager:
        postgres_engine = Engine()

    lock = PostgresAdvisorySessionLock(Manager())
    assert await lock.acquire("p", "s")
    await lock.release("p", "s")
    assert calls.index("ROLLBACK") < calls.index("CLOSE")


@pytest.mark.asyncio
async def test_postgres_competition_timeout_cleans_connection_and_key_lock() -> None:
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": False}
    class Connection:
        def __init__(self): self.closed = False
        async def execute(self, *args, **kwargs): return Result()
        async def rollback(self): pass
        async def close(self): self.closed = True
    class Engine:
        def __init__(self): self.connections = []
        async def connect(self):
            connection = Connection()
            self.connections.append(connection)
            return connection
    class Manager:
        def __init__(self): self.postgres_engine = Engine()

    manager = Manager()
    lock = PostgresAdvisorySessionLock(manager)
    assert await lock.acquire("p", "contended", timeout_seconds=0) is False
    assert manager.postgres_engine.connections[0].closed
    assert await lock.acquire("p", "contended", timeout_seconds=0) is False


@pytest.mark.asyncio
async def test_postgres_acquire_cancellation_preserves_cancelled_error_and_unlocks_key() -> None:
    entered = asyncio.Event()
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": True}
    class Connection:
        calls = 0
        async def execute(self, *args, **kwargs):
            Connection.calls += 1
            if Connection.calls == 1:
                entered.set()
                await asyncio.Future()
            return Result()
        async def rollback(self): pass
        async def close(self): pass
    class Engine:
        async def connect(self): return Connection()
    class Manager:
        postgres_engine = Engine()

    lock = PostgresAdvisorySessionLock(Manager())
    task = asyncio.create_task(lock.acquire("p", "cancel-acquire", timeout_seconds=10))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await lock.acquire("p", "cancel-acquire", timeout_seconds=0)
    await lock.release("p", "cancel-acquire")


@pytest.mark.asyncio
async def test_postgres_invalidate_connection_when_acquired_lock_rollback_fails() -> None:
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": True}
    class Connection:
        def __init__(self): self.invalidated = False; self.closed = False
        async def execute(self, *args, **kwargs): return Result()
        async def rollback(self): raise RuntimeError("rollback failed")
        async def invalidate(self): self.invalidated = True
        async def close(self): self.closed = True
    class Engine:
        def __init__(self): self.connection = Connection()
        async def connect(self): return self.connection
    class Manager:
        def __init__(self): self.postgres_engine = Engine()

    manager = Manager()
    lock = PostgresAdvisorySessionLock(manager)
    assert await lock.acquire("p", "rollback-fails") is False
    assert manager.postgres_engine.connection.invalidated
    assert manager.postgres_engine.connection.closed


@pytest.mark.asyncio
async def test_postgres_invalidate_connection_when_unlock_fails() -> None:
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": True}
    class Connection:
        def __init__(self): self.invalidated = False
        async def execute(self, statement, *args, **kwargs):
            if "unlock" in str(statement): raise RuntimeError("unlock failed")
            return Result()
        async def rollback(self): pass
        async def invalidate(self): self.invalidated = True
        async def close(self): pass
    class Engine:
        def __init__(self): self.connection = Connection()
        async def connect(self): return self.connection
    class Manager:
        def __init__(self): self.postgres_engine = Engine()

    manager = Manager()
    lock = PostgresAdvisorySessionLock(manager)
    assert await lock.acquire("p", "unlock-fails")
    await lock.release("p", "unlock-fails")
    assert manager.postgres_engine.connection.invalidated


@pytest.mark.asyncio
async def test_postgres_cancelled_release_always_releases_local_key_lock() -> None:
    unlock_started = asyncio.Event()
    class Result:
        def mappings(self): return self
        def first(self): return {"locked": True}
    class Connection:
        block_unlock = True
        async def execute(self, statement, *args, **kwargs):
            if "unlock" in str(statement) and Connection.block_unlock:
                Connection.block_unlock = False
                unlock_started.set()
                await asyncio.Future()
            return Result()
        async def rollback(self): pass
        async def close(self): pass
    class Engine:
        async def connect(self): return Connection()
    class Manager:
        postgres_engine = Engine()

    lock = PostgresAdvisorySessionLock(Manager())
    assert await lock.acquire("p", "cancel-release")
    task = asyncio.create_task(lock.release("p", "cancel-release"))
    await unlock_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await lock.acquire("p", "cancel-release", timeout_seconds=0)
    await lock.release("p", "cancel-release")


def test_get_session_lock_singleton() -> None:
    lock1 = get_session_lock()
    lock2 = get_session_lock()
    assert lock1 is lock2
