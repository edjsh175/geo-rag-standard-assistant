from __future__ import annotations

from datetime import datetime

import pytest

from app.services.search_service import SearchService


def make_document_detail(doc_id: str, content: str) -> dict:
    return {
        "id": doc_id,
        "title": "DB14_T 3429-2025 全域土地综合整治项目可行性研究报告编制规范",
        "content": content,
        "metadata": {
            "description": "无",
            "keywords": ["土地", "整治"],
            "custom_fields": {"standard_code": "DB14_T 3429-2025"},
        },
        "spatial_info": None,
        "file_info": {
            "type": "pdf",
            "size": 1024,
            "upload_time": datetime.now(),
            "filename": "DB14_T 3429-2025.pdf",
            "mime_type": "application/pdf",
        },
        "standard_info": {
            "code": "DB14_T 3429-2025",
            "status": "现行",
        },
        "download_available": True,
        "download_url": f"/api/documents/{doc_id}/download",
    }


@pytest.mark.asyncio
async def test_detect_intent_treats_casual_chat_as_other_without_llm() -> None:
    service = SearchService.__new__(SearchService)

    intent = await service.detect_intent("我们可以随便闲聊吗")

    assert intent == "other"


@pytest.mark.asyncio
async def test_detect_intent_treats_dialog_management_query_without_llm() -> None:
    service = SearchService.__new__(SearchService)

    intent = await service.detect_intent("总结一下我们刚才在讨论什么")

    assert intent == "dialog_management"


def test_document_follow_up_fallback_ignores_placeholder_description() -> None:
    service = SearchService.__new__(SearchService)
    detail = make_document_detail(
        "7873",
        content="本标准明确了项目编制要求。规定了建设边界约束条件。",
    )

    answer = service.build_document_follow_up_fallback_answer(
        "7873的主要内容是什么",
        detail,
    )

    assert "主要内容可概括为：无" not in answer
    assert "项目编制要求" in answer
