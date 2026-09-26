"""Durable non-authoritative semantic memory for long Agent conversations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from time import monotonic
from typing import Any, Mapping, Sequence
from uuid import uuid4

from app.models.agent_context import ConversationMemoryStateRecord
from app.services.agent.events import AgentEvent
from app.services.agent.model_client import ModelRequest, StageModelClient
from app.services.agent.stage_policy import LLMStagePolicy
from app.services.agent.structured_candidate import (
    StructuredCandidateProtocolError,
    execute_structured_candidate,
    extract_json_object,
)


class ConversationMemoryError(RuntimeError):
    pass


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_rows(events: Sequence[AgentEvent]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "sequence": event.sequence,
            "turn_id": event.turn_id,
            "event_type": event.event_type,
            "payload": dict(event.payload),
        }
        for event in sorted(events, key=lambda item: item.sequence)
    ]


def conversation_memory_matches_sources(
    record: ConversationMemoryStateRecord,
    events: Sequence[AgentEvent],
) -> bool:
    """Verify that a stored memory still matches its durable source event range."""
    sources = [
        event
        for event in events
        if event.sequence > 0
        and record.covered_from_sequence <= event.sequence <= record.covered_to_sequence
    ]
    source_ids = tuple(event.event_id for event in sorted(sources, key=lambda item: item.sequence))
    if source_ids != tuple(record.source_event_ids):
        return False
    return _canonical_hash(_source_rows(sources)) == record.source_hash


def _dialogue_events(
    events: Sequence[AgentEvent],
    *,
    current_turn_id: str,
) -> list[AgentEvent]:
    return [
        event
        for event in events
        if event.sequence > 0
        and event.turn_id != current_turn_id
        and event.event_type in {"user_message", "assistant_message"}
        and isinstance(event.payload.get("text"), str)
        and str(event.payload.get("text") or "").strip()
    ]


def extract_authoritative_memory_facts(
    events: Sequence[AgentEvent],
) -> dict[str, Any]:
    explicit_ui_selections: dict[str, Any] = {}
    last_browser_effect: dict[str, Any] | None = None

    for event in sorted(events, key=lambda item: item.sequence):
        if event.event_type == "user_message":
            admitted = event.payload.get("user_ui_selections")
            if isinstance(admitted, Mapping) and admitted:
                explicit_ui_selections = json.loads(
                    json.dumps(admitted, ensure_ascii=False, default=str)
                )
        elif event.event_type == "browser_tool_completed":
            status = str(event.payload.get("status") or "").strip().lower()
            effect = event.payload.get("effect")
            effect_status = (
                str(effect.get("status") or "").strip().lower()
                if isinstance(effect, Mapping)
                else ""
            )
            if status in {"succeeded", "success", "completed", "ok"} or effect_status == "applied":
                last_browser_effect = {
                    "event_id": event.event_id,
                    "turn_id": event.turn_id,
                    "tool_name": event.payload.get("tool_name"),
                    "status": event.payload.get("status"),
                    "effect": json.loads(
                        json.dumps(effect or {}, ensure_ascii=False, default=str)
                    ),
                }

    runtime_facts: dict[str, Any] = {}
    if last_browser_effect is not None:
        runtime_facts["last_browser_effect"] = last_browser_effect
    return {
        "explicit_ui_selections": explicit_ui_selections,
        "authoritative_runtime_facts": runtime_facts,
    }


@dataclass(frozen=True, slots=True)
class ConversationCompactionPlan:
    should_summarize: bool
    events_to_summarize: tuple[AgentEvent, ...]
    recent_events: tuple[AgentEvent, ...]
    all_source_events: tuple[AgentEvent, ...]


class ConversationMemoryPlanner:
    def __init__(self, *, estimator, controller_context_tokens: int) -> None:
        self.estimator = estimator
        self.controller_context_tokens = max(1, int(controller_context_tokens))

    def _event_tokens(self, event: AgentEvent) -> int:
        role = "user" if event.event_type == "user_message" else "assistant"
        return self.estimator.estimate(f"{role}: {event.payload.get('text', '')}")

    def plan(
        self,
        *,
        events: Sequence[AgentEvent],
        current_turn_id: str,
        previous: ConversationMemoryStateRecord | None,
    ) -> ConversationCompactionPlan:
        dialogue = _dialogue_events(events, current_turn_id=current_turn_id)
        previous_to = previous.covered_to_sequence if previous is not None else 0
        uncovered = [event for event in dialogue if event.sequence > previous_to]

        recent_budget = max(32, int(self.controller_context_tokens * 0.35))
        trigger_budget = max(recent_budget + 16, int(self.controller_context_tokens * 0.55))
        if sum(self._event_tokens(event) for event in uncovered) <= trigger_budget:
            return ConversationCompactionPlan(
                should_summarize=False,
                events_to_summarize=(),
                recent_events=tuple(uncovered),
                all_source_events=(),
            )

        recent_reversed: list[AgentEvent] = []
        used = 0
        for event in reversed(uncovered):
            cost = self._event_tokens(event)
            if recent_reversed and used + cost > recent_budget:
                break
            recent_reversed.append(event)
            used += cost
        recent = list(reversed(recent_reversed))
        recent_ids = {event.event_id for event in recent}
        to_summarize = [event for event in uncovered if event.event_id not in recent_ids]
        if not to_summarize:
            return ConversationCompactionPlan(False, (), tuple(uncovered), ())

        covered_to = to_summarize[-1].sequence
        sources = [
            event
            for event in events
            if event.sequence > 0
            and event.turn_id != current_turn_id
            and event.sequence <= covered_to
        ]
        return ConversationCompactionPlan(
            should_summarize=True,
            events_to_summarize=tuple(to_summarize),
            recent_events=tuple(recent),
            all_source_events=tuple(sources),
        )


class ConversationMemorySummarizer:
    def __init__(self, *, model_client: StageModelClient) -> None:
        self.model_client = model_client

    async def summarize(
        self,
        *,
        principal_id: str,
        session_id: str,
        turn_id: str,
        events_to_summarize: Sequence[AgentEvent],
        all_source_events: Sequence[AgentEvent],
        previous: ConversationMemoryStateRecord | None,
        authoritative_facts: Mapping[str, Any],
        stage_policy: LLMStagePolicy,
        model_name: str | None,
    ) -> ConversationMemoryStateRecord:
        if not events_to_summarize or not all_source_events:
            raise ConversationMemoryError("conversation memory requires durable source events")

        new_dialogue = [
            {
                "role": "user" if event.event_type == "user_message" else "assistant",
                "text": str(event.payload.get("text") or "").strip(),
            }
            for event in events_to_summarize
        ]
        previous_payload = (
            {
                "rolling_summary": previous.rolling_summary,
                "active_goal": previous.active_goal,
                "user_constraints": list(previous.user_constraints),
            }
            if previous is not None
            else None
        )
        schema = {
            "type": "object",
            "properties": {
                "rolling_summary": {"type": "string", "maxLength": 500},
                "active_goal": {"type": "string", "maxLength": 120},
                "user_constraints": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {"type": "string", "maxLength": 100},
                },
            },
            "required": ["rolling_summary", "active_goal", "user_constraints"],
            "additionalProperties": False,
        }
        messages = (
            {
                "role": "system",
                "content": (
                    "Compress only dialogue semantics for future conversational continuity. "
                    "This memory is NON-AUTHORITATIVE: do not assert knowledge-base facts, map facts, "
                    "tool results, or UI state as truth. Preserve only what the user explicitly asked, "
                    "corrected, constrained, or left unfinished. Assistant statements may be summarized "
                    "only as conversation history, never upgraded to verified facts. Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Previous memory:\n{json.dumps(previous_payload, ensure_ascii=False)}\n\n"
                    f"New older dialogue to merge:\n{json.dumps(new_dialogue, ensure_ascii=False)}"
                ),
            },
        )
        execution = stage_policy.for_stage("conversation_memory")
        call_id = str(uuid4())
        deadline_at = monotonic() + execution.timeout_seconds

        async def generate(attempt):
            remaining = deadline_at - monotonic()
            if remaining <= 0:
                raise TimeoutError("conversation memory model call deadline exceeded")
            request = ModelRequest(
                stage="conversation_memory",
                messages=messages,
                request_reasoning=False,
                model_name=model_name,
                temperature=0.0,
                call_id=call_id,
                attempt=attempt.protocol_attempt,
                timeout_seconds=remaining,
                response_schema=schema,
                audit_context={
                    "principal_id": principal_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                },
            )
            return (await self.model_client.complete(request)).content

        try:
            payload = await execute_structured_candidate(
                generate=generate,
                validate=self._parse,
            )
        except StructuredCandidateProtocolError as exc:
            raise ConversationMemoryError(
                "conversation memory failed structured output contract"
            ) from exc

        source_rows = _source_rows(all_source_events)
        version = 1 if previous is None else previous.summary_version + 1
        memory_id = "memory-" + _canonical_hash(
            {
                "principal_id": principal_id,
                "session_id": session_id,
                "summary_version": version,
            }
        )
        return ConversationMemoryStateRecord(
            memory_id=memory_id,
            principal_id=principal_id,
            session_id=session_id,
            summary_version=version,
            covered_from_sequence=min(event.sequence for event in all_source_events),
            covered_to_sequence=max(event.sequence for event in all_source_events),
            rolling_summary=payload["rolling_summary"],
            active_goal=payload["active_goal"],
            user_constraints=tuple(payload["user_constraints"]),
            explicit_ui_selections=dict(
                authoritative_facts.get("explicit_ui_selections") or {}
            ),
            authoritative_runtime_facts=dict(
                authoritative_facts.get("authoritative_runtime_facts") or {}
            ),
            source_event_ids=tuple(event.event_id for event in all_source_events),
            source_hash=_canonical_hash(source_rows),
        )

    @staticmethod
    def _parse(content: str | None) -> dict[str, Any]:
        payload = extract_json_object(content)
        summary = payload.get("rolling_summary")
        goal = payload.get("active_goal")
        constraints = payload.get("user_constraints")
        if not isinstance(summary, str) or len(summary) > 500:
            raise ValueError("conversation memory rolling_summary is invalid")
        if not isinstance(goal, str) or len(goal) > 120:
            raise ValueError("conversation memory active_goal is invalid")
        if (
            not isinstance(constraints, list)
            or len(constraints) > 6
            or not all(isinstance(item, str) and len(item) <= 100 for item in constraints)
        ):
            raise ValueError("conversation memory user_constraints are invalid")
        return {
            "rolling_summary": summary.strip(),
            "active_goal": goal.strip(),
            "user_constraints": [item.strip() for item in constraints if item.strip()],
        }
