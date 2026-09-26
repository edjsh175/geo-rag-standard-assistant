"""Historical Context Reconstruction authority for GeoAI decisions and snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence

from app.models.agent_context import ContextSnapshotRecord
from app.services.agent.context.budget import ContextBudgetManager
from app.services.agent.context.engine import ContextEngine
from app.services.agent.context.frame import ContextFrame
from app.services.agent.context.projection import ControllerContextProjection
from app.services.agent.events import AgentEvent


@dataclass(frozen=True)
class ContextReconstructionResult:
    """Outcome of historical context reconstruction and hash verification."""

    matched: bool
    stage: str
    snapshot_id: str
    expected_projection_hash: str
    reconstructed_projection_hash: str
    expected_frame_hash: str
    reconstructed_frame_hash: str
    sections_matched: bool
    differing_sections: tuple[str, ...] = ()
    reconstructed_projection: ControllerContextProjection | None = None
    reconstructed_frame: ContextFrame | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


class GeoAIHistoricalContextReconstructor:
    """Replays durable session events and exact evidence to reconstruct past ContextFrames and Projections."""

    def __init__(self, context_engine: ContextEngine | None = None) -> None:
        self.context_engine = context_engine or ContextEngine()

    def reconstruct_controller(
        self,
        *,
        snapshot: ContextSnapshotRecord,
        events: Sequence[AgentEvent],
        session_info: Mapping[str, Any] | None = None,
        working_evidence: Sequence[Mapping[str, Any]] = (),
        evidence_catalog: Sequence[Mapping[str, Any]] = (),
        user_question: str = "",
        conversation_memory: Any = None,
        tool_contracts_text: str = "",
        tool_names: str = "",
        available_capabilities: Sequence[str] = (),
        available_control_actions: Sequence[str] = (),
        spatial_context: Mapping[str, Any] | None = None,
        publication_evidence_budget: Mapping[str, Any] | None = None,
    ) -> ContextReconstructionResult:
        # 1. Filter events up to source_event_ids if provided
        filtered_events = list(events)
        if snapshot.source_event_ids:
            source_set = set(snapshot.source_event_ids)
            filtered_events = [e for e in events if e.event_id in source_set]

        # 2. Extract action surface identity from snapshot payload if available
        payload = snapshot.snapshot_payload or {}
        action_identity = payload.get("action_surface_identity") or {}
        effective_capabilities = tuple(action_identity.get("available_capabilities") or available_capabilities)
        effective_control_actions = tuple(action_identity.get("available_control_actions") or available_control_actions)
        effective_tool_names = str(action_identity.get("tool_names") or tool_names)

        # 3. Rebuild ContextFrame
        frame = self.context_engine.build_frame(
            session_id=snapshot.session_id,
            principal_id=snapshot.principal_id,
            question=user_question,
            events=filtered_events,
            working_evidence=working_evidence,
            evidence_memory=evidence_catalog,
            spatial_context=spatial_context,
            current_turn_id=snapshot.turn_id,
            conversation_memory=conversation_memory,
        )

        # 4. Project for controller
        proj, reconstructed_snap = self.context_engine.project_for_controller(
            frame,
            tool_contracts_text=tool_contracts_text,
            tool_names=effective_tool_names,
            available_capabilities=effective_capabilities,
            available_control_actions=effective_control_actions,
            publication_evidence_budget=publication_evidence_budget,
        )

        # 5. Verify projection hash and frame hash
        expected_frame_hash = str(payload.get("frame_hash") or "")
        expected_proj_hash = snapshot.projection_hash
        frame_matched = not expected_frame_hash or (reconstructed_snap.frame_hash == expected_frame_hash)
        proj_matched = reconstructed_snap.projection_hash == expected_proj_hash

        # Check section-level differences
        expected_sections = {
            s["name"]: s["hash"]
            for s in payload.get("sections", [])
            if isinstance(s, dict) and "name" in s and "hash" in s
        }
        reconstructed_sections = {
            s.name: s.content_hash for s in reconstructed_snap.sections
        }
        differing = []
        for name, exp_h in expected_sections.items():
            if reconstructed_sections.get(name) != exp_h:
                differing.append(name)

        overall_matched = proj_matched and frame_matched and (not differing)

        return ContextReconstructionResult(
            matched=overall_matched,
            stage=snapshot.stage,
            snapshot_id=snapshot.snapshot_id,
            expected_projection_hash=expected_proj_hash,
            reconstructed_projection_hash=reconstructed_snap.projection_hash,
            expected_frame_hash=expected_frame_hash,
            reconstructed_frame_hash=reconstructed_snap.frame_hash,
            sections_matched=not differing,
            differing_sections=tuple(differing),
            reconstructed_projection=proj,
            reconstructed_frame=frame,
            diagnostics={
                "differing_sections": differing,
                "reconstructed_sections": reconstructed_sections,
                "expected_sections": expected_sections,
            },
        )
