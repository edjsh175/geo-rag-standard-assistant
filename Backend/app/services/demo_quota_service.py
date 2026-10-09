"""
Visitor demo quota tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from app.core.config import settings
from app.core.database import db_manager


class DemoQuotaStatus(BaseModel):
    remaining: int
    daily_limit: int
    global_remaining: int
    reset_at: str
    exhausted: bool
    contact_text: str


@dataclass(frozen=True)
class DemoQuotaDecision:
    allowed: bool
    quota: DemoQuotaStatus
    reason: Optional[str] = None


_LUA_CONSUME_QUOTA_SCRIPT = """
local visitor_key = KEYS[1]
local ip_key = KEYS[2]
local global_key = KEYS[3]

local visitor_limit = tonumber(ARGV[1])
local ip_limit = tonumber(ARGV[2])
local global_limit = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local visitor_count = tonumber(redis.call('get', visitor_key) or '0')
local ip_count = tonumber(redis.call('get', ip_key) or '0')
local global_count = tonumber(redis.call('get', global_key) or '0')

if visitor_count >= visitor_limit then
    return {0, visitor_count, ip_count, global_count, "visitor_quota_exhausted"}
end
if ip_count >= ip_limit then
    return {0, visitor_count, ip_count, global_count, "visitor_quota_exhausted"}
end
if global_count >= global_limit then
    return {0, visitor_count, ip_count, global_count, "global_quota_exhausted"}
end

local new_visitor = redis.call('incr', visitor_key)
local new_ip = redis.call('incr', ip_key)
local new_global = redis.call('incr', global_key)

if ttl > 0 then
    redis.call('expire', visitor_key, ttl)
    redis.call('expire', ip_key, ttl)
    redis.call('expire', global_key, ttl)
end

return {1, new_visitor, new_ip, new_global, "allowed"}
"""


class DemoQuotaService:
    """Use Redis counters to bound public demo AI generation cost."""

    def __init__(
        self,
        redis_client=None,
        now_func: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.redis_client = redis_client if redis_client is not None else db_manager.redis_client
        self.now_func = now_func or (lambda: datetime.now(timezone.utc))

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(settings.DEMO_QUOTA_TIMEZONE)
        except ZoneInfoNotFoundError:
            return ZoneInfo("Asia/Shanghai")

    def _now_local(self) -> datetime:
        now = self.now_func()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(self._timezone())

    def _quota_window(self) -> tuple[str, str, int]:
        now = self._now_local()
        window = now.strftime("%Y%m%d")
        reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl = max(1, int((reset - now).total_seconds()))
        return window, reset.isoformat(), ttl

    def _keys(self, visitor_id: str, ip_hash: str) -> tuple[str, str, str]:
        window, _, _ = self._quota_window()
        prefix = f"demo:ai:{window}"
        return (
            f"{prefix}:visitor:{visitor_id}",
            f"{prefix}:ip:{ip_hash}",
            f"{prefix}:global",
        )

    def _unavailable_status(self) -> DemoQuotaStatus:
        _, reset_at, _ = self._quota_window()
        return DemoQuotaStatus(
            remaining=0,
            daily_limit=settings.DEMO_DAILY_AI_QUOTA_PER_VISITOR,
            global_remaining=0,
            reset_at=reset_at,
            exhausted=True,
            contact_text=settings.DEMO_CONTACT_TEXT,
        )

    async def _read_count(self, key: str) -> int:
        if not self.redis_client:
            return 0
        value = await self.redis_client.get(key)
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def get_status(self, visitor_id: str, ip_hash: str) -> DemoQuotaStatus:
        if not self.redis_client:
            return self._unavailable_status()

        try:
            visitor_key, ip_key, global_key = self._keys(visitor_id, ip_hash)
            visitor_count = await self._read_count(visitor_key)
            ip_count = await self._read_count(ip_key)
            global_count = await self._read_count(global_key)
        except Exception:
            return self._unavailable_status()

        per_visitor_remaining = max(0, settings.DEMO_DAILY_AI_QUOTA_PER_VISITOR - visitor_count)
        per_ip_remaining = max(0, settings.DEMO_DAILY_AI_QUOTA_PER_IP - ip_count)
        global_remaining = max(0, settings.DEMO_GLOBAL_DAILY_AI_QUOTA - global_count)
        remaining = min(per_visitor_remaining, per_ip_remaining, global_remaining)
        _, reset_at, _ = self._quota_window()

        return DemoQuotaStatus(
            remaining=remaining,
            daily_limit=settings.DEMO_DAILY_AI_QUOTA_PER_VISITOR,
            global_remaining=global_remaining,
            reset_at=reset_at,
            exhausted=remaining <= 0,
            contact_text=settings.DEMO_CONTACT_TEXT,
        )

    async def consume_generation(self, visitor_id: str, ip_hash: str) -> DemoQuotaDecision:
        if not self.redis_client:
            return DemoQuotaDecision(
                allowed=False,
                quota=self._unavailable_status(),
                reason="quota_store_unavailable",
            )

        try:
            visitor_key, ip_key, global_key = self._keys(visitor_id, ip_hash)
            _, reset_at, ttl = self._quota_window()

            if hasattr(self.redis_client, "eval"):
                # Atomic Lua evaluation to eliminate Check-Then-Act race condition
                res = await self.redis_client.eval(
                    _LUA_CONSUME_QUOTA_SCRIPT,
                    3,
                    visitor_key,
                    ip_key,
                    global_key,
                    str(settings.DEMO_DAILY_AI_QUOTA_PER_VISITOR),
                    str(settings.DEMO_DAILY_AI_QUOTA_PER_IP),
                    str(settings.DEMO_GLOBAL_DAILY_AI_QUOTA),
                    str(ttl),
                )
                allowed_flag = bool(res[0])
                visitor_count = int(res[1])
                ip_count = int(res[2])
                global_count = int(res[3])
                reason = str(res[4]) if not allowed_flag else None

                per_visitor_remaining = max(0, settings.DEMO_DAILY_AI_QUOTA_PER_VISITOR - visitor_count)
                per_ip_remaining = max(0, settings.DEMO_DAILY_AI_QUOTA_PER_IP - ip_count)
                global_remaining = max(0, settings.DEMO_GLOBAL_DAILY_AI_QUOTA - global_count)
                remaining = min(per_visitor_remaining, per_ip_remaining, global_remaining)

                quota_status = DemoQuotaStatus(
                    remaining=remaining,
                    daily_limit=settings.DEMO_DAILY_AI_QUOTA_PER_VISITOR,
                    global_remaining=global_remaining,
                    reset_at=reset_at,
                    exhausted=remaining <= 0,
                    contact_text=settings.DEMO_CONTACT_TEXT,
                )
                return DemoQuotaDecision(
                    allowed=allowed_flag,
                    quota=quota_status,
                    reason=reason,
                )
            else:
                # Fallback for simple mocks lacking eval support
                status = await self.get_status(visitor_id, ip_hash)
                if status.exhausted:
                    return DemoQuotaDecision(
                        allowed=False,
                        quota=status,
                        reason="visitor_quota_exhausted",
                    )
                for key in (visitor_key, ip_key, global_key):
                    await self.redis_client.incr(key)
                    await self.redis_client.expire(key, ttl)
                return DemoQuotaDecision(
                    allowed=True,
                    quota=await self.get_status(visitor_id, ip_hash),
                )
        except Exception:
            return DemoQuotaDecision(
                allowed=False,
                quota=self._unavailable_status(),
                reason="quota_store_unavailable",
            )


def get_demo_quota_service() -> DemoQuotaService:
    return DemoQuotaService()
