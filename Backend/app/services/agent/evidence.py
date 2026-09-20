"""Deterministic evidence lifecycle for Agent retrieval results."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable, Sequence
from uuid import NAMESPACE_URL, uuid5

from app.services.agent.contracts import EvidenceItem, FrozenEvidenceSnapshot
from app.services.rag.contracts import RetrievalCandidate


class EvidenceLedger:
    """Session-scoped evidence memory with explicit per-turn activation.

    Retrieval candidates become immutable evidence records through deterministic
    structural admission. Historical records stay searchable, but only evidence
    explicitly active in the current turn may enter a frozen citation snapshot.
    """

    def __init__(self, *, session_id: str) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        self.session_id = session_id
        self._items: dict[str, EvidenceItem] = {}
        self._working_by_turn: dict[str, list[str]] = {}
        self._seen_turns: dict[str, set[str]] = {}
        self._next_citation_ordinal = 1

    def add_candidates(
        self,
        *,
        turn_id: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> list[EvidenceItem]:
        self._require_turn_id(turn_id)
        admitted: list[EvidenceItem] = []
        for candidate in candidates:
            if not self._is_structurally_admissible(candidate):
                continue
            item = self._get_or_create_item(turn_id=turn_id, candidate=candidate)
            self._activate(turn_id=turn_id, evidence_id=item.evidence_id)
            admitted.append(item)
        return admitted

    def activate_existing(
        self,
        *,
        turn_id: str,
        evidence_ids: Sequence[str],
    ) -> tuple[EvidenceItem, ...]:
        self._require_turn_id(turn_id)
        activated: list[EvidenceItem] = []
        for evidence_id in self._dedupe(evidence_ids):
            item = self._items.get(evidence_id)
            if item is None:
                raise KeyError(f"unknown evidence_id: {evidence_id}")
            self._activate(turn_id=turn_id, evidence_id=evidence_id)
            activated.append(item)
        return tuple(activated)

    def working_evidence(self, *, turn_id: str) -> tuple[EvidenceItem, ...]:
        evidence_ids = self._working_by_turn.get(turn_id, [])
        return tuple(self._items[evidence_id] for evidence_id in evidence_ids)

    def freeze(
        self,
        *,
        turn_id: str,
        evidence_ids: Sequence[str],
    ) -> FrozenEvidenceSnapshot:
        self._require_turn_id(turn_id)
        selected_ids = self._dedupe(evidence_ids)
        working_ids = set(self._working_by_turn.get(turn_id, []))
        unavailable = [evidence_id for evidence_id in selected_ids if evidence_id not in working_ids]
        if unavailable:
            raise ValueError(
                "frozen evidence must come from current working evidence: "
                + ", ".join(unavailable)
            )

        items = tuple(self._items[evidence_id] for evidence_id in selected_ids)
        snapshot_identity = json.dumps(
            [self.session_id, turn_id, selected_ids],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return FrozenEvidenceSnapshot(
            snapshot_id=str(uuid5(NAMESPACE_URL, snapshot_identity)),
            session_id=self.session_id,
            turn_id=turn_id,
            items=items,
        )

    def search_memory(
        self,
        *,
        query: str,
        exclude_turn_id: str | None = None,
        limit: int = 8,
    ) -> tuple[EvidenceItem, ...]:
        normalized_query = self._normalize_text(query)
        if not normalized_query or limit <= 0:
            return ()

        excluded_ids = set(self._working_by_turn.get(exclude_turn_id or "", []))
        terms = self._query_terms(normalized_query)
        scored: list[tuple[int, int, EvidenceItem]] = []
        for item in self._items.values():
            if item.evidence_id in excluded_ids:
                continue
            haystack = self._normalize_text(
                " ".join(
                    [
                        item.title,
                        item.text,
                        json.dumps(dict(item.metadata), ensure_ascii=False, default=str),
                    ]
                )
            )
            score = self._memory_score(normalized_query, terms, haystack)
            if score <= 0:
                continue
            ordinal = self._citation_ordinal(item.citation_id)
            scored.append((score, ordinal, item))

        scored.sort(key=lambda row: (-row[0], row[1]))
        return tuple(row[2] for row in scored[:limit])

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return self._items.get(evidence_id)

    def _get_or_create_item(
        self,
        *,
        turn_id: str,
        candidate: RetrievalCandidate,
    ) -> EvidenceItem:
        text = candidate.text.strip()
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        identity = json.dumps(
            [
                self.session_id,
                candidate.provenance.source,
                candidate.chunk_id,
                content_hash,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        evidence_id = str(uuid5(NAMESPACE_URL, identity))
        existing = self._items.get(evidence_id)
        if existing is not None:
            return existing

        citation_id = f"E{self._next_citation_ordinal}"
        self._next_citation_ordinal += 1
        item = EvidenceItem(
            evidence_id=evidence_id,
            citation_id=citation_id,
            session_id=self.session_id,
            first_turn_id=turn_id,
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            text=text,
            title=candidate.title,
            score=float(candidate.score),
            metadata=dict(candidate.metadata),
            source=candidate.provenance.source,
            match_type=candidate.provenance.match_type,
            content_hash=content_hash,
        )
        self._items[evidence_id] = item
        return item

    def _activate(self, *, turn_id: str, evidence_id: str) -> None:
        working = self._working_by_turn.setdefault(turn_id, [])
        if evidence_id not in working:
            working.append(evidence_id)
        self._seen_turns.setdefault(evidence_id, set()).add(turn_id)

    @staticmethod
    def _is_structurally_admissible(candidate: RetrievalCandidate) -> bool:
        return bool(candidate.chunk_id.strip() and candidate.text.strip())

    @staticmethod
    def _dedupe(values: Iterable[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", "", value or "").lower()

    @staticmethod
    def _query_terms(normalized_query: str) -> tuple[str, ...]:
        latin_terms = re.findall(r"[a-z0-9_]{2,}", normalized_query)
        chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,}", normalized_query)
        return tuple(dict.fromkeys([*latin_terms, *chinese_terms]))

    @staticmethod
    def _memory_score(query: str, terms: Sequence[str], haystack: str) -> int:
        score = 10 if query in haystack else 0
        score += sum(2 for term in terms if term in haystack)
        return score

    @staticmethod
    def _citation_ordinal(citation_id: str) -> int:
        try:
            return int(citation_id.removeprefix("E"))
        except ValueError:
            return 10**9

    @staticmethod
    def _require_turn_id(turn_id: str) -> None:
        if not turn_id.strip():
            raise ValueError("turn_id must not be empty")
