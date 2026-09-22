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
