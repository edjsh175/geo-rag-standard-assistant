"""Unit tests for Reviewer repair loop (REVISE -> Repair Scope -> V2 -> Reviewer #2 -> Fail-Close)."""

from __future__ import annotations

from datetime import datetime
import pytest

from app.models.search_models import DocumentResult
from app.services.agent.answer_generator import AnswerUnit, GeneratedAnswer
from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.events import AgentEvent
from app.services.agent.reviewer import (
    ReviewFinding,
    ReviewResult,
    build_answer_repair_scope,
    validate_answer_repair_draft,
)
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.tool_runtime import ToolCall
from app.services.agent.contracts import EvidenceItem, FrozenEvidenceSnapshot


def make_snapshot() -> FrozenEvidenceSnapshot:
    item1 = EvidenceItem(
        evidence_id="ev-1",
        citation_id="E1",
        session_id="s1",
        first_turn_id="t1",
        chunk_id="c1",
        document_id="d1",
        title="标准A",
        text="青羊区商业用地容积率上限为 4.0。",
        score=0.9,
        metadata={},
        source="postgres",
        match_type="keyword",
        content_hash="h1",
    )
    item2 = EvidenceItem(
        evidence_id="ev-2",
        citation_id="E2",
        session_id="s1",
        first_turn_id="t1",
        chunk_id="c2",
        document_id="d2",
        title="标准B",
        text="建筑限高为 60 米。",
        score=0.85,
        metadata={},
        source="postgres",
        match_type="keyword",
        content_hash="h2",
    )
    return FrozenEvidenceSnapshot(
        snapshot_id="snap-1",
        session_id="s1",
        turn_id="t1",
        items=(item1, item2),
    )


def test_build_answer_repair_scope():
    snapshot = make_snapshot()
    answer_v1 = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.0。限高是100米。",
        citations=("E1", "E2"),
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是100米。", citations=("E2",)),  # overstated/unsupported
        ),
    )
    review_1 = ReviewResult(
        verdict="OVERSTATED",
        findings=(
            ReviewFinding(unit_id="unit-1", status="SUPPORTED", citations=("E1",)),
            ReviewFinding(unit_id="unit-2", status="OVERSTATED", citations=("E2",)),
        ),
    )

    scope = build_answer_repair_scope(answer_v1, review_1, snapshot)
    assert scope["contract_version"] == "answer_repair_scope_v1"
    assert scope["immutable_units"] == ["unit-1"]
    assert len(scope["editable_units"]) == 1
    assert scope["editable_units"][0]["unit_id"] == "unit-2"
    assert "E1" in scope["editable_units"][0]["allowed_evidence_ids"]
    assert "E2" in scope["editable_units"][0]["allowed_evidence_ids"]


def test_validate_answer_repair_draft_success():
    snapshot = make_snapshot()
    answer_v1 = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.0。限高是100米。",
        citations=("E1", "E2"),
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是100米。", citations=("E2",)),
        ),
    )
    scope = {
        "immutable_units": ["unit-1"],
        "editable_units": [{"unit_id": "unit-2", "allowed_evidence_ids": ["E1", "E2"]}],
    }

    # Valid repair: unit-1 unchanged, unit-2 text corrected to 60米
    answer_v2 = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.0。限高是60米。",
        citations=("E1", "E2"),
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是60米。", citations=("E2",)),
        ),
    )
    # Should not raise
    validate_answer_repair_draft(answer_v1, answer_v2, scope)


def test_validate_answer_repair_draft_rejects_illegal_modifications():
    answer_v1 = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.0。限高是100米。",
        citations=("E1", "E2"),
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是100米。", citations=("E2",)),
        ),
    )
    scope = {
        "immutable_units": ["unit-1"],
        "editable_units": [{"unit_id": "unit-2", "allowed_evidence_ids": ["E1", "E2"]}],
    }

    # 1. Modifying immutable unit text
    bad_v2_immutable = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.5。限高是60米。",
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.5。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是60米。", citations=("E2",)),
        ),
    )
    with pytest.raises(ValueError, match="answer_repair_immutable_unit_changed"):
        validate_answer_repair_draft(answer_v1, bad_v2_immutable, scope)

    # 2. Introducing new unit
    bad_v2_new_unit = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.0。限高是60米。绿化率30%。",
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是60米。", citations=("E2",)),
            AnswerUnit(unit_id="unit-3", text="绿化率30%。", citations=("E1",)),
        ),
    )
    with pytest.raises(ValueError, match="answer_repair_new_unit_forbidden"):
        validate_answer_repair_draft(answer_v1, bad_v2_new_unit, scope)

    # 3. Changing unit order
    bad_v2_order = GeneratedAnswer(
        kind="knowledge_answer",
        answer="限高是60米。容积率是4.0。",
        units=(
            AnswerUnit(unit_id="unit-2", text="限高是60米。", citations=("E2",)),
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
        ),
    )
    with pytest.raises(ValueError, match="answer_repair_unit_order_changed"):
        validate_answer_repair_draft(answer_v1, bad_v2_order, scope)

    # 4. Unallowed citation in editable unit
    bad_v2_citation = GeneratedAnswer(
        kind="knowledge_answer",
        answer="容积率是4.0。限高是60米。",
        units=(
            AnswerUnit(unit_id="unit-1", text="容积率是4.0。", citations=("E1",)),
            AnswerUnit(unit_id="unit-2", text="限高是60米。", citations=("E99",)),
        ),
    )
    with pytest.raises(ValueError, match="answer_repair_new_evidence_forbidden"):
        validate_answer_repair_draft(answer_v1, bad_v2_citation, scope)


@pytest.mark.asyncio
async def test_runtime_reviewer_repair_loop_success():
    """Verify Reviewer #1 REVISE -> Answer V2 -> Reviewer #2 PASS -> Published."""
    snapshot = make_snapshot()

    class FakeController:
        async def decide(self, **kwargs):
            return ToolCall(
                tool_call_id="c1",
                name="compose_answer",
                arguments={"selected_evidence_ids": ["ev-1", "ev-2"]},
            )

    class FakeAnswerGeneratorWithRepair:
        def __init__(self):
            self.repair_called = False

        async def generate(self, **kwargs):
            return GeneratedAnswer(
                kind="knowledge_answer",
                answer="容积率4.0。限高100米。",
                citations=("E1", "E2"),
                units=(
                    AnswerUnit(unit_id="unit-1", text="容积率4.0。", citations=("E1",)),
                    AnswerUnit(unit_id="unit-2", text="限高100米。", citations=("E2",)),
                ),
            )

        async def generate_repair(self, **kwargs):
            self.repair_called = True
            return GeneratedAnswer(
                kind="knowledge_answer",
                answer="容积率4.0。限高60米。",
                citations=("E1", "E2"),
                units=(
                    AnswerUnit(unit_id="unit-1", text="容积率4.0。", citations=("E1",)),
                    AnswerUnit(unit_id="unit-2", text="限高60米。", citations=("E2",)),
                ),
            )

    class FakeTwoPhaseReviewer:
        def __init__(self):
            self.attempts = 0

        async def review(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                # Reviewer #1 rejects with OVERSTATED
                return ReviewResult(
                    verdict="OVERSTATED",
                    findings=(
                        ReviewFinding(unit_id="unit-1", status="SUPPORTED", citations=("E1",)),
                        ReviewFinding(unit_id="unit-2", status="OVERSTATED", citations=("E2",)),
                    ),
                )
            # Reviewer #2 passes V2
            return ReviewResult(
                verdict="SUPPORTED",
                findings=(
                    ReviewFinding(unit_id="unit-1", status="SUPPORTED", citations=("E1",)),
                    ReviewFinding(unit_id="unit-2", status="SUPPORTED", citations=("E2",)),
                ),
            )

    ans_gen = FakeAnswerGeneratorWithRepair()
    rev = FakeTwoPhaseReviewer()

    class FakePort:
        pass

    runtime = AgentRuntime(
        retrieval_port=FakePort(),
        controller=FakeController(),
        answer_generator=ans_gen,
        reviewer=rev,
        session_store=InMemoryAgentSessionStore(),
    )

    session = runtime.session_store.get_or_create(principal_id="u1", session_id="s1")
    for item in snapshot.items:
        session.evidence_ledger._items[item.evidence_id] = item
    session.evidence_ledger._working_by_turn["turn-1"] = [item.evidence_id for item in snapshot.items]

    result = await runtime.run(
        AgentRunRequest(
            question="规划指标要求？",
            session_id="s1",
            principal_id="u1",
            reviewer_enabled=True,
        )
    )

    assert ans_gen.repair_called is True
    assert rev.attempts == 2
    assert result.publication_state == "published"
    assert result.answer.answer == "容积率4.0。限高60米。"
    event_types = [ev.event_type for ev in result.events]
    assert "answer_repair_scope_created" in event_types


@pytest.mark.asyncio
async def test_runtime_reviewer_repair_loop_second_failure_fail_closes():
    """Verify Reviewer #2 REVISE -> fail-close with review_rejected."""
    snapshot = make_snapshot()

    class FakeController:
        async def decide(self, **kwargs):
            return ToolCall(
                tool_call_id="c1",
                name="compose_answer",
                arguments={"selected_evidence_ids": ["ev-1", "ev-2"]},
            )

    class FakeAnswerGeneratorWithRepair:
        async def generate(self, **kwargs):
            return GeneratedAnswer(
                kind="knowledge_answer",
                answer="容积率4.0。限高100米。",
                citations=("E1", "E2"),
                units=(
                    AnswerUnit(unit_id="unit-1", text="容积率4.0。", citations=("E1",)),
                    AnswerUnit(unit_id="unit-2", text="限高100米。", citations=("E2",)),
                ),
            )

        async def generate_repair(self, **kwargs):
            return GeneratedAnswer(
                kind="knowledge_answer",
                answer="容积率4.0。限高70米。",
                citations=("E1", "E2"),
                units=(
                    AnswerUnit(unit_id="unit-1", text="容积率4.0。", citations=("E1",)),
                    AnswerUnit(unit_id="unit-2", text="限高70米。", citations=("E2",)),
                ),
            )

    class AlwaysRejectReviewer:
        async def review(self, **kwargs):
            return ReviewResult(
                verdict="OVERSTATED",
                findings=(
                    ReviewFinding(unit_id="unit-1", status="SUPPORTED", citations=("E1",)),
                    ReviewFinding(unit_id="unit-2", status="OVERSTATED", citations=("E2",)),
                ),
            )

    runtime = AgentRuntime(
        retrieval_port=None,
        controller=FakeController(),
        answer_generator=FakeAnswerGeneratorWithRepair(),
        reviewer=AlwaysRejectReviewer(),
        session_store=InMemoryAgentSessionStore(),
    )

    session = runtime.session_store.get_or_create(principal_id="u1", session_id="s2")
    for item in snapshot.items:
        session.evidence_ledger._items[item.evidence_id] = item
    session.evidence_ledger._working_by_turn["turn-1"] = [item.evidence_id for item in snapshot.items]

    result = await runtime.run(
        AgentRunRequest(
            question="规划指标要求？",
            session_id="s2",
            principal_id="u1",
            reviewer_enabled=True,
        )
    )

    assert result.publication_state == "review_rejected"
    assert result.answer is None
    assert "未通过证据审查" in (result.limitation or "")
