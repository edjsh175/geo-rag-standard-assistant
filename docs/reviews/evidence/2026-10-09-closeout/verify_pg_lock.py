import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "Backend").is_dir())
sys.path.insert(0, str(ROOT / "Backend"))
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings
from app.services.agent.distributed_lock import PostgresAdvisorySessionLock

async def main():
    business = create_async_engine(settings.DATABASE_URL, pool_size=1, max_overflow=0, pool_timeout=1)
    lock_engine = create_async_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0, pool_timeout=1)
    manager = SimpleNamespace(postgres_engine=lock_engine)
    first, second = PostgresAdvisorySessionLock(manager), PostgresAdvisorySessionLock(manager)
    key = "closeout-" + uuid4().hex
    checks = {}
    try:
        assert await first.acquire("closeout", key, timeout_seconds=1)
        async with business.connect() as conn:
            checks["business_query_while_locked"] = (await conn.execute(text("SELECT 1"))).scalar() == 1
        checks["cross_instance_contention_rejected"] = not await second.acquire("closeout", key, timeout_seconds=0.1)
        waiter = asyncio.create_task(second.acquire("closeout", key, timeout_seconds=10))
        await asyncio.sleep(0.1)
        waiter.cancel()
        try:
            await waiter
        except asyncio.CancelledError:
            checks["waiter_cancellation_propagated"] = True
        await first.release("closeout", key)
        checks["reacquire_after_release_and_cancel"] = await second.acquire("closeout", key, timeout_seconds=1)
        await second.release("closeout", key)
        checks["no_lock_connection_leaked"] = lock_engine.pool.checkedout() == 0
        assert all(checks.values()), checks
        print(json.dumps({"passed": True, "checks": checks}, indent=2))
    finally:
        await first.release("closeout", key)
        await second.release("closeout", key)
        await lock_engine.dispose()
        await business.dispose()

asyncio.run(main())
