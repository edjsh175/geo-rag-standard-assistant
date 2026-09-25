from __future__ import annotations

from app.services.agent.context import AgentContextBuilder
from app.services.agent.events import AgentEvent


def test_context_builder_uses_budget_without_fixed_last_n_turn_rule() -> None:
    builder = AgentContextBuilder(max_characters=120)
    events = tuple(
        AgentEvent(
            event_type="user_message",
            session_id="session-1",
            turn_id=f"turn-{index}",
            payload={"text": f"第{index}轮-" + ("内容" * 12)},
        )
        for index in range(1, 10)
    )

    context = builder.build(
        question="当前问题",
        prior_events=events,
        working_evidence=(),
    )

    assert len(context.summary) <= 120
    assert "当前问题" in context.current_question
    assert "第9轮" in context.summary
    source = (AgentContextBuilder.__doc__ or "") + builder.__class__.__name__
    assert "history[-6:]" not in source


def test_context_keeps_evidence_structured_outside_conversation_summary() -> None:
    builder = AgentContextBuilder(max_characters=200)
    context = builder.build(
        question="问题",
        prior_events=(),
        working_evidence=(
            {"evidence_id": "ev-1", "citation_id": "E1", "title": "标准"},
        ),
    )

    assert "ev-1" not in context.summary
    assert context.working_evidence[0]["evidence_id"] == "ev-1"
