from __future__ import annotations

import pytest

from app.services.agent.publication import (
    PublicationDecision,
    PublicationStateError,
    PublishedResult,
)


def test_publication_result_is_the_single_authority_for_visible_answer() -> None:
    result = PublishedResult.publish(
        text="鏈夎瘉鎹敮鎸佺殑绛旀",
        publication_state="published",
        map_action=None,
    )

    assert result.decision is PublicationDecision.PUBLISH
    assert result.visible_text == "鏈夎瘉鎹敮鎸佺殑绛旀"


def test_blocked_publication_cannot_carry_candidate_text() -> None:
    result = PublishedResult.safe_fallback(
        publication_state="review_rejected",
        fallback_text="绛旀鏈€氳繃璇佹嵁瀹℃煡锛屾湭鍙戝竷銆?,
    )

    assert result.decision is PublicationDecision.SAFE_FALLBACK
    assert result.visible_text == "绛旀鏈€氳繃璇佹嵁瀹℃煡锛屾湭鍙戝竷銆?
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

    # 1. Direct answer
    res_direct = AgentRunResult(
        session_id="s1",
        turn_id="t1",
        trace_id="tr1",
        publication_state="published",
        answer=GeneratedAnswer(
            kind="direct_answer",
            answer="鎮ㄥソ锛岃闂湁浠€涔堝彲浠ュ府鎮紵",
            citations=(),
            units=(),
        ),
        clarification=None,
        limitation=None,
        frozen_evidence=None,
        review=None,
        events=(),
    )
    assert isinstance(res_direct.typed_result, DirectAnswerResult)
    assert res_direct.typed_result.text == "鎮ㄥソ锛岃闂湁浠€涔堝彲浠ュ府鎮紵"
    assert res_direct.typed_result.user_visible is True
    assert res_direct.typed_result.logical_turn_completed is True

    # 2. Knowledge answer
    res_know = AgentRunResult(
        session_id="s1",
        turn_id="t1",
        trace_id="tr1",
        publication_state="published",
        answer=GeneratedAnswer(
            kind="knowledge_answer",
            answer="瀹圭Н鐜囦笂闄愪负 4.0銆?,
            citations=("E1",),
            units=(AnswerUnit(unit_id="u1", text="瀹圭Н鐜囦笂闄愪负 4.0銆?, citations=("E1",)),),
        ),
        clarification=None,
        limitation=None,
        frozen_evidence=None,
        review=None,
        events=(),
    )
    assert isinstance(res_know.typed_result, KnowledgeAnswerResult)
    assert res_know.typed_result.text == "瀹圭Н鐜囦笂闄愪负 4.0銆?
    assert res_know.typed_result.citations == ("E1",)
    assert res_know.typed_result.user_visible is True

    # 3. Clarification
    res_clarify = AgentRunResult(
        session_id="s1",
        turn_id="t1",
        trace_id="tr1",
        publication_state="clarification",
        answer=None,
        clarification="璇锋槑纭偍鏌ヨ鐨勬槸鎴愰兘甯傝繕鏄潚缇婂尯锛?,
        limitation=None,
        frozen_evidence=None,
        review=None,
        events=(),
    )
    assert isinstance(res_clarify.typed_result, ClarificationRequired)
    assert res_clarify.typed_result.question == "璇锋槑纭偍鏌ヨ鐨勬槸鎴愰兘甯傝繕鏄潚缇婂尯锛?
    assert res_clarify.typed_result.logical_turn_completed is False

    # 4. Browser tool continuation required
    res_browser = AgentRunResult(
        session_id="s1",
        turn_id="t1",
        trace_id="tr1",
        publication_state="tool_execution_required",
        answer=MapAction(type="locate_map", target="闈掔緤鍖?),
        clarification=None,
        limitation=None,
        frozen_evidence=None,
        review=None,
        events=(),
        pending_tool_call_id="call-42",
        continuation_token="tok-42",
    )
    assert isinstance(res_browser.typed_result, BrowserToolExecutionRequired)
    assert res_browser.typed_result.tool_call_id == "call-42"
    assert res_browser.typed_result.continuation_token == "tok-42"
    assert res_browser.typed_result.tool_name == "locate_map"
    assert res_browser.typed_result.user_visible is False
    assert res_browser.typed_result.logical_turn_completed is False

    # 5. Safe limitation
    res_limit = AgentRunResult(
        session_id="s1",
        turn_id="t1",
        trace_id="tr1",
        publication_state="limitation",
        answer=None,
        clarification=None,
        limitation="瓒呭嚭瑙勫垝绠¤緰鑼冨洿銆?,
        frozen_evidence=None,
        review=None,
        events=(),
    )
    assert isinstance(res_limit.typed_result, SafeLimitation)
    assert res_limit.typed_result.message == "瓒呭嚭瑙勫垝绠¤緰鑼冨洿銆?
    assert res_limit.typed_result.logical_turn_completed is True

    # 6. No safe answer (review_rejected / fuse)
    res_nosafe = AgentRunResult(
        session_id="s1",
        turn_id="t1",
        trace_id="tr1",
        publication_state="review_rejected",
        answer=None,
        clarification=None,
        limitation=None,
        frozen_evidence=None,
        review=None,
        events=(),
    )
    assert isinstance(res_nosafe.typed_result, NoSafeAnswer)
    assert res_nosafe.typed_result.reason == "review_rejected"
