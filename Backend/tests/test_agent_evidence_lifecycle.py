from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.agent.evidence import EvidenceLedger
from app.services.rag.contracts import RetrievalCandidate


def make_candidate(
    *,
    chunk_id: str,
    text: str,
    title: str = "规划标准",
    document_id: str | None = None,
) -> RetrievalCandidate:
    metadata = {
        "chunk_id": chunk_id,
        "document_name": title,
        "match_type": "keyword",
    }
    if document_id is not None:
        metadata["document_id"] = document_id
    result = DocumentResult(
        id=document_id or chunk_id,
        title=title,
        content=text,
        similarity=0.9,
        metadata=metadata,
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )
    return RetrievalCandidate.from_document_result(result)


def test_freeze_uses_stable_evidence_and_citation_identity() -> None:
    ledger = EvidenceLedger(session_id="session-1")
    admitted = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[make_candidate(chunk_id="chunk-1", text="重庆市滑坡监测要求")],
    )

    snapshot = ledger.freeze(
        turn_id="turn-1",
        evidence_ids=[admitted[0].evidence_id],
    )

    assert snapshot.session_id == "session-1"
    assert snapshot.turn_id == "turn-1"
    assert snapshot.items[0].evidence_id == admitted[0].evidence_id
    assert snapshot.items[0].citation_id == "E1"
    assert snapshot.items[0].chunk_id == "chunk-1"
    with pytest.raises(TypeError):
        snapshot.items[0].metadata["new"] = "mutation"  # type: ignore[index]


def test_repeated_candidate_keeps_same_identity_across_turns() -> None:
    ledger = EvidenceLedger(session_id="session-1")
    candidate = make_candidate(chunk_id="chunk-1", text="同一事实")

    first = ledger.add_candidates(turn_id="turn-1", candidates=[candidate])[0]
    second = ledger.add_candidates(turn_id="turn-2", candidates=[candidate])[0]

    assert second.evidence_id == first.evidence_id
    assert second.citation_id == first.citation_id == "E1"


def test_memory_search_does_not_automatically_reactivate_historical_evidence() -> None:
    ledger = EvidenceLedger(session_id="session-1")
    historical = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[make_candidate(chunk_id="chunk-history", text="历史滑坡监测要求")],
    )[0]

    matches = ledger.search_memory(query="滑坡监测", exclude_turn_id="turn-2")

    assert [item.evidence_id for item in matches] == [historical.evidence_id]
    with pytest.raises(ValueError, match="working evidence"):
        ledger.freeze(turn_id="turn-2", evidence_ids=[historical.evidence_id])

    ledger.activate_existing(turn_id="turn-2", evidence_ids=[historical.evidence_id])
    snapshot = ledger.freeze(turn_id="turn-2", evidence_ids=[historical.evidence_id])

    assert snapshot.items[0].evidence_id == historical.evidence_id
    assert snapshot.items[0].citation_id == "E1"


def test_structurally_empty_candidate_is_not_admitted() -> None:
    ledger = EvidenceLedger(session_id="session-1")

    admitted = ledger.add_candidates(
        turn_id="turn-1",
        candidates=[make_candidate(chunk_id="chunk-empty", text="   ")],
    )

    assert admitted == []
    assert ledger.working_evidence(turn_id="turn-1") == ()


def test_observation_can_be_admitted_and_frozen_without_kb_retrieval() -> None:
    ledger = EvidenceLedger(session_id="session-1")

    item = ledger.add_observation(
        turn_id="turn-1",
        source="browser_gis",
        observation_key="tool-call-1",
        title="Browser GIS tool receipt",
        payload={"status": "succeeded", "output": {"layer_ref": "ul_1"}},
    )

    snapshot = ledger.freeze(turn_id="turn-1", evidence_ids=[item.evidence_id])
    assert snapshot.items[0].source == "browser_gis"
    assert snapshot.items[0].match_type == "observation"
    assert '"layer_ref":"ul_1"' in snapshot.items[0].text
