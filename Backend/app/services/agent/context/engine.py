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


def _empty_turn_runtime_facts(turn_id: str | None) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "controller_actions": [],
        "tool_calls": [],
        "clarification": None,
        "publication_state": None,
        "review_verdict": None,
        "map_facts": [],
    }


def _extract_turn_runtime_facts(
    events: Sequence[AgentEvent], turn_id: str | None
) -> dict[str, Any]:
    """Extract authoritative execution facts for one explicitly identified turn."""
    facts = _empty_turn_runtime_facts(turn_id)
    if not turn_id:
        return facts
    turn_events = [ev for ev in events if getattr(ev, "turn_id", None) == turn_id]
    if not turn_events:
        return facts

    controller_actions: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    clarification: dict[str, Any] | None = None
    publication_state: str | None = None
    review_verdict: str | None = None
    map_facts: list[dict[str, Any]] = []

    for ev in turn_events:
        t = ev.event_type
        p = ev.payload or {}
        if t == "controller_decision":
            action_name = p.get("tool_name") or p.get("action")
            if action_name:
                controller_actions.append(str(action_name))
        elif t == "tool_started":
            tool_calls.append({"tool": p.get("tool_name"), "status": "started", "call_id": p.get("tool_call_id")})
        elif t == "tool_completed":
            call = next((tc for tc in tool_calls if tc.get("call_id") == p.get("tool_call_id")), None)
            if call is None:
                call = {"tool": p.get("tool_name"), "call_id": p.get("tool_call_id")}
                tool_calls.append(call)
            call["status"] = p.get("status", "completed")
            if "error" in p:
                call["error"] = p["error"]
        elif t == "browser_tool_completed":
            map_facts.append({"tool": p.get("tool_name"), "status": p.get("status"), "effect": p.get("effect")})
            for call in tool_calls:
                if call.get("call_id") == p.get("tool_call_id"):
                    call["status"] = p.get("status", "completed")
                    call["source"] = "browser_receipt"
        elif t in ("clarification_requested", "clarify"):
            clarification = {"requested": True, "details": p}
        elif t == "publication_completed":
            publication_state = str(p.get("state") or "")
        elif t == "review_completed":
            review_verdict = str(p.get("verdict") or "")

    facts.update({
        "controller_actions": controller_actions,
        "tool_calls": tool_calls,
        "clarification": clarification,
        "publication_state": publication_state,
        "review_verdict": review_verdict,
        "map_facts": map_facts,
    })
    return facts


def extract_previous_turn_runtime_facts(events: Sequence[AgentEvent]) -> dict[str, Any]:
    """Extract facts from the most recently represented turn (legacy helper)."""
    turn_id = next(
        (getattr(ev, "turn_id", None) for ev in reversed(events) if getattr(ev, "turn_id", None)),
        None,
    )
    if not turn_id:
        return {}
    return _extract_turn_runtime_facts(events, turn_id)


def extract_scoped_runtime_facts(
    events: Sequence[AgentEvent], *, current_turn_id: str
) -> dict[str, Any]:
    """Return explicitly namespaced facts for current and immediately prior turns."""
    previous_turn_id = next(
        (
            getattr(ev, "turn_id", None)
            for ev in reversed(events)
            if getattr(ev, "turn_id", None) and getattr(ev, "turn_id", None) != current_turn_id
        ),
        None,
    )
    return {
        "current_turn": _extract_turn_runtime_facts(events, current_turn_id),
        "previous_turn": _extract_turn_runtime_facts(events, previous_turn_id),
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
        current_turn_id: str | None = None,
    ) -> ContextFrame:
        """Construct a structured ContextFrame from session facts and runtime inputs."""
        conv_list: list[dict[str, Any]] = []
        source_event_ids: list[str] = []

        for ev in events:
            source_event_ids.append(ev.event_id)
            if ev.event_type in {"user_message", "assistant_message"}:
                if ev.event_type == "user_message" and current_turn_id and ev.turn_id == current_turn_id:
                    continue
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
                "publication_token_cost": ev.get("publication_token_cost"),
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
                    "publication_token_cost": ev.get("publication_token_cost"),
                })

        runtime_facts = (
            extract_scoped_runtime_facts(events, current_turn_id=current_turn_id)
            if current_turn_id is not None
            else extract_previous_turn_runtime_facts(events)
        )
        admitted_metadata = dict(metadata or {})
        browser_observations = admitted_metadata.get("browser_observations") or {}
        user_ui_selections = admitted_metadata.get("user_ui_selections") or {}
        client_hints = admitted_metadata.get("client_hints") or {}

        return ContextFrame.create(
            session={"session_id": session_id, "principal_id": principal_id},
            user_question=question,
            spatial=spatial_context or {},
            conversation=conv_list,
            evidence_memory=list(evidence_memory),
            working_evidence=list(working_evidence),
            evidence_catalog=catalog,
            runtime_facts=runtime_facts,
            browser_observations=browser_observations,
            user_ui_selections=user_ui_selections,
            client_hints=client_hints,
            runtime_capabilities=tool_contracts or {},
            source_event_ids=source_event_ids,
            metadata={},
        )

    def project_for_controller(
        self,
        frame: ContextFrame,
        *,
        tool_contracts_text: str,
        tool_names: str,
        available_capabilities: Sequence[str] = (),
        available_control_actions: Sequence[str] = (),
        publication_evidence_budget: Mapping[str, Any] | None = None,
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
            user_ui_selections=frame.user_ui_selections,
            client_hints=frame.client_hints,
            map_context=trimmed_map,
            tool_contracts_text=tool_contracts_text,
            tool_names=tool_names,
            available_capabilities=tuple(available_capabilities),
            available_control_actions=tuple(available_control_actions),
            publication_evidence_budget=publication_evidence_budget or {},
            estimated_tokens=tokens,
        )

        session_id = str(frame.session.get("session_id") or "")
        turn_id = "current"
        current_facts = frame.runtime_facts.get("current_turn") if isinstance(frame.runtime_facts, Mapping) else None
        if isinstance(current_facts, Mapping) and current_facts.get("turn_id"):
            turn_id = str(current_facts["turn_id"])
        elif frame.conversation:
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
