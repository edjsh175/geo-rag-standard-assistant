import pytest

import app.core.database as database


class FakeConnection:
    async def execute(self, statement):
        return None


class FakeBegin:
    async def __aenter__(self):
        return FakeConnection()

    async def __aexit__(self, *exc):
        return False


class FakeEngine:
    def __init__(self, options):
        self.options = options
        self.dispose_calls = 0

    def begin(self):
        return FakeBegin()

    async def dispose(self):
        self.dispose_calls += 1


@pytest.mark.asyncio
async def test_postgres_lock_pool_is_separate_and_bounded(monkeypatch):
    created = []

    def fake_create_async_engine(url, **options):
        engine = FakeEngine(options)
        created.append((url, engine))
        return engine

    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)
    manager = database.DatabaseManager()

    await manager._init_postgres()

    assert manager.postgres_engine is created[0][1]
    assert manager.postgres_lock_engine is created[1][1]
    assert manager.postgres_lock_engine is not manager.postgres_engine
    assert manager.postgres_lock_engine.options["pool_size"] > 0
    assert manager.postgres_lock_engine.options["max_overflow"] >= 0
    assert (
        manager.postgres_lock_engine.options["pool_size"]
        + manager.postgres_lock_engine.options["max_overflow"]
        < manager.postgres_engine.options["pool_size"]
        + manager.postgres_engine.options["max_overflow"]
    )


@pytest.mark.asyncio
async def test_database_close_disposes_postgres_lock_pool(monkeypatch):
    created = []

    def fake_create_async_engine(url, **options):
        engine = FakeEngine(options)
        created.append(engine)
        return engine

    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)
    manager = database.DatabaseManager()
    await manager._init_postgres()

    await manager.close()

    assert all(engine.dispose_calls == 1 for engine in created)


def test_search_runtime_uses_dedicated_postgres_lock_pool(monkeypatch):
    from app.api import search_routes

    lock_engine = object()
    monkeypatch.setattr(search_routes.db_manager, "postgres_lock_engine", lock_engine, raising=False)

    class SearchServiceStub:
        def get_retrieval_port(self):
            return object()

    application = search_routes._build_search_application_service(
        search_service=SearchServiceStub(),
        asset_service=object(),
        contract_service=object(),
        document_repository=object(),
    )

    session_lock = application.agent_runtime.session_lock

    assert session_lock._manager.postgres_engine is lock_engine
    assert session_lock._manager is not search_routes.db_manager
