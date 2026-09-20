"""Main Controller → Tool → Observation loop for GeoRAG Agent mode."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import Any, AsyncIterator, Callable, Mapping
from uuid import uuid4

from app.services.agent.answer_generator import GeneratedAnswer
from app.services.agent.context import AgentContextBuilder
from app.services.agent.contracts import FrozenEvidenceSnapshot
from app.services.agent.events import AgentEvent
from app.services.agent.session import InMemoryAgentSessionStore
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.tool_runtime import (
    ResourceFuse,
    ToolObservation,
    ToolRuntime,
)
from app.services.rag.contracts import RetrievalPort


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    question: str
    session_id: str
    reviewer_enabled: bool = False
    thinking: bool = False
    endpoint_supports_reasoning: bool = False
    max_steps: int = 12
    max_elapsed_seconds: float = 60.0
    request_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    session_id: str
    turn_id: str
    trace_id: str
    publication_state: str
    answer: GeneratedAnswer | None
    clarification: str | None
    frozen_evidence: FrozenEvidenceSnapshot | None
    review: Any | None
    events: tuple[AgentEvent, ...]


@dataclass(frozen=True, slots=True)
class AgentStreamFrame:
    event: AgentEvent | None = None
    result: AgentRunResult | None = None


class AgentRuntime:
    def __init__(
        self,
        *,
        retrieval_port: RetrievalPort,
        controller,
        answer_generator,
        session_store: InMemoryAgentSessionStore,
        reviewer=None,
        context_builder: AgentContextBuilder | None = None,
    ) -> None:
        self.retrieval_port = retrieval_port
        self.controller = controller
        self.answer_generator = answer_generator
        self.reviewer = reviewer
        self.session_store = session_store
        self.context_builder = context_builder or AgentContextBuilder()

    async def run(
        self,
        request: AgentRunRequest,
        *,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> AgentRunResult:
        question = request.question.strip()
        if not question:
            raise ValueError("question must not be empty")

        session = self.session_store.get_or_create(request.session_id)
        turn_id = session.new_turn_id()
        trace_id = str(uuid4())
        turn_events: list[AgentEvent] = []

        self._append_event(
            session.events,
            turn_events,
            AgentEvent(
                event_type="user_message",
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={"text": question},
            ),
            event_listener,
        )

        fuse = ResourceFuse(
            max_steps=request.max_steps,
            max_elapsed_seconds=request.max_elapsed_seconds,
        )
        tool_runtime = ToolRuntime(
            retrieval_port=self.retrieval_port,
            evidence_ledger=session.evidence_ledger,
            resource_fuse=fuse,
        )
        stage_policy = LLMStagePolicy(
            user_thinking=request.thinking,
            endpoint_supports_reasoning=request.endpoint_supports_reasoning,
        )
        observations: list[ToolObservation] = []

        while True:
            fuse.ensure_within_limits()
            context = self.context_builder.build(
                question=question,
                prior_events=session.events[:-1],
                working_evidence=tuple(
                    {
                        "evidence_id": item.evidence_id,
                        "citation_id": item.citation_id,
                        "title": item.title,
                    }
                    for item in session.evidence_ledger.working_evidence(
                        turn_id=turn_id
                    )
                ),
            )
            call = await self.controller.decide(
                question=context.current_question,
                context_summary=self._merge_request_context(
                    context.summary,
                    request.request_context,
                ),
                observations=tuple(observations),
                stage_policy=stage_policy,
            )
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="controller_decision",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"tool_name": call.name, "tool_call_id": call.tool_call_id},
                ),
                event_listener,
            )
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="tool_started",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"tool_name": call.name, "tool_call_id": call.tool_call_id},
                ),
                event_listener,
            )

            observation = await tool_runtime.execute(turn_id=turn_id, call=call)
            if call.name == "compose_answer":
                snapshot = observation.payload["snapshot"]
                self._append_event(
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="evidence_frozen",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={
                            "snapshot_id": snapshot.snapshot_id,
                            "evidence_ids": list(snapshot.evidence_ids),
                        },
                    ),
                    event_listener,
                )

            observations.append(observation)
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": observation.tool_name,
                        "tool_call_id": observation.tool_call_id,
                        "status": observation.status,
                    },
                ),
                event_listener,
            )

            if not observation.is_terminal:
                continue

            if call.name == "clarify":
                clarification = str(observation.payload["question"])
                self._append_event(
                    session.events,
                    turn_events,
                    AgentEvent(
                        event_type="publication_completed",
                        session_id=session.session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={"state": "clarification"},
                    ),
                    event_listener,
                )
                return AgentRunResult(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    publication_state="clarification",
                    answer=None,
                    clarification=clarification,
                    frozen_evidence=None,
                    review=None,
                    events=tuple(turn_events),
                )

            snapshot = observation.payload["snapshot"]
            if not snapshot.items:
                raise ValueError("knowledge publication requires Frozen Evidence")
            answer = await self.answer_generator.generate(
                question=question,
                snapshot=snapshot,
                stage_policy=stage_policy,
            )
            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="answer_generated",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"kind": answer.kind, "citations": list(answer.citations)},
                ),
                event_listener,
            )

            review = None
            if request.reviewer_enabled:
                if self.reviewer is None:
                    raise RuntimeError("reviewer_enabled but no reviewer is configured")
                review = await self.reviewer.review(
                    question=question,
                    answer=answer,
                    snapshot=snapshot,
                    stage_policy=stage_policy,
                )

            self._append_event(
                session.events,
                turn_events,
                AgentEvent(
                    event_type="publication_completed",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"state": "published"},
                ),
                event_listener,
            )
            session.events.append(
                AgentEvent(
                    event_type="assistant_message",
                    session_id=session.session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={"text": answer.answer},
                )
            )
            return AgentRunResult(
                session_id=session.session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                publication_state="published",
                answer=answer,
                clarification=None,
                frozen_evidence=snapshot,
                review=review,
                events=tuple(turn_events),
            )

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentStreamFrame]:
        """Project observable events from the exact same ``run`` execution path."""

        queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue()
        sentinel = object()
        result_holder: list[AgentRunResult] = []

        async def execute() -> None:
            try:
                result = await self.run(
                    request,
                    event_listener=queue.put_nowait,
                )
                result_holder.append(result)
            finally:
                queue.put_nowait(sentinel)

        task = asyncio.create_task(execute())
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield AgentStreamFrame(event=item)  # type: ignore[arg-type]

        await task
        yield AgentStreamFrame(result=result_holder[0])

    @staticmethod
    def _append_event(
        session_events: list[AgentEvent],
        turn_events: list[AgentEvent],
        event: AgentEvent,
        event_listener: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        session_events.append(event)
        turn_events.append(event)
        if event_listener is not None:
            event_listener(event)

    @staticmethod
    def _merge_request_context(
        summary: str,
        request_context: Mapping[str, Any],
    ) -> str:
        if not request_context:
            return summary
        factual_context = json.dumps(
            dict(request_context),
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        if not summary:
            return f"request_context: {factual_context}"
        return f"{summary}\nrequest_context: {factual_context}"
