from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.services.demo_quota_service import DemoQuotaService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str):
        value = self.values.get(key)
        return None if value is None else str(value)

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


def fixed_now() -> datetime:
    return datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_consume_generation_tracks_visitor_ip_and_global_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_VISITOR", 2)
    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_IP", 3)
    monkeypatch.setattr(settings, "DEMO_GLOBAL_DAILY_AI_QUOTA", 5)
    monkeypatch.setattr(settings, "DEMO_CONTACT_TEXT", "请联系项目作者。")

    redis = FakeRedis()
    service = DemoQuotaService(redis_client=redis, now_func=fixed_now)

    first = await service.consume_generation("visitor-a", "ip-a")
    second = await service.consume_generation("visitor-a", "ip-a")
    third = await service.consume_generation("visitor-a", "ip-a")

    assert first.allowed is True
    assert first.quota.remaining == 1
    assert second.allowed is True
    assert second.quota.remaining == 0
    assert third.allowed is False
    assert third.quota.exhausted is True
    assert third.quota.contact_text == "请联系项目作者。"


@pytest.mark.asyncio
async def test_global_quota_blocks_new_visitors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_VISITOR", 10)
    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_IP", 10)
    monkeypatch.setattr(settings, "DEMO_GLOBAL_DAILY_AI_QUOTA", 1)

    service = DemoQuotaService(redis_client=FakeRedis(), now_func=fixed_now)

    allowed = await service.consume_generation("visitor-a", "ip-a")
    blocked = await service.consume_generation("visitor-b", "ip-b")

    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.quota.global_remaining == 0


@pytest.mark.asyncio
async def test_missing_redis_disables_visitor_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_VISITOR", 10)
    monkeypatch.setattr(settings, "DEMO_GLOBAL_DAILY_AI_QUOTA", 300)
    monkeypatch.setattr(settings, "DEMO_CONTACT_TEXT", "请联系项目作者。")

    service = DemoQuotaService(redis_client=None, now_func=fixed_now)

    decision = await service.consume_generation("visitor-a", "ip-a")

    assert decision.allowed is False
    assert decision.quota.exhausted is True
    assert decision.quota.remaining == 0
    assert decision.reason == "quota_store_unavailable"
