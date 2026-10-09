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

    async def eval(self, script: str, numkeys: int, *args):
        # Emulate atomic Redis Lua script execution
        keys = args[:numkeys]
        argv = args[numkeys:]
        visitor_key, ip_key, global_key = keys[0], keys[1], keys[2]
        visitor_limit = int(argv[0])
        ip_limit = int(argv[1])
        global_limit = int(argv[2])
        ttl = int(argv[3])

        v_cnt = self.values.get(visitor_key, 0)
        ip_cnt = self.values.get(ip_key, 0)
        g_cnt = self.values.get(global_key, 0)

        if v_cnt >= visitor_limit:
            return [0, v_cnt, ip_cnt, g_cnt, "visitor_quota_exhausted"]
        if ip_cnt >= ip_limit:
            return [0, v_cnt, ip_cnt, g_cnt, "visitor_quota_exhausted"]
        if g_cnt >= global_limit:
            return [0, v_cnt, ip_cnt, g_cnt, "global_quota_exhausted"]

        self.values[visitor_key] = v_cnt + 1
        self.values[ip_key] = ip_cnt + 1
        self.values[global_key] = g_cnt + 1
        for k in (visitor_key, ip_key, global_key):
            self.expirations[k] = ttl
        return [1, self.values[visitor_key], self.values[ip_key], self.values[global_key], "allowed"]


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


@pytest.mark.asyncio
async def test_consume_generation_concurrent_race_condition_atomicity(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_VISITOR", 3)
    monkeypatch.setattr(settings, "DEMO_DAILY_AI_QUOTA_PER_IP", 10)
    monkeypatch.setattr(settings, "DEMO_GLOBAL_DAILY_AI_QUOTA", 100)

    redis = FakeRedis()
    service = DemoQuotaService(redis_client=redis, now_func=fixed_now)

    # Concurrently fire 20 requests for the same visitor
    tasks = [service.consume_generation("visitor-concurrent", "ip-concurrent") for _ in range(20)]
    results = await asyncio.gather(*tasks)

    allowed_results = [r for r in results if r.allowed]
    denied_results = [r for r in results if not r.allowed]

    # Exactly 3 allowed, exactly 17 denied
    assert len(allowed_results) == 3
    assert len(denied_results) == 17
    # Quota is strictly exhausted, count was not overrun
    assert redis.values[f"demo:ai:20260530:visitor:visitor-concurrent"] == 3
    for r in denied_results:
        assert r.quota.exhausted is True
        assert r.quota.remaining == 0

