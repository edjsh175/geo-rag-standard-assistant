"""Controller context/action-surface projection boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.services.agent.context import ContextEngine
from app.services.agent.controller_protocol import ExecutableActionState
from app.services.agent.session import AgentSession
from app.services.agent.tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class ControllerTurnProjection:
    frame: Any
    controller_projection: Any
    controller_snapshot: Any
    action_state: ExecutableActionState
    map_context: Mapping[str, Any] | None
    working_evidence_dicts: tuple[dict[str, Any], ...]
    all_ledger_items: tuple[Any, ...]


class ContextProjector:
    """Build the deterministic Controller input surface for one planning step."""

    def __init__(self, context_engine: ContextEngine) -> None:
        self.context_engine = context_engine

    def project_controller(
        self,
        *,
        session: AgentSession,
        principal_id: str,
        turn_id: str,
        question: str,
        request_context: Mapping[str, Any],
        registry: ToolRegistry,
        provider_health: Mapping[str, bool],
        reviewer_enabled: bool,
    ) -> ControllerTurnProjection:
        working_items = session.evidence_ledger.working_evidence(turn_id=turn_id)
        working_ev_dicts = tuple(
            {
                "evidence_id": item.evidence_id,
                "citation_id": item.citation_id,
                "title": item.title,
                "excerpt": item.text[:800],
                "score": item.score,
                "publication_token_cost": self.context_engine.budget_manager.estimate_publication_evidence_tokens([item]),
            }
            for item in working_items
        )
        historical_items = session.evidence_ledger.historical_items(current_turn_id=turn_id)
        historical_ev_dicts = tuple(
            {
                "evidence_id": item.evidence_id,
                "citation_id": item.citation_id,
                "title": item.title,
                "excerpt": item.text[:800],
                "score": item.score,
                "publication_token_cost": self.context_engine.budget_manager.estimate_publication_evidence_tokens([item]),
            }
            for item in historical_items
        )

        browser_observations = request_context.get("browser_observations")
        raw_map_context = (
            browser_observations.get("map_context")
            if isinstance(browser_observations, Mapping)
            else None
        )
        map_context = raw_map_context if isinstance(raw_map_context, Mapping) else None

        frame = self.context_engine.build_frame(
            session_id=session.session_id,
            principal_id=principal_id,
            question=question,
            events=session.events,
            working_evidence=working_ev_dicts,
            evidence_memory=historical_ev_dicts,
            spatial_context=map_context,
            metadata=request_context,
            current_turn_id=turn_id,
            conversation_memory=session.conversation_memory,
            identity_resolution=session.identity_resolution,
        )

        all_ledger_items = tuple(session.evidence_ledger.all_items())
        selectable_ids = tuple(item.evidence_id for item in all_ledger_items)
        evidence_id_aliases = {
            str(item.citation_id): item.evidence_id
            for item in all_ledger_items
            if getattr(item, "citation_id", None)
        }
        action_state = ExecutableActionState.compute(
            registry=registry,
            map_context=map_context,
            identity_resolution=frame.identity_resolution,
            has_evidence=bool(selectable_ids),
            selectable_evidence_ids=selectable_ids,
            evidence_id_aliases=evidence_id_aliases,
            provider_health=provider_health,
        )

        tool_specs = registry.specs_for(action_state.available_capabilities)
        tool_contracts_text = "\n".join(
            f"- {spec.name}: {spec.description}" for spec in tool_specs
        ) if tool_specs else ""
        tool_names = ", ".join(spec.name for spec in tool_specs) if tool_specs else ""
        publication_budget = self.context_engine.budget_manager.check_evidence_selection(
            question=question,
            items=(),
            reviewer_enabled=reviewer_enabled,
        ).to_dict()
        publication_budget.pop("allowed", None)
        publication_budget.pop("evidence_tokens", None)
        publication_budget["reviewer_enabled"] = reviewer_enabled

        controller_projection, controller_snapshot = self.context_engine.project_for_controller(
            frame,
            tool_contracts_text=tool_contracts_text,
            tool_names=tool_names,
            available_capabilities=tuple(action_state.available_capabilities),
            available_control_actions=tuple(action_state.available_control_actions),
            publication_evidence_budget=publication_budget,
        )

        return ControllerTurnProjection(
            frame=frame,
            controller_projection=controller_projection,
            controller_snapshot=controller_snapshot,
            action_state=action_state,
            map_context=map_context,
            working_evidence_dicts=working_ev_dicts,
            all_ledger_items=all_ledger_items,
        )


__all__ = ["ControllerTurnProjection", "ContextProjector"]
