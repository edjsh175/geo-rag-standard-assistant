"""ContextEngine: converts ContextFrame into budgeted role projections and auditable snapshots."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from app.services.agent.context.budget import ContextBudgetManager
from app.services.agent.context.frame import ContextFrame, _thaw
from app.services.agent.context.projection import (
    AnswerContextProjection,
    ControllerContextProjection,
    ReviewerContextProjection,
)
from app.services.agent.context.snapshot import ContextSnapshot
from app.services.agent.events import AgentEvent


def extract_previous_turn_runtime_facts(events: Sequence[AgentEvent]) -> dict[str, Any]:
    """Extract authoritative execution facts from the immediate previous turn."""
    if not events:
        return {}
    turn_ids = []
    for ev in reversed(events):
        tid = getattr(ev, "turn_id", None)
        if tid and tid not in turn_ids:
            turn_ids.append(tid)
    if not turn_ids:
        return {}
    target_turn_id = turn_ids[0]
    prev_events = [ev for ev in events if getattr(ev, "turn_id", None) == target_turn_id]
    if not prev_events:
        return {}

    controller_actions: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    clarification: dict[str, Any] | None = None
    publication_state: str | None = None
    review_verdict: str | None = None
    map_facts: list[dict[str, Any]] = []

    for ev in prev_events:
        t = ev.event_type
        p = ev.payload or {}
        if t == "controller_decision":
            action_name = p.get("tool_name") or p.get("action")
            if action_name:
                controller_actions.append(str(action_name))
        elif t == "tool_started":
            tool_calls.append({"tool": p.get("tool_name"), "status": "started", "call_id": p.get("tool_call_id")})
        elif t == "tool_completed":
            for tc in tool_calls:
                if tc.get("call_id") == p.get("tool_call_id"):
                    tc["status"] = p.get("status", "completed")
                    if "error" in p:
                        tc["error"] = p["error"]
        elif t == "browser_tool_completed":
            map_facts.append({"tool": p.get("tool_name"), "status": p.get("status"), "effect": p.get("effect")})
        elif t in ("clarification_requested", "clarify"):
            clarification = {"requested": True, "details": p}
        elif t == "publication_completed":
            publication_state = str(p.get("state") or "")
        elif t == "review_completed":
            review_verdict = str(p.get("verdict") or "")

    return {
        "turn_id": target_turn_id,
        "controller_actions": controller_actions,
        "tool_calls": tool_calls,
        "clarification": clarification,
        "publication_state": publication_state,
        "review_verdict": review_verdict,
        "map_facts": map_facts,
    }


class ContextEngine:
    """Orchestrates structured context creation, role projection, and snapshot recording."""

    def __init__(self, budget_manager: ContextBudgetManager | None = None) -> None:
        self.budget_manager = budget_manager or ContextBudgetManager()

    def build_frame(
        self,
        *,
        session_id: str,
        principal_id: str,
        question: str,
        events: Sequence[AgentEvent],
        working_evidence: Sequence[Mapping[str, Any]],
        evidence_memory: Sequence[Mapping[str, Any]] = (),
        spatial_context: Mapping[str, Any] | None = None,
        tool_contracts: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ContextFrame:
        """Construct a structured ContextFrame from session facts and runtime inputs."""
        conv_list: list[dict[str, Any]] = []
        source_event_ids: list[str] = []

        for ev in events:
            source_event_ids.append(ev.event_id)
            if ev.event_type in {"user_message", "assistant_message"}:
                text = ev.payload.get("text")
                if isinstance(text, str) and text.strip():
                    conv_list.append({
                        "role": "user" if ev.event_type == "user_message" else "assistant",
                        "text": text.strip(),
                        "turn_id": ev.turn_id,
                        "event_id": ev.event_id,
                    })

        # Assemble unified evidence catalog
        catalog: list[dict[str, Any]] = []
        for ev in working_evidence:
            catalog.append({
                "evidence_id": ev.get("evidence_id"),
                "citation_id": ev.get("citation_id"),
                "title": ev.get("title", ""),
                "excerpt": (ev.get("excerpt") or ev.get("text") or "")[:200],
                "source_type": ev.get("source_type", "working"),
                "selectable_for_snapshot": True,
            })
        for ev in evidence_memory:
            eid = ev.get("evidence_id")
            if not any(c["evidence_id"] == eid for c in catalog):
                catalog.append({
                    "evidence_id": eid,
                    "citation_id": ev.get("citation_id"),
                    "title": ev.get("title", ""),
                    "excerpt": (ev.get("excerpt") or ev.get("text") or "")[:200],
                    "source_type": "historical",
                    "selectable_for_snapshot": True,
                })

        runtime_facts = extract_previous_turn_runtime_facts(events)
        if metadata:
            runtime_facts.update({k: v for k, v in metadata.items() if k not in runtime_facts})

        return ContextFrame.create(
            session={"session_id": session_id, "principal_id": principal_id},
            user_question=question,
            spatial=spatial_context or {},
            conversation=conv_list,
            evidence_memory=list(evidence_memory),
            working_evidence=list(working_evidence),
            evidence_catalog=catalog,
            runtime_facts=runtime_facts,
            runtime_capabilities=tool_contracts or {},
            source_event_ids=source_event_ids,
            metadata=metadata or {},
        )

    def project_for_controller(
        self,
        frame: ContextFrame,
        *,
        tool_contracts_text: str,
        tool_names: str,
        available_capabilities: Sequence[str] = (),
        available_control_actions: Sequence[str] = (),
    ) -> tuple[ControllerContextProjection, ContextSnapshot]:
        """Produce a budgeted projection and audit snapshot for Controller decisions."""
        conv_lines: list[str] = []
        for msg in frame.conversation:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            if text:
                conv_lines.append(f"{role}: {text}")

        summary, trimmed_evidence, trimmed_map, tokens = self.budget_manager.trim_controller_context(
            question=frame.user_question,
            conversation_lines=conv_lines,
            working_evidence=frame.working_evidence,
            map_context=frame.spatial if frame.spatial else None,
            tool_contracts_text=tool_contracts_text,
        )

        projection = ControllerContextProjection(
            user_question=frame.user_question,
            conversation_text=summary,
            working_evidence=tuple(trimmed_evidence),
            evidence_catalog=frame.evidence_catalog,
            runtime_facts=frame.runtime_facts,
            map_context=trimmed_map,
            tool_contracts_text=tool_contracts_text,
            tool_names=tool_names,
            available_capabilities=tuple(available_capabilities),
            available_control_actions=tuple(available_control_actions),
            estimated_tokens=tokens,
        )

        session_id = str(frame.session.get("session_id") or "")
        turn_id = "current"
        if frame.conversation:
            turn_id = str(frame.conversation[-1].get("turn_id") or "current")

        snapshot = ContextSnapshot.create(
            stage="controller",
            session_id=session_id,
            turn_id=turn_id,
            frame_payload=frame.to_dict(),
            projection_sections=projection.sections(),
            source_event_ids=frame.source_event_ids,
            token_usage_estimate=tokens,
        )
        return projection, snapshot

    def project_for_answer(
        self,
        frame: ContextFrame,
        *,
        conversation_summary: str,
    ) -> tuple[AnswerContextProjection, ContextSnapshot]:
        """Produce a budgeted projection and audit snapshot for Answer generation."""
        summary, trimmed_evidence, trimmed_map, tokens = self.budget_manager.trim_answer_context(
            question=frame.user_question,
            conversation_summary=conversation_summary,
            evidence_items=frame.working_evidence,
            map_context=frame.spatial if frame.spatial else None,
        )

        projection = AnswerContextProjection(
            user_question=frame.user_question,
            conversation_summary=summary,
            citable_evidence=tuple(trimmed_evidence),
            map_context=trimmed_map,
            estimated_tokens=tokens,
        )

        session_id = str(frame.session.get("session_id") or "")
        turn_id = "current"
        if frame.conversation:
            turn_id = str(frame.conversation[-1].get("turn_id") or "current")

        snapshot = ContextSnapshot.create(
            stage="answer",
            session_id=session_id,
            turn_id=turn_id,
            frame_payload=frame.to_dict(),
            projection_sections=projection.sections(),
            source_event_ids=frame.source_event_ids,
            token_usage_estimate=tokens,
        )
        return projection, snapshot

    def project_for_reviewer(
        self,
        frame: ContextFrame,
        *,
        draft_answer: str,
    ) -> tuple[ReviewerContextProjection, ContextSnapshot]:
        """Produce a projection and audit snapshot for Reviewer verification."""
        tokens = (
            self.budget_manager.estimate_tokens(frame.user_question)
            + self.budget_manager.estimate_tokens(draft_answer)
            + self.budget_manager.estimate_tokens(json.dumps(list(frame.working_evidence), default=str))
        )

        projection = ReviewerContextProjection(
            user_question=frame.user_question,
            draft_answer=draft_answer,
            citable_evidence=frame.working_evidence,
            estimated_tokens=tokens,
        )

        session_id = str(frame.session.get("session_id") or "")
        turn_id = "current"
        if frame.conversation:
            turn_id = str(frame.conversation[-1].get("turn_id") or "current")

        snapshot = ContextSnapshot.create(
            stage="reviewer",
            session_id=session_id,
            turn_id=turn_id,
            frame_payload=frame.to_dict(),
            projection_sections=projection.sections(),
            source_event_ids=frame.source_event_ids,
            token_usage_estimate=tokens,
        )
        return projection, snapshot
