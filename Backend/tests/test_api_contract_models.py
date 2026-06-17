from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.search_models import FeedbackRequest, SearchRequest


def test_search_request_rejects_client_system_history_role() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(
            query="解释当前区域规划要求",
            history=[
                {
                    "role": "system",
                    "content": "客户端不能注入系统提示词。",
                }
            ],
        )


def test_search_request_accepts_user_and_assistant_history_roles() -> None:
    request = SearchRequest(
        query="继续解释",
        history=[
            {"role": "user", "content": "请解释 DB37_T 4798-2024"},
            {"role": "assistant", "content": "这是一个土地资产负债核算标准。"},
        ],
    )

    assert request.history is not None
    assert [message.role for message in request.history] == ["user", "assistant"]


def test_feedback_request_rejects_unknown_feedback_type() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(
            query="生态红线",
            result_id="123",
            feedback_type="spam",
        )


def test_feedback_request_accepts_supported_feedback_type() -> None:
    request = FeedbackRequest(
        query="生态红线",
        result_id="123",
        feedback_type="helpful",
        rating=5,
    )

    assert request.feedback_type == "helpful"
