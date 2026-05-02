from __future__ import annotations

from datetime import datetime

from app.services.search_service import SearchService


def make_document_detail(doc_id: str, content: str) -> dict:
    return {
        "id": doc_id,
        "title": "DB50_T 1015-2020 土地整治项目规划设计规范",
        "content": content,
        "metadata": {
            "description": "用于验证文档追问的摘要与依据样式。",
        },
        "standard_info": {
            "code": "DB50_T 1015-2020",
        },
        "file_info": {
            "upload_time": datetime.now(),
        },
    }


def test_build_document_follow_up_fallback_answer_formats_evidence_as_blockquotes() -> None:
    service = SearchService.__new__(SearchService)
    detail = make_document_detail(
        "17930",
        content="本标准明确了项目规划设计总则。规定了土地整治项目编制要求。提出了质量控制与成果提交要求。",
    )

    answer = service.build_document_follow_up_fallback_answer(
        "17930：其核心强制性条文有哪些？",
        detail,
    )

    assert "《DB50_T 1015-2020 土地整治项目规划设计规范》" in answer
    assert "标准编号：DB50_T 1015-2020" in answer
    assert "\n> 依据1：" in answer


def test_normalize_evidence_blockquotes_converts_evidence_lines_only() -> None:
    service = SearchService.__new__(SearchService)

    answer = (
        "《示例标准》的主要内容可概括为：这是正文。\n"
        "标准编号：DB50/T 1015-2020\n"
        "依据1：第一条依据\n"
        "依据2：第二条依据"
    )

    normalized = service._normalize_evidence_blockquotes(answer)

    assert "《示例标准》的主要内容可概括为：这是正文。" in normalized
    assert "标准编号：DB50/T 1015-2020" in normalized
    assert "\n> 依据1：第一条依据" in normalized
    assert "\n> 依据2：第二条依据" in normalized
    assert "\n依据1：第一条依据" not in normalized
