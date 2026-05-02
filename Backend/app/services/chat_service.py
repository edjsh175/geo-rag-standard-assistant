"""
Chat orchestration service that decides when to call document retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional

from app.core.llm_config import llm_config
from app.models.chat_models import ChatRequest, ChatResponse, ChatToolTrace
from app.models.search_models import FollowUpContext
from app.services.document_asset_service import DocumentAssetService
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

SEARCH_TOOL_NAME = "search_documents"
RELAXED_VECTOR_THRESHOLD = 0.35
DOC_SPECIFIC_HINTS = (
    "内容",
    "条文",
    "强制",
    "核心",
    "适用范围",
    "摘要",
    "总结",
    "讲了什么",
    "说了什么",
    "定义",
    "要求",
    "标准",
    "文档",
)
SEARCH_INTENT_HINTS = (
    "标准",
    "规范",
    "规程",
    "政策",
    "条文",
    "定义",
    "适用范围",
    "强制性",
    "技术",
    "要求",
    "土地整治",
    "开发边界",
    "红线",
    "基本农田",
    "文档",
)


@dataclass
class ChatToolDecision:
    intent: Literal["search", "dialog_management", "greeting", "other", "product_qa"] = "other"
    use_search_tool: bool = False
    search_query: Optional[str] = None
    use_follow_up_document: bool = False
    reason: str = ""


class ChatService:
    """High-level chat service that treats retrieval as an optional tool."""

    def __init__(self, search_service: SearchService, asset_service: DocumentAssetService):
        self.search_service = search_service
        self.asset_service = asset_service

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        conversation_id = request.conversation_id or f"conv_{int(datetime.now().timestamp() * 1000)}"
        resolved_follow_up_context = self._resolve_follow_up_context(request.message, request.follow_up_context)
        decision = await self.decide_tools(
            query=request.message,
            history=request.history,
            follow_up_context=resolved_follow_up_context,
        )

        if decision.use_search_tool:
            return await self._handle_search_tool(
                request=request,
                conversation_id=conversation_id,
                decision=decision,
                follow_up_context=resolved_follow_up_context,
            )

        if decision.intent == "dialog_management":
            message = await self.search_service.handle_dialog_management(
                query=request.message,
                history=request.history,
            )
        else:
            message = await self.generate_non_search_response(
                query=request.message,
                intent=decision.intent,
                history=request.history,
            )

        return ChatResponse(
            message=message,
            conversation_id=conversation_id,
            references=[],
            tool_trace=[
                ChatToolTrace(
                    tool_name=SEARCH_TOOL_NAME,
                    used=False,
                    reason=decision.reason or "Direct chat response selected.",
                )
            ],
            mode="direct",
        )

    async def decide_tools(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
        follow_up_context: Optional[FollowUpContext] = None,
    ) -> ChatToolDecision:
        if follow_up_context and follow_up_context.target_document_id:
            return ChatToolDecision(
                intent="search",
                use_search_tool=True,
                search_query=query,
                use_follow_up_document=True,
                reason="Resolved follow-up document context is available.",
            )

        truncated_history = self.search_service._truncate_history(history)
        history_text = json.dumps(truncated_history[-4:], ensure_ascii=False)
        candidate_documents = follow_up_context.candidate_documents if follow_up_context else []
        candidate_text = json.dumps([doc.model_dump() for doc in candidate_documents], ensure_ascii=False)

        system_prompt = """
你是 GeoAI 聊天编排器。你的任务是决定这轮消息是否需要调用 `search_documents` 工具。

规则：
1. 只有当用户明确在查询标准、规范、政策、条文、定义、适用范围、强制性要求，或需要文档依据时，才使用 search_documents。
2. 如果用户是在闲聊、寒暄、询问产品能力、要求总结当前对话、重复上一条回答、解释刚才的表达方式，不要使用 search_documents。
3. 如果用户在追问上一轮文档，且已经有 follow_up_context，可将 use_follow_up_document 设为 true。
4. 如果不需要检索，也不要假装已经查库。

只返回 JSON，不要返回 Markdown 代码块，不要解释。
JSON 结构：
{
  "intent": "search|dialog_management|greeting|other|product_qa",
  "use_search_tool": true,
  "search_query": "用于检索的精炼查询；不检索时为空字符串",
  "use_follow_up_document": false,
  "reason": "一句中文说明"
}
"""

        user_prompt = f"""
当前用户消息：
{query}

最近对话（截断）：
{history_text}

最近候选文档：
{candidate_text}
"""

        try:
            raw_decision = await llm_config.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=220,
            )
            parsed = self._parse_decision_payload(raw_decision)
            if parsed is not None:
                return parsed
            logger.warning("Chat tool decision parsing failed; using fallback routing. Raw=%r", raw_decision)
        except Exception as exc:
            logger.error("Chat tool decision generation failed: %s", exc)

        return self._fallback_tool_decision(query, follow_up_context)

    async def generate_non_search_response(
        self,
        query: str,
        intent: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        truncated_history = self.search_service._truncate_history(history)
        system_prompt = """
你是 GeoAI 空间规划智能助手。
当前这轮对话不允许检索文档库，也不要声称你已经查库。

你可以处理：
- 闲聊和寒暄
- 产品能力说明
- 对当前对话的简短解释
- 不要求文档依据的简短说明

回复要求：
1. 用中文回答，1 到 4 句。
2. 语气自然、专业、克制。
3. 如果用户后续需要标准依据，可以提醒他继续提供标准主题、编号或文档名称。
4. 不要输出“已检索到相关标准”或“未在库中检索到相关标准规定”。
"""

        try:
            answer = await llm_config.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    *truncated_history,
                    {"role": "user", "content": f"intent={intent}\nquery={query}"},
                ],
                temperature=0.5,
                max_tokens=280,
            )
            return answer.strip()
        except Exception as exc:
            logger.error("Direct chat response generation failed: %s", exc)
            return self._fallback_non_search_response(query, intent)

    async def _handle_search_tool(
        self,
        request: ChatRequest,
        conversation_id: str,
        decision: ChatToolDecision,
        follow_up_context: Optional[FollowUpContext],
    ) -> ChatResponse:
        query = request.message
        tool_query = decision.search_query or query
        tool_trace = [
            ChatToolTrace(
                tool_name=SEARCH_TOOL_NAME,
                used=True,
                reason=decision.reason or "Document retrieval was requested for this turn.",
                query=tool_query,
            )
        ]

        if follow_up_context and follow_up_context.target_document_id:
            detail, result = await self.search_service.load_follow_up_document_result(
                follow_up_context,
                self.asset_service,
            )
            if detail and result:
                answer, _ = await self.search_service.generate_document_follow_up_answer(
                    query=query,
                    document_detail=detail,
                    history=request.history,
                )
                tool_trace[0].result_count = 1
                return ChatResponse(
                    message=answer,
                    conversation_id=conversation_id,
                    references=[result],
                    tool_trace=tool_trace,
                    mode="follow_up",
                )

        results = await self.search_service.search(
            query=tool_query,
            top_k=request.top_k,
            threshold=0.7,
            spatial_filter=None,
            metadata_filter=None,
        )
        if not results:
            results = await self.search_service.search(
                query=tool_query,
                top_k=request.top_k,
                threshold=RELAXED_VECTOR_THRESHOLD,
                spatial_filter=None,
                metadata_filter=None,
            )

        results = await self.asset_service.enrich_search_results(results)
        tool_trace[0].result_count = len(results)

        if not results:
            return ChatResponse(
                message="未找到与该问题直接相关的文档依据。可以补充标准编号、地区或更具体的主题关键词。",
                conversation_id=conversation_id,
                references=[],
                tool_trace=tool_trace,
                mode="search",
            )

        try:
            answer, _ = await self.search_service.generate_answer(
                query=query,
                results=results,
                top_context_docs=min(5, len(results)),
                history=request.history,
            )
        except Exception as exc:
            logger.error("Grounded search answer generation failed: %s", exc)
            answer = self._build_search_results_fallback_answer(results)

        return ChatResponse(
            message=answer,
            conversation_id=conversation_id,
            references=results,
            tool_trace=tool_trace,
            mode="search",
        )

    def _resolve_follow_up_context(
        self,
        query: str,
        follow_up_context: Optional[FollowUpContext],
    ) -> Optional[FollowUpContext]:
        if follow_up_context and follow_up_context.target_document_id:
            return follow_up_context

        explicit_document_id = self.search_service.extract_explicit_document_id(query)
        if explicit_document_id and self._looks_like_document_specific_question(query):
            candidate_documents = follow_up_context.candidate_documents if follow_up_context else []
            return FollowUpContext(
                target_document_id=explicit_document_id,
                candidate_documents=candidate_documents,
                resolution_source="explicit_text",
            )

        return follow_up_context

    def _looks_like_document_specific_question(self, query: str) -> bool:
        compact_query = re.sub(r"\s+", "", query or "")
        if not compact_query:
            return False
        if compact_query[0].isdigit() and ("：" in query or ":" in query):
            return True
        return any(hint in compact_query for hint in DOC_SPECIFIC_HINTS)

    def _parse_decision_payload(self, payload: str) -> Optional[ChatToolDecision]:
        if not payload:
            return None

        normalized = payload.strip()
        if normalized.startswith("```"):
            normalized = re.sub(r"^```(?:json)?\s*|\s*```$", "", normalized, flags=re.IGNORECASE | re.DOTALL).strip()

        try:
            data = json.loads(normalized)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", normalized, re.DOTALL)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        intent = str(data.get("intent") or "").strip().lower()
        if intent not in {"search", "dialog_management", "greeting", "other", "product_qa"}:
            return None

        return ChatToolDecision(
            intent=intent,  # type: ignore[arg-type]
            use_search_tool=bool(data.get("use_search_tool")),
            search_query=str(data.get("search_query") or "").strip() or None,
            use_follow_up_document=bool(data.get("use_follow_up_document")),
            reason=str(data.get("reason") or "").strip(),
        )

    def _fallback_tool_decision(
        self,
        query: str,
        follow_up_context: Optional[FollowUpContext],
    ) -> ChatToolDecision:
        if follow_up_context and follow_up_context.target_document_id:
            return ChatToolDecision(
                intent="search",
                use_search_tool=True,
                search_query=query,
                use_follow_up_document=True,
                reason="Fallback routing preserved explicit follow-up document context.",
            )

        rule_based_intent = getattr(self.search_service, "_detect_rule_based_intent", None)
        if callable(rule_based_intent):
            intent = rule_based_intent(query)
            if intent == "dialog_management":
                return ChatToolDecision(
                    intent="dialog_management",
                    use_search_tool=False,
                    reason="Fallback routing detected dialog-management wording.",
                )
            if intent in {"greeting", "other"}:
                return ChatToolDecision(
                    intent=intent,  # type: ignore[arg-type]
                    use_search_tool=False,
                    reason="Fallback routing detected non-search wording.",
                )

        compact_query = re.sub(r"\s+", "", query or "")
        if any(hint in compact_query for hint in SEARCH_INTENT_HINTS):
            return ChatToolDecision(
                intent="search",
                use_search_tool=True,
                search_query=query,
                reason="Fallback routing detected document-search language.",
            )

        return ChatToolDecision(
            intent="other",
            use_search_tool=False,
            reason="Fallback routing defaulted to direct chat response.",
        )

    def _fallback_non_search_response(self, query: str, intent: str) -> str:
        compact_query = re.sub(r"\s+", "", query or "")
        if intent == "dialog_management":
            return "可以继续追问上一轮内容，或者让我重复、总结刚才的对话。"
        if "你能做什么" in compact_query or "可以做什么" in compact_query or "你是谁" in compact_query:
            return "我可以陪你简短交流，也可以在需要时检索标准规范、定位到具体文档，并继续追问某份文档的内容。"
        if intent == "greeting" or "闲聊" in compact_query or "聊天" in compact_query:
            return "可以。你可以直接和我聊，也可以随时切回标准检索、文档追问或空间规划相关问题。"
        return "可以继续问我产品能力、当前对话内容，或者在需要文档依据时直接给我标准主题、编号或文档名称。"

    def _build_search_results_fallback_answer(self, results: List[Any]) -> str:
        top_results = results[:3]
        if not top_results:
            return "未找到与该问题直接相关的文档依据。"

        lines = ["我找到了以下相关文档依据："]
        for index, result in enumerate(top_results, start=1):
            snippet = re.sub(r"\s+", " ", str(result.content or "")).strip()[:80]
            if snippet:
                lines.append(f"{index}. 《{result.title}》：{snippet}")
            else:
                lines.append(f"{index}. 《{result.title}》")
        lines.append("如果你要继续深挖其中一份，可以直接告诉我文档编号或继续追问具体条文。")
        return "\n".join(lines)
