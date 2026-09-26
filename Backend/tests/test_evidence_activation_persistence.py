from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.services.agent.contracts import EvidenceItem
from app.services.agent.store import InMemoryAgentStore, PostgresAgentStore


def make_item(evidence_id: str, citation_id: str, *, turn_id: str = "turn-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        citation_id=citation_id,
        session_id="session-1",
        first_turn_id=turn_id,
        chunk_id=f"chunk-{evidence_id}",
        document_id=None,
        text=f"text-{evidence_id}",
        title=f"title-{evidence_id}",
        score=1.0,
        metadata={},
        source="doc_store",
        match_type="keyword",
        content_hash=f"hash-{evidence_id}",
    )


@pytest.mark.asyncio
async def test_in_memory_store_persists_ordered_evidence_activations() -> None:
    store = InMemoryAgentStore()
    await store.save_evidence_activations(
        "user-1",
        "session-1",
        {"turn-2": ("ev-b", "ev-a")},
    )

    restored = await store.list_evidence_activations("user-1", "session-1")

    assert restored == {"turn-2": ("ev-b", "ev-a")}


class _Mappings:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def mappings(self):
        return _Mappings(self._row, self._rows)


class _SessionRowConnection:
    async def execute(self, sql, params):
        statement = str(sql)
        if "FROM geoai_agent_sessions" in statement:
            return _Result(
                row={
                    "id": "user-1:session-1",
                    "principal_id": "user-1",
                    "session_id": "session-1",
                    "workspace_id": "default",
                    "status": "active",
                    "next_turn_number": 3,
                    "metadata": {},
                }
            )
        return _Result()


class _Manager:
    def __init__(self):
        self.postgres_sessionmaker = object()
        self.connection = _SessionRowConnection()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.connection


class _ActivationConnection:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], int] = {}

    async def execute(self, sql, params):
        statement = str(sql)
        if "INSERT INTO geoai_agent_evidence_activations" in statement:
            key = (str(params["turn_id"]), str(params["evidence_id"]))
            self.rows[key] = int(params["ordinal"])
            return _Result()
        if "FROM geoai_agent_evidence_activations" in statement:
            rows = [
                {"turn_id": turn_id, "evidence_id": evidence_id, "ordinal": ordinal}
                for (turn_id, evidence_id), ordinal in sorted(
                    self.rows.items(),
                    key=lambda item: (item[0][0], item[1]),
                )
            ]
            return _Result(rows=rows)
        return _Result()


class _ActivationManager:
    def __init__(self) -> None:
        self.postgres_sessionmaker = object()
        self.connection = _ActivationConnection()

    @asynccontextmanager
    async def get_postgres_session(self):
        yield self.connection


class _RestoringStore(PostgresAgentStore):
    async def list_events(self, principal_id, session_id, from_sequence=0):
        return []

    async def list_evidence_items(self, principal_id, session_id, active_only=True):
        return [make_item("ev-a", "E1"), make_item("ev-b", "E2")]

    async def list_evidence_activations(self, principal_id, session_id):
        return {"turn-2": ("ev-b", "ev-a")}

    async def get_pending_execution(self, principal_id, session_id):
        return None


@pytest.mark.asyncio
async def test_postgres_session_restore_rehydrates_working_evidence_projection() -> None:
    store = _RestoringStore(manager=_Manager())

    session = await store.get_session("user-1", "session-1")

    assert session is not None
    assert [
        item.evidence_id
        for item in session.evidence_ledger.working_evidence(turn_id="turn-2")
    ] == ["ev-b", "ev-a"]


@pytest.mark.asyncio
async def test_postgres_activation_projection_roundtrips_in_ordinal_order() -> None:
    store = PostgresAgentStore(manager=_ActivationManager())

    await store.save_evidence_activations(
        "user-1",
        "session-1",
        {
            "turn-1": ("ev-b", "ev-a"),
            "turn-2": ("ev-c",),
        },
    )
    restored = await store.list_evidence_activations("user-1", "session-1")

    assert restored == {
        "turn-1": ("ev-b", "ev-a"),
        "turn-2": ("ev-c",),
    }
