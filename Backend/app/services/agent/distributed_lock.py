"""Distributed session lock supporting PostgreSQL advisory lock, Redis, and local asyncio fallback.

Enforces mutual exclusion across concurrent agent turns for the same (principal_id, session_id).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from contextlib import asynccontextmanager
import hashlib
import logging
import time
from typing import AsyncGenerator, Optional
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


def derive_advisory_lock_id(principal_id: str, session_id: str) -> int:
    """Derive a signed 64-bit integer from principal_id:session_id for Postgres pg_advisory_lock."""
    composite = f"{principal_id.strip()}:{session_id.strip()}".encode("utf-8")
    digest = hashlib.sha256(composite).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class SessionLockAcquisitionError(RuntimeError):
    """Raised when a session lock cannot be acquired within the timeout."""


class DistributedSessionLock(ABC):
    """Abstract interface for distributed session exclusion."""

    @abstractmethod
    async def acquire(
        self,
        principal_id: str,
        session_id: str,
        timeout_seconds: float = 10.0,
    ) -> bool:
        """Attempt to acquire lock for (principal_id, session_id). Returns True if acquired."""
        raise NotImplementedError

    @abstractmethod
    async def release(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        """Release the acquired lock for (principal_id, session_id)."""
        raise NotImplementedError

    @asynccontextmanager
    async def lock(
        self,
        principal_id: str,
        session_id: str,
        timeout_seconds: float = 10.0,
    ) -> AsyncGenerator[None, None]:
        """Context manager for acquiring and safely releasing session lock."""
        acquired = await self.acquire(principal_id, session_id, timeout_seconds=timeout_seconds)
        if not acquired:
            raise SessionLockAcquisitionError(
                f"Failed to acquire session lock for session '{session_id}' within {timeout_seconds}s"
            )
        try:
            yield
        finally:
            try:
                await self.release(principal_id, session_id)
            except Exception as exc:
                logger.warning(
                    "Error releasing session lock for session '%s': %s",
                    session_id,
                    exc,
                )


class LocalAsyncioSessionLock(DistributedSessionLock):
    """Process-local in-memory lock using asyncio.Lock."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_lock(self, principal_id: str, session_id: str) -> asyncio.Lock:
        key = (principal_id.strip(), session_id.strip())
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def acquire(
        self,
        principal_id: str,
        session_id: str,
        timeout_seconds: float = 10.0,
    ) -> bool:
        lock = await self._get_lock(principal_id, session_id)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout_seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def release(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        key = (principal_id.strip(), session_id.strip())
        async with self._global_lock:
            lock = self._locks.get(key)
        if lock and lock.locked():
            lock.release()


class PostgresAdvisorySessionLock(DistributedSessionLock):
    """PostgreSQL Advisory Lock based distributed session exclusion (pg_try_advisory_lock).

    Maintains a dedicated database connection while held so that if the process terminates
    unexpectedly, PostgreSQL automatically frees the lock.
    """

    def __init__(self, manager=None) -> None:
        self._manager = manager
        self._held_connections: dict[tuple[str, str], tuple[Any, int]] = {}
        self._key_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()

    @property
    def _is_available(self) -> bool:
        from app.core.database import db_manager

        mgr = self._manager or db_manager
        return bool(mgr and getattr(mgr, "postgres_engine", None))

    async def acquire(
        self,
        principal_id: str,
        session_id: str,
        timeout_seconds: float = 10.0,
    ) -> bool:
        from app.core.database import db_manager

        mgr = self._manager or db_manager
        if not self._is_available:
            return False

        key = (principal_id.strip(), session_id.strip())
        async with self._state_lock:
            key_lock = self._key_locks.setdefault(key, asyncio.Lock())
        deadline = time.monotonic() + timeout_seconds
        try:
            if key_lock.locked():
                await asyncio.wait_for(key_lock.acquire(), timeout=timeout_seconds)
            else:
                await key_lock.acquire()
        except asyncio.TimeoutError:
            return False
        lock_id = derive_advisory_lock_id(principal_id, session_id)
        conn = None
        acquired = False
        lock_obtained = False
        invalidate_connection = False
        try:
            conn = await mgr.postgres_engine.connect()
            while True:
                result = await conn.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id) AS locked"),
                    {"lock_id": lock_id},
                )
                row = result.mappings().first()
                if row and row["locked"]:
                    lock_obtained = True
                    # Session advisory locks survive rollback; return pooled connections transaction-free.
                    await conn.rollback()
                    async with self._state_lock:
                        self._held_connections[key] = (conn, lock_id)
                    acquired = True
                    break

                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except asyncio.CancelledError:
            # The query may have acquired a session lock even if its result was cancelled.
            invalidate_connection = True
            raise
        except Exception as exc:
            logger.error("Error executing Postgres advisory lock acquire: %s", exc)
        finally:
            if not acquired:
                try:
                    if conn is not None:
                        if lock_obtained:
                            invalidate_connection = True
                        if not invalidate_connection:
                            try:
                                await conn.rollback()
                            except Exception as exc:
                                logger.warning("Error rolling back failed Postgres lock acquire: %s", exc)
                                invalidate_connection = True
                        try:
                            if invalidate_connection:
                                await conn.invalidate()
                        except Exception as exc:
                            logger.error("Error invalidating Postgres lock connection: %s", exc)
                        finally:
                            await conn.close()
                finally:
                    key_lock.release()
        return acquired

    async def release(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        key = (principal_id.strip(), session_id.strip())
        async with self._state_lock:
            entry = self._held_connections.pop(key, None)
        if entry is None:
            return

        conn, lock_id = entry
        invalidate_connection = False
        try:
            await conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            )
        except asyncio.CancelledError:
            invalidate_connection = True
            raise
        except Exception as exc:
            invalidate_connection = True
            logger.warning("Error releasing Postgres advisory lock %d: %s", lock_id, exc)
        finally:
            try:
                if not invalidate_connection:
                    await conn.rollback()
            except Exception as exc:
                invalidate_connection = True
                logger.warning("Error rolling back Postgres lock connection: %s", exc)
            try:
                if invalidate_connection:
                    await conn.invalidate()
            except Exception as exc:
                logger.error("Error invalidating Postgres lock connection: %s", exc)
            finally:
                try:
                    await conn.close()
                finally:
                    key_lock = self._key_locks.get(key)
                    if key_lock and key_lock.locked():
                        key_lock.release()


class RedisDistributedSessionLock(DistributedSessionLock):
    """Bounded Redis SET NX PX lease without renewal; unsuitable for long-running tasks."""

    RELEASE_LUA = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_client=None, ttl_seconds: int = 60) -> None:
        self._redis_client = redis_client
        self._ttl_ms = int(ttl_seconds * 1000)
        self._tokens: dict[tuple[str, str], str] = {}
        self._acquiring: set[tuple[str, str]] = set()
        self._state_lock = asyncio.Lock()

    @property
    def _client(self):
        if self._redis_client is not None:
            return self._redis_client
        from app.core.database import db_manager

        return getattr(db_manager, "redis_client", None)

    async def acquire(
        self,
        principal_id: str,
        session_id: str,
        timeout_seconds: float = 10.0,
    ) -> bool:
        client = self._client
        if client is None:
            return False

        key = (principal_id.strip(), session_id.strip())
        async with self._state_lock:
            if key in self._tokens or key in self._acquiring:
                return False
            self._acquiring.add(key)
        redis_key = f"geoai:session_lock:{key[0]}:{key[1]}"
        token = str(uuid4())
        deadline = time.monotonic() + timeout_seconds

        try:
            while True:
                ok = await client.set(redis_key, token, px=self._ttl_ms, nx=True)
                if ok:
                    try:
                        async with self._state_lock:
                            self._tokens[key] = token
                    except BaseException:
                        try:
                            await client.eval(self.RELEASE_LUA, 1, redis_key, token)
                        except Exception:
                            logger.exception("Failed to clean up cancelled Redis lock acquisition")
                        raise
                    return True
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.05)
            return False
        except Exception as exc:
            logger.error("Error executing Redis session lock acquire: %s", exc)
            return False
        finally:
            async with self._state_lock:
                self._acquiring.discard(key)

    async def release(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        client = self._client
        key = (principal_id.strip(), session_id.strip())
        async with self._state_lock:
            token = self._tokens.pop(key, None)
        if token is None or client is None:
            return

        redis_key = f"geoai:session_lock:{key[0]}:{key[1]}"
        try:
            await client.eval(self.RELEASE_LUA, 1, redis_key, token)
        except Exception as exc:
            logger.warning("Error releasing Redis session lock '%s': %s", redis_key, exc)


class AutoSelectingSessionLock(DistributedSessionLock):
    """Automatically selects PostgreSQL Advisory Lock -> Redis Lock -> Local Lock."""

    def __init__(
        self,
        postgres_lock: Optional[PostgresAdvisorySessionLock] = None,
        redis_lock: Optional[RedisDistributedSessionLock] = None,
        local_lock: Optional[LocalAsyncioSessionLock] = None,
    ) -> None:
        self._pg = postgres_lock or PostgresAdvisorySessionLock()
        self._redis = redis_lock or RedisDistributedSessionLock()
        self._local = local_lock or LocalAsyncioSessionLock()
        self._active_provider: dict[tuple[str, str], DistributedSessionLock] = {}
        self._acquiring: set[tuple[str, str]] = set()
        self._state_lock = asyncio.Lock()

    async def acquire(
        self,
        principal_id: str,
        session_id: str,
        timeout_seconds: float = 10.0,
    ) -> bool:
        key = (principal_id.strip(), session_id.strip())
        async with self._state_lock:
            if key in self._active_provider or key in self._acquiring:
                return False
            self._acquiring.add(key)
        provider = None
        try:
            try:
                if self._pg._is_available:
                    provider = self._pg
                elif self._redis._client is not None:
                    provider = self._redis
                else:
                    provider = self._local
            except Exception as exc:
                logger.error("Unable to inspect configured session lock providers: %s", exc)
                return False

            try:
                acquired = await provider.acquire(principal_id, session_id, timeout_seconds)
            except Exception as exc:
                logger.error("Configured session lock provider failed: %s", exc)
                return False
            if acquired:
                try:
                    async with self._state_lock:
                        self._active_provider[key] = provider
                except BaseException:
                    await provider.release(principal_id, session_id)
                    raise
            return acquired
        finally:
            async with self._state_lock:
                self._acquiring.discard(key)

    async def release(
        self,
        principal_id: str,
        session_id: str,
    ) -> None:
        key = (principal_id.strip(), session_id.strip())
        async with self._state_lock:
            provider = self._active_provider.pop(key, None)
        if provider is not None:
            await provider.release(principal_id, session_id)



_default_lock: Optional[DistributedSessionLock] = None


def get_session_lock() -> DistributedSessionLock:
    """Singleton getter for the system distributed session lock."""
    global _default_lock
    if _default_lock is None:
        _default_lock = AutoSelectingSessionLock()
    return _default_lock
