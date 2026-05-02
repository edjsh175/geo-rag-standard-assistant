from __future__ import annotations

from datetime import datetime

import pytest

from app.models.chat_models import ChatRequest
from app.models.search_models import DocumentResult, FollowUpContext
from app.services.chat_service import ChatService, ChatToolDecision


def make_result(doc_id: str, title: str = "result") -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=title,
        content=f"content for {title}",
        similarity=0.88,
        metadata={"document_name": title, "standard_code": "DB50_T 1015-2020"},
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


def make_document_detail(doc_id: str, content: str = "文档内容摘要") -> dict:
    return {
        "id": doc_id,
        "title": "DB50_T 1015-2020 土地整治项目规划设计规范",
        "content": content,
        "metadata": {
            "description": "适用于土地整治项目规划设计。",
            "keywords": ["土地整治", "规划设计"],
            "custom_fields": {"standard_code": "DB50_T 1015-2020"},
        },
        "spatial_info": None,
        "file_info": {
            "type": "pdf",
            "size": 1024,
            "upload_time": datetime.now(),
            "filename": "DB50_T 1015-2020.pdf",
            "mime_type": "application/pdf",
        },
        "standard_info": {
            "code": "DB50_T 1015-2020",
            "status": "现行",
        },
        "download_available": True,
        "download_url": f"/api/documents/{doc_id}/download",
    }


class SearchServiceStub:
    def __init__(self) -> None:
        self.results: list[DocumentResult] = []
        self.follow_up_result: DocumentResult | None = None
        self.follow_up_detail: dict | None = None
        self.dialog_answer = "这是对话总结。"
        self.generated_answer = "这是检索后的归纳回答。"

    def _truncate_history(self, history, max_messages: int = 6):
        return (history or [])[-max_messages:]

    def extract_explicit_document_id(self, query: str) -> str | None:
        if "17930" in query:
            return "17930"
        return None

    async def load_follow_up_document_result(self, follow_up_context, asset_service):
        return self.follow_up_detail, self.follow_up_result

    async def generate_document_follow_up_answer(self, query, document_detail, history=None):
        return "这是单文档追问回答。", 0.05

    async def search(self, query, top_k, threshold, spatial_filter=None, metadata_filter=None):
        return self.results

    async def generate_answer(self, query, results, top_context_docs=5, history=None):
        return self.generated_answer, 0.12

    async def handle_dialog_management(self, query, history=None):
        return self.dialog_answer

    def _detect_rule_based_intent(self, query: str) -> str | None:
        if "总结一下" in query:
            return "dialog_management"
        if "闲聊" in query:
            return "other"
        return None


class AssetServiceStub:
    async def enrich_search_results(self, results: list[DocumentResult]) -> list[DocumentResult]:
        return results


@pytest.mark.asyncio
async def test_handle_chat_returns_direct_response_without_search(monkeypatch: pytest.MonkeyPatch) -> None:
    search_service = SearchServiceStub()
    chat_service = ChatService(search_service=search_service, asset_service=AssetServiceStub())

    async def fake_decide_tools(*args, **kwargs) -> ChatToolDecision:
        return ChatToolDecision(intent="other", use_search_tool=False, reason="No retrieval needed.")

    async def fake_direct_response(*args, **kwargs) -> str:
        return "可以继续闲聊，也可以切回标准检索。"

    monkeypatch.setattr(chat_service, "decide_tools", fake_decide_tools)
    monkeypatch.setattr(chat_service, "generate_non_search_response", fake_direct_response)

    response = await chat_service.handle_chat(ChatRequest(message="我们可以随便闲聊吗"))

    assert response.message == "可以继续闲聊，也可以切回标准检索。"
    assert response.references == []
    assert response.mode == "direct"
    assert response.tool_trace and response.tool_trace[0].used is False


@pytest.mark.asyncio
async def test_handle_chat_routes_dialog_management_without_search(monkeypatch: pytest.MonkeyPatch) -> None:
    search_service = SearchServiceStub()
    chat_service = ChatService(search_service=search_service, asset_service=AssetServiceStub())

    async def fake_decide_tools(*args, **kwargs) -> ChatToolDecision:
        return ChatToolDecision(intent="dialog_management", use_search_tool=False, reason="Dialog management.")

    monkeypatch.setattr(chat_service, "decide_tools", fake_decide_tools)

    response = await chat_service.handle_chat(ChatRequest(message="总结一下我们刚才在聊什么"))

    assert response.message == search_service.dialog_answer
    assert response.references == []
    assert response.mode == "direct"


@pytest.mark.asyncio
async def test_handle_chat_uses_search_tool_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    search_service = SearchServiceStub()
    search_service.results = [make_result("17930", "土地整治项目规划设计规范")]
    chat_service = ChatService(search_service=search_service, asset_service=AssetServiceStub())

    async def fake_decide_tools(*args, **kwargs) -> ChatToolDecision:
        return ChatToolDecision(
            intent="search",
            use_search_tool=True,
            search_query="土地整治与利用",
            reason="User is asking for document-backed information.",
        )

    monkeypatch.setattr(chat_service, "decide_tools", fake_decide_tools)

    response = await chat_service.handle_chat(ChatRequest(message="土地整治与利用"))

    assert response.message == search_service.generated_answer
    assert len(response.references) == 1
    assert response.references[0].id == "17930"
    assert response.mode == "search"
    assert response.tool_trace and response.tool_trace[0].used is True


@pytest.mark.asyncio
async def test_handle_chat_uses_follow_up_document_path_for_explicit_doc_id() -> None:
    search_service = SearchServiceStub()
    search_service.follow_up_detail = make_document_detail("17930")
    search_service.follow_up_result = make_result("17930", "土地整治项目规划设计规范")
    chat_service = ChatService(search_service=search_service, asset_service=AssetServiceStub())

    response = await chat_service.handle_chat(
        ChatRequest(message="17930：其核心强制性条文有哪些？")
    )

    assert response.message == "这是单文档追问回答。"
    assert len(response.references) == 1
    assert response.references[0].id == "17930"
    assert response.mode == "follow_up"


@pytest.mark.asyncio
async def test_handle_chat_returns_no_evidence_message_when_search_finds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search_service = SearchServiceStub()
    chat_service = ChatService(search_service=search_service, asset_service=AssetServiceStub())

    async def fake_decide_tools(*args, **kwargs) -> ChatToolDecision:
        return ChatToolDecision(
            intent="search",
            use_search_tool=True,
            search_query="不存在的标准主题",
            reason="User explicitly asked for standard evidence.",
        )

    monkeypatch.setattr(chat_service, "decide_tools", fake_decide_tools)

    response = await chat_service.handle_chat(ChatRequest(message="不存在的标准主题"))

    assert "未找到与该问题直接相关的文档依据" in response.message
    assert response.references == []
    assert response.mode == "search"
