from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.agent.answer_generator import AnswerUnit, GeneratedAnswer
from app.services.agent.contracts import EvidenceItem
from app.services.agent.runtime import AgentRunRequest, AgentRuntime
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.tool_runtime import ToolCall


@pytest.mark.asyncio
async def test_review_repair_emits_two_distinct_correlated_lifecycles() -> None:
    class Controller:
        async def decide(self, **kwargs):
            return ToolCall("compose-1", "compose_answer", {"evidence_ids": ["ev-1", "ev-2"]})

    class Answerer:
        async def generate(self, **kwargs):
            return GeneratedAnswer(
                kind="knowledge_answer", answer="上限100米。", citations=("E1",),
                units=(AnswerUnit(unit_id="unit-1", text="上限100米。", citations=("E1",)),),
            )

        async def generate_repair(self, **kwargs):
            return GeneratedAnswer(
                kind="knowledge_answer", answer="上限60米。", citations=("E1",),
                units=(AnswerUnit(unit_id="unit-1", text="上限60米。", citations=("E1",)),),
            )

    class Reviewer:
        def __init__(self):
            self.calls = 0

        async def review(self, **kwargs):
            self.calls += 1
            verdict = "OVERSTATED" if self.calls == 1 else "SUPPORTED"
            finding = SimpleNamespace(
                unit_id="unit-1", status=verdict, citations=("E1",),
                issue="overstated" if self.calls == 1 else None,
            )
            return SimpleNamespace(verdict=verdict, findings=(finding,))

    store = InMemoryAgentSessionStore()
    reviewer = Reviewer()
    runtime = AgentRuntime(
        retrieval_port=None, controller=Controller(), answer_generator=Answerer(),
        reviewer=reviewer, session_store=store,
    )
    session = store.get_or_create("admin:test", "review-repair")
    for n, text in ((1, "建筑限高60米。"), (2, "相关规划依据。")):
        item = EvidenceItem(
            evidence_id=f"ev-{n}", citation_id=f"E{n}", session_id="review-repair",
            first_turn_id="turn-1", chunk_id=f"c{n}", document_id=f"d{n}",
            title=f"依据{n}", text=text, score=0.9, metadata={}, source="postgres",
            match_type="keyword", content_hash=f"h{n}",
        )
        session.evidence_ledger._items[item.evidence_id] = item
    session.evidence_ledger._working_by_turn["turn-1"] = ["ev-1", "ev-2"]

    result = await runtime.run(AgentRunRequest(
        question="规划限高是多少？", session_id="review-repair", principal_id="admin:test",
        reviewer_enabled=True,
    ))
    starts = [event for event in result.events if event.event_type == "review_started"]
    completes = [event for event in result.events if event.event_type == "review_completed"]
    assert reviewer.calls == 2
    assert [event.payload["attempt"] for event in starts] == [1, 2]
    assert [event.payload["attempt"] for event in completes] == [1, 2]
    assert starts[0].payload["review_id"] == completes[0].payload["review_id"]
    assert starts[1].payload["review_id"] == completes[1].payload["review_id"]
    assert starts[0].payload["review_id"] != starts[1].payload["review_id"]
    assert [event.payload["verdict"] for event in completes] == ["OVERSTATED", "SUPPORTED"]
    assert result.publication_state == "published"
