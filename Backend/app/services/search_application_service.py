"""Application boundary that selects deterministic search or generation mode."""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import AsyncIterator
from uuid import uuid4

from app.models.search_models import SearchRequest, SearchResponse
from app.services.agent.evidence import EvidenceLedger
from app.services.agent.events import AgentEvent
from app.services.agent.runtime import AgentRunRequest
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import RetrievalRequestConstraints
from app.services.rag.contracts import RetrievalCandidate


RELAXED_VECTOR_THRESHOLD = 0.35


@dataclass(frozen=True, slots=True)
class SearchStreamFrame:
    event: AgentEvent | None = None
    response: SearchResponse | None = None


class SearchApplicationService:
    """Own explicit product-mode routing without semantic intent classification."""

    def __init__(
        self,
        *,
        search_service,
        asset_service,
        contract_service,
        agent_runtime,
        retrieval_port,
    ) -> None:
        self.search_service = search_service
        self.asset_service = asset_service
        self.contract_service = contract_service
        self.agent_runtime = agent_runtime
        self.retrieval_port = retrieval_port

    async def execute(
        self,
        request: SearchRequest,
        *,
        generation_allowed: bool,
        principal_id: str,
    ) -> SearchResponse:
        started_at = datetime.now()
        if not generation_allowed:
            results = await self._deterministic_search(request)
            return SearchResponse(
                query=request.query,
                results=results,
                total_count=len(results),
                search_time=(datetime.now() - started_at).total_seconds(),
                search_mode=request.search_mode,
            )

        mode = request.mode or "agent"
        if mode == "linear":
            results = await self._deterministic_search(request)
            session_id = request.session_id or f"session-{uuid4()}"
            ledger = EvidenceLedger(session_id=session_id)
            turn_id = f"linear-{uuid4()}"
            admitted = ledger.add_candidates(
                turn_id=turn_id,
                candidates=tuple(
                    RetrievalCandidate.from_document_result(result)
                    for result in results
                ),
            )
            if not admitted:
                return SearchResponse(
                    query=request.query,
                    results=results,
                    total_count=len(results),
                    search_time=(datetime.now() - started_at).total_seconds(),
                    search_mode=request.search_mode,
                    generated_answer=None,
                    session_id=session_id,
                    final_mode="linear",
                    publication_state="insufficient_evidence",
                )
            snapshot = ledger.freeze(
                turn_id=turn_id,
                evidence_ids=[item.evidence_id for item in admitted],
            )
            answer = await self.agent_runtime.answer_generator.generate(
                question=request.query,
                snapshot=snapshot,
                stage_policy=LLMStagePolicy(
                    user_thinking=False,
                    endpoint_supports_reasoning=False,
                ),
            )
            publication_state = "published"
            generated_answer = answer.answer
            if request.reviewer_enabled:
                reviewer = getattr(self.agent_runtime, "reviewer", None)
                if reviewer is None:
                    publication_state = "review_failed"
                    generated_answer = "证据审查执行失败，答案未发布。"
                else:
                    try:
                        review = await reviewer.review(
                            question=request.query,
                            answer=answer,
                            snapshot=snapshot,
                            stage_policy=LLMStagePolicy(
                                user_thinking=False,
                                endpoint_supports_reasoning=False,
                            ),
                        )
                    except Exception:
                        publication_state = "review_failed"
                        generated_answer = "证据审查执行失败，答案未发布。"
                    else:
                        verdict = str(getattr(review, "verdict", "")).strip().upper()
                        if verdict not in {"SUPPORTED", "PASS", "PASSED"}:
                            publication_state = "review_rejected"
                            generated_answer = "答案未通过证据审查，未发布。"
            elapsed = (datetime.now() - started_at).total_seconds()
            return SearchResponse(
                query=request.query,
                results=results,
                total_count=len(results),
                search_time=elapsed,
                search_mode=request.search_mode,
                generated_answer=generated_answer,
                generation_time=elapsed,
                session_id=session_id,
                final_mode="linear",
                publication_state=publication_state,
                map_action=(answer.map_action if publication_state == "published" else None),
            )

        session_id = request.session_id or f"session-{uuid4()}"
        run_result = await self.agent_runtime.run(
            AgentRunRequest(
                question=request.query,
                session_id=session_id,
                principal_id=principal_id,
                reviewer_enabled=request.reviewer_enabled,
                thinking=bool(request.thinking),
                request_context={
                    "follow_up_context": (
                        request.follow_up_context.model_dump()
                        if request.follow_up_context is not None
                        else None
                    ),
                },
                legacy_history=tuple(
                    message.model_dump() for message in (request.history or [])
                ),
                retrieval_constraints=self._retrieval_constraints(request),
            )
        )
        results = await self._results_from_frozen_evidence(run_result.frozen_evidence)
        generated_answer = (
            run_result.answer.answer
            if run_result.answer is not None
            else (run_result.clarification or run_result.limitation)
        )
        elapsed = (datetime.now() - started_at).total_seconds()
        return SearchResponse(
            query=request.query,
            results=results,
            total_count=len(results),
            search_time=elapsed,
            search_mode=request.search_mode,
            generated_answer=generated_answer,
            generation_time=elapsed,
            session_id=run_result.session_id,
            trace_id=run_result.trace_id,
            final_mode="agent",
            publication_state=run_result.publication_state,
            map_action=(
                getattr(run_result.answer, "map_action", None)
                if run_result.answer is not None
                else None
            ),
        )

    async def stream(
        self,
        request: SearchRequest,
        *,
        generation_allowed: bool,
        principal_id: str,
    ) -> AsyncIterator[SearchStreamFrame]:
        if not generation_allowed or (request.mode or "agent") == "linear":
            yield SearchStreamFrame(
                response=await self.execute(
                    request,
                    generation_allowed=generation_allowed,
                    principal_id=principal_id,
                )
            )
            return

        started_at = datetime.now()
        session_id = request.session_id or f"session-{uuid4()}"
        run_request = AgentRunRequest(
            question=request.query,
            session_id=session_id,
            principal_id=principal_id,
            reviewer_enabled=request.reviewer_enabled,
            thinking=bool(request.thinking),
            request_context={
                "follow_up_context": (
                    request.follow_up_context.model_dump()
                    if request.follow_up_context is not None
                    else None
                ),
            },
            legacy_history=tuple(
                message.model_dump() for message in (request.history or [])
            ),
            retrieval_constraints=self._retrieval_constraints(request),
        )

        async for frame in self.agent_runtime.stream(run_request):
            if frame.event is not None:
                yield SearchStreamFrame(event=frame.event)
                continue

            run_result = frame.result
            if run_result is None:
                continue
            results = await self._results_from_frozen_evidence(run_result.frozen_evidence)
            generated_answer = (
                run_result.answer.answer
                if run_result.answer is not None
                else (run_result.clarification or run_result.limitation)
            )
            elapsed = (datetime.now() - started_at).total_seconds()
            yield SearchStreamFrame(
                response=SearchResponse(
                    query=request.query,
                    results=results,
                    total_count=len(results),
                    search_time=elapsed,
                    search_mode=request.search_mode,
                    generated_answer=generated_answer,
                    generation_time=elapsed,
                    session_id=run_result.session_id,
                    trace_id=run_result.trace_id,
                    final_mode="agent",
                    publication_state=run_result.publication_state,
                    map_action=(
                        getattr(run_result.answer, "map_action", None)
                        if run_result.answer is not None
                        else None
                    ),
                )
            )

    async def _deterministic_search(self, request: SearchRequest):
        results = await self.search_service.search(
            query=request.query,
            top_k=request.top_k,
            threshold=request.threshold,
            spatial_filter=request.spatial_filter,
            metadata_filter=request.metadata_filter,
            search_mode=request.search_mode,
            use_rerank=request.use_rerank,
        )
        if not results and request.threshold > RELAXED_VECTOR_THRESHOLD:
            results = await self.search_service.search(
                query=request.query,
                top_k=request.top_k,
                threshold=RELAXED_VECTOR_THRESHOLD,
                spatial_filter=request.spatial_filter,
                metadata_filter=request.metadata_filter,
                search_mode=request.search_mode,
                use_rerank=request.use_rerank,
            )
        results = await self.asset_service.enrich_search_results(results)
        return await self.contract_service.filter_deleted_results(results)

    async def _results_from_frozen_evidence(self, snapshot):
        if snapshot is None or not snapshot.items:
            return []
        chunk_ids = [item.chunk_id for item in snapshot.items]
        candidates = await self.retrieval_port.fetch_chunks(chunk_ids)
        results = [candidate.source_result for candidate in candidates]
        results = await self.asset_service.enrich_search_results(results)
        return await self.contract_service.filter_deleted_results(results)

    @staticmethod
    def _retrieval_constraints(request: SearchRequest) -> RetrievalRequestConstraints:
        return RetrievalRequestConstraints(
            top_k=request.top_k,
            threshold=request.threshold,
            search_mode=request.search_mode,
            use_rerank=request.use_rerank,
            metadata_filter=request.metadata_filter,
            spatial_filter=request.spatial_filter,
        )
