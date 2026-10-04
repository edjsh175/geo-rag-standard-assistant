"""Deterministic tool-dispatch orchestration boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.agent.controller_protocol import ControllerDecision, TOOL_CALL_ACTION
from app.services.agent.event_projection import safe_error, tool_result_summary
from app.services.agent.events import AgentEvent
from app.services.agent.identity import EntityCandidateRef, IdentityResolution
from app.services.agent.tool_runtime import (
    RegionSelectionAmbiguous,
    RegionSelectionNotFound,
    RetrievalUnavailableError,
    ResourceFuseExceeded,
    ToolCall,
    ToolExecutionError,
    ToolObservation,
    ToolRuntime,
)


@dataclass(frozen=True, slots=True)
class ToolExecutionOutcome:
    call: ToolCall
    observation: ToolObservation | None
    events: tuple[AgentEvent, ...]
    terminal_error: str | None = None
    persist_evidence: bool = False
    identity_resolution: IdentityResolution | None = None


class ToolExecutionCoordinator:
    """Validate and execute one Controller-selected tool call.

    This boundary owns tool lifecycle event construction and deterministic
    exception taxonomy. It deliberately does not decide the next Agent action,
    publish user-visible content, or persist evidence/session state.
    """

    def __init__(self, tool_runtime: ToolRuntime) -> None:
        self.tool_runtime = tool_runtime

    @staticmethod
    def _to_tool_call(call: ToolCall | ControllerDecision) -> ToolCall:
        """Cross the planning→execution boundary exactly once.

        ControllerDecision is the planning protocol; ToolCall is the only
        execution protocol accepted by ToolRuntime.
        """
        if isinstance(call, ToolCall):
            return call
        if call.action != TOOL_CALL_ACTION or not call.tool or not call.tool_call_id:
            raise TypeError("ToolExecutionCoordinator requires an executable tool decision")
        return ToolCall(
            tool_call_id=call.tool_call_id,
            name=call.tool,
            arguments=dict(call.arguments),
        )

    async def execute(
        self,
        *,
        turn_id: str,
        session_id: str,
        trace_id: str,
        call: ToolCall | ControllerDecision,
    ) -> ToolExecutionOutcome:
        runtime_call = self._to_tool_call(call)
        try:
            canonical_call = self.tool_runtime.validate_call(call=runtime_call)
        except ToolExecutionError as exc:
            observation = ToolObservation(
                tool_call_id=runtime_call.tool_call_id,
                tool_name=runtime_call.name,
                status="denied",
                payload={"error": str(exc)},
                is_terminal=False,
            )
            return ToolExecutionOutcome(
                call=runtime_call,
                observation=observation,
                events=(
                    AgentEvent(
                        event_type="tool_completed",
                        session_id=session_id,
                        turn_id=turn_id,
                        trace_id=trace_id,
                        payload={
                            "tool_name": runtime_call.name,
                            "tool_call_id": runtime_call.tool_call_id,
                            "status": "denied",
                            "error": safe_error("TOOL_INVALID_ARGUMENTS"),
                            "result_summary": {},
                        },
                    ),
                ),
            )

        lifecycle_events = [
            AgentEvent(
                event_type="controller_decision",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={
                    "tool_name": canonical_call.name,
                    "tool_call_id": canonical_call.tool_call_id,
                },
            ),
            AgentEvent(
                event_type="tool_started",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={
                    "tool_name": canonical_call.name,
                    "tool_call_id": canonical_call.tool_call_id,
                    "arguments": dict(canonical_call.arguments),
                },
            ),
        ]

        try:
            observation = await self.tool_runtime.execute_validated(
                turn_id=turn_id,
                call=canonical_call,
            )
        except RegionSelectionAmbiguous as exc:
            identity_resolution = IdentityResolution(
                status="ambiguous",
                candidate_refs=tuple(
                    EntityCandidateRef(
                        entity_ref=f"region:{str(item.get('adcode') or '').strip()}",
                        display_name=(
                            f"{str(item.get('region_name') or '').strip()} "
                            f"({str(item.get('adcode') or '').strip()})"
                        ).strip(),
                    )
                    for item in exc.candidates
                    if str(item.get("adcode") or "").strip()
                    and str(item.get("region_name") or "").strip()
                ),
            )
            observation = ToolObservation(
                tool_call_id=canonical_call.tool_call_id,
                tool_name=canonical_call.name,
                status="failed",
                payload={
                    "error_code": "REGION_AMBIGUOUS",
                    "region_name": exc.region_name,
                    "candidates": [dict(item) for item in exc.candidates],
                },
                is_terminal=False,
            )
            lifecycle_events.append(
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": observation.tool_name,
                        "tool_call_id": observation.tool_call_id,
                        "status": observation.status,
                        "error": safe_error("TOOL_FAILED"),
                        "result_summary": {},
                    },
                )
            )
            return ToolExecutionOutcome(
                call=canonical_call,
                observation=observation,
                events=tuple(lifecycle_events),
                identity_resolution=identity_resolution,
            )
        except RegionSelectionNotFound as exc:
            observation = ToolObservation(
                tool_call_id=canonical_call.tool_call_id,
                tool_name=canonical_call.name,
                status="failed",
                payload={"error_code": "REGION_NOT_FOUND", "error": str(exc)},
                is_terminal=False,
            )
            lifecycle_events.append(
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": observation.tool_name,
                        "tool_call_id": observation.tool_call_id,
                        "status": observation.status,
                        "error": safe_error("TOOL_FAILED"),
                        "result_summary": {},
                    },
                )
            )
            return ToolExecutionOutcome(
                call=canonical_call,
                observation=observation,
                events=tuple(lifecycle_events),
            )
        except ResourceFuseExceeded:
            lifecycle_events.append(
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": canonical_call.name,
                        "tool_call_id": canonical_call.tool_call_id,
                        "status": "failed",
                        "error": safe_error("TOOL_FAILED"),
                        "result_summary": {},
                    },
                )
            )
            return ToolExecutionOutcome(
                call=canonical_call,
                observation=None,
                events=tuple(lifecycle_events),
                terminal_error="resource_fuse",
            )
        except RetrievalUnavailableError:
            lifecycle_events.append(
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": canonical_call.name,
                        "tool_call_id": canonical_call.tool_call_id,
                        "status": "failed",
                        "error": safe_error("TOOL_UNAVAILABLE"),
                        "result_summary": {},
                    },
                )
            )
            return ToolExecutionOutcome(
                call=canonical_call,
                observation=None,
                events=tuple(lifecycle_events),
                terminal_error="retrieval_unavailable",
            )
        except ToolExecutionError as exc:
            observation = ToolObservation(
                tool_call_id=canonical_call.tool_call_id,
                tool_name=canonical_call.name,
                status="denied",
                payload={"error": str(exc)},
                is_terminal=False,
            )
            lifecycle_events.append(
                AgentEvent(
                    event_type="tool_completed",
                    session_id=session_id,
                    turn_id=turn_id,
                    trace_id=trace_id,
                    payload={
                        "tool_name": observation.tool_name,
                        "tool_call_id": observation.tool_call_id,
                        "status": observation.status,
                        "error": safe_error(
                            "TOOL_TIMEOUT"
                            if str(exc).startswith("TOOL_TIMEOUT:")
                            else "TOOL_FAILED"
                        ),
                        "result_summary": {},
                    },
                )
            )
            return ToolExecutionOutcome(
                call=canonical_call,
                observation=observation,
                events=tuple(lifecycle_events),
            )

        lifecycle_events.append(
            AgentEvent(
                event_type="tool_completed",
                session_id=session_id,
                turn_id=turn_id,
                trace_id=trace_id,
                payload={
                    "tool_name": observation.tool_name,
                    "tool_call_id": observation.tool_call_id,
                    "status": observation.status,
                    "result_summary": tool_result_summary(
                        observation.tool_name,
                        observation,
                    ),
                },
            )
        )
        return ToolExecutionOutcome(
            call=canonical_call,
            observation=observation,
            events=tuple(lifecycle_events),
            persist_evidence=True,
        )


__all__ = ["ToolExecutionCoordinator", "ToolExecutionOutcome"]
