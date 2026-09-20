"""Application boundary that selects deterministic search or generation mode."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.models.search_models import SearchRequest, SearchResponse
from app.services.agent.runtime import AgentRunRequest
from app.services.map_action_adapter import LegacyMapActionAdapter


RELAXED_VECTOR_THRESHOLD = 0.35


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
        endpoint_supports_reasoning: bool = False,
    ) -> None:
        self.search_service = search_service
        self.asset_service = asset_service
        self.contract_service = contract_service
        self.agent_runtime = agent_runtime
        self.retrieval_port = retrieval_port
        self.endpoint_supports_reasoning = endpoint_supports_reasoning

    async def execute(
        self,
        request: SearchRequest,
        *,
        generation_allowed: bool,
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
            generated_answer, _ = await self.search_service.generate_answer(
                query=request.query,
                results=results,
                top_context_docs=min(5, len(results)),
                history=request.history,
            )
            adapted = LegacyMapActionAdapter().adapt(generated_answer)
            elapsed = (datetime.now() - started_at).total_seconds()
            return SearchResponse(
                query=request.query,
                results=results,
                total_count=len(results),
                search_time=elapsed,
                search_mode=request.search_mode,
                generated_answer=adapted.answer,
                generation_time=elapsed,
                final_mode="linear",
                publication_state="published",
                map_action=adapted.map_action,
            )

        session_id = request.session_id or f"session-{uuid4()}"
        run_result = await self.agent_runtime.run(
            AgentRunRequest(
                question=request.query,
                session_id=session_id,
                reviewer_enabled=request.reviewer_enabled,
                thinking=bool(request.thinking),
                endpoint_supports_reasoning=self.endpoint_supports_reasoning,
                request_context={
                    "follow_up_context": (
                        request.follow_up_context.model_dump()
                        if request.follow_up_context is not None
                        else None
                    ),
                    "legacy_history": [
                        message.model_dump() for message in (request.history or [])
                    ],
                },
            )
        )
        results = await self._results_from_frozen_evidence(run_result.frozen_evidence)
        generated_answer = (
            run_result.answer.answer
            if run_result.answer is not None
            else run_result.clarification
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
