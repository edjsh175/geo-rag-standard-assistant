from __future__ import annotations

import pytest

from app.services.agent.publication import (
    PublicationDecision,
    PublicationStateError,
    PublishedResult,
)


def test_publication_result_is_the_single_authority_for_visible_answer() -> None:
    result = PublishedResult.publish(
        text="有证据支持的答案",
        publication_state="published",
        map_action=None,
    )

    assert result.decision is PublicationDecision.PUBLISH
    assert result.visible_text == "有证据支持的答案"


def test_blocked_publication_cannot_carry_candidate_text() -> None:
    result = PublishedResult.safe_fallback(
        publication_state="review_rejected",
        fallback_text="答案未通过证据审查，未发布。",
    )

    assert result.decision is PublicationDecision.SAFE_FALLBACK
    assert result.visible_text == "答案未通过证据审查，未发布。"
    assert result.answer is None


def test_publish_rejects_non_publishable_state() -> None:
    with pytest.raises(PublicationStateError):
        PublishedResult.publish(
            text="candidate",
            publication_state="review_rejected",
            map_action=None,
        )


def test_agent_run_result_typed_result_variants() -> None:
    from app.services.agent.answer_generator import AnswerUnit, GeneratedAnswer
    from app.services.agent.contracts import MapAction
    from app.services.agent.publication import (
        BrowserToolExecutionRequired,
        ClarificationRequired,
        DirectAnswerResult,
        KnowledgeAnswerResult,
        NoSafeAnswer,
        SafeLimitation,
    )
    from app.services.agent.runtime import AgentRunResult

    direct = AgentRunResult(
        session_id="s1", turn_id="t1", trace_id="tr1", publication_state="published",
        answer=GeneratedAnswer(kind="direct_answer", answer="hello", citations=(), units=()),
        clarification=None, limitation=None, frozen_evidence=None, review=None, events=(),
    )
    assert isinstance(direct.typed_result, DirectAnswerResult)
    assert direct.typed_result.text == "hello"

    knowledge = AgentRunResult(
        session_id="s1", turn_id="t1", trace_id="tr1", publication_state="published",
        answer=GeneratedAnswer(
            kind="knowledge_answer",
            answer="grounded answer",
            citations=("E1",),
            units=(AnswerUnit(unit_id="u1", text="grounded answer", citations=("E1",)),),
        ),
        clarification=None, limitation=None, frozen_evidence=None, review=None, events=(),
    )
    assert isinstance(knowledge.typed_result, KnowledgeAnswerResult)
    assert knowledge.typed_result.citations == ("E1",)

    clarification = AgentRunResult(
        session_id="s1", turn_id="t1", trace_id="tr1", publication_state="clarification",
        answer=None, clarification="confirm entity", limitation=None,
        frozen_evidence=None, review=None, events=(),
    )
    assert isinstance(clarification.typed_result, ClarificationRequired)
    assert clarification.typed_result.logical_turn_completed is False

    browser = AgentRunResult(
        session_id="s1", turn_id="t1", trace_id="tr1", publication_state="tool_execution_required",
        answer=MapAction(type="locate_map", target="target"), clarification=None, limitation=None,
        frozen_evidence=None, review=None, events=(), pending_tool_call_id="call-42",
        continuation_token="tok-42",
    )
    assert isinstance(browser.typed_result, BrowserToolExecutionRequired)
    assert browser.typed_result.tool_call_id == "call-42"

    limitation = AgentRunResult(
        session_id="s1", turn_id="t1", trace_id="tr1", publication_state="limitation",
        answer=None, clarification=None, limitation="out of scope",
        frozen_evidence=None, review=None, events=(),
    )
    assert isinstance(limitation.typed_result, SafeLimitation)

    no_safe = AgentRunResult(
        session_id="s1", turn_id="t1", trace_id="tr1", publication_state="review_rejected",
        answer=None, clarification=None, limitation=None,
        frozen_evidence=None, review=None, events=(),
    )
    assert isinstance(no_safe.typed_result, NoSafeAnswer)
    assert no_safe.typed_result.reason == "review_rejected"
