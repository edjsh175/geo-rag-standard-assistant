"""Request-level cached health snapshot for external Agent tool providers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from time import monotonic
from types import MappingProxyType
from typing import Any, Callable, Mapping

from sqlalchemy import text

from app.core.database import db_manager

logger = logging.getLogger(__name__)

_FAIL_CLOSED_HEALTH = {
    "postgres": False,
    "kb": False,
    "postgis": False,
}


@dataclass(frozen=True, slots=True)
class ProviderHealthSnapshot:
    provider_health: Mapping[str, bool]
    captured_at_monotonic: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_health",
            MappingProxyType(dict(self.provider_health)),
        )


class ProviderHealthService:
    """Probe once per TTL window and fail closed on probe timeout/error."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 5.0,
        timeout_seconds: float = 1.0,
        clock: Callable[[], float] = monotonic,
        postgres_engine_getter: Callable[[], Any] | None = None,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self.ttl_seconds = float(ttl_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.clock = clock
        self.postgres_engine_getter = postgres_engine_getter or (
            lambda: db_manager.postgres_engine
        )
        self._cached: ProviderHealthSnapshot | None = None
        self._lock = asyncio.Lock()

    async def snapshot(self) -> ProviderHealthSnapshot:
        now = self.clock()
        cached = self._cached
        if cached is not None and now - cached.captured_at_monotonic < self.ttl_seconds:
            return cached

        async with self._lock:
            now = self.clock()
            cached = self._cached
            if cached is not None and now - cached.captured_at_monotonic < self.ttl_seconds:
                return cached
            try:
                provider_health = await asyncio.wait_for(
                    self._probe_provider_health(),
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:
                logger.warning(
                    "Provider health probe failed closed: %s",
                    type(exc).__name__,
                )
                provider_health = dict(_FAIL_CLOSED_HEALTH)

            snapshot = ProviderHealthSnapshot(
                provider_health=provider_health,
                captured_at_monotonic=self.clock(),
            )
            self._cached = snapshot
            return snapshot

    async def _probe_provider_health(self) -> Mapping[str, bool]:
        engine = self.postgres_engine_getter()
        if engine is None:
            return dict(_FAIL_CLOSED_HEALTH)

        statement = text(
            """
            SELECT
                to_regclass('public.policy_chunks') IS NOT NULL AS policy_chunks_ready,
                EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'postgis'
                ) AS postgis_ready
            """
        )
        async with engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one()

        return {
            "postgres": True,
            "kb": bool(row["policy_chunks_ready"]),
            "postgis": bool(row["postgis_ready"]),
        }


FAIL_CLOSED_PROVIDER_HEALTH: Mapping[str, bool] = MappingProxyType(
    dict(_FAIL_CLOSED_HEALTH)
)


__all__ = [
    "FAIL_CLOSED_PROVIDER_HEALTH",
    "ProviderHealthService",
    "ProviderHealthSnapshot",
]
