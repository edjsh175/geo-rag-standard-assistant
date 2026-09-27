"""Deterministic execution boundary for Controller-selected Agent tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable, Mapping

from app.services.agent.evidence import EvidenceLedger
from app.services.agent.tool_policy import (
    ToolExecutionContext,
    ToolPolicy,
    ToolPolicyViolation,
)
from app.services.agent.tools import ToolRegistry, build_default_tool_registry
from app.models.search_models import MetadataFilter, SpatialFilter
from app.services.rag.contracts import RetrievalPort, RetrievalQuery


class ToolExecutionError(ValueError):
    """Raised when a tool call violates its explicit input contract."""


class ResourceFuseExceeded(RuntimeError):
    """Raised when a physical runtime safety limit has been exhausted."""


class RetrievalUnavailableError(RuntimeError):
    """Raised when every retrieval channel attempted for a tool call is unavailable."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool_call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolObservation:
    tool_call_id: str
    tool_name: str
    status: str
    payload: Mapping[str, Any]
    is_terminal: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalRequestConstraints:
    top_k: int = 10
    threshold: float = 0.7
    search_mode: str = "hybrid"
    use_rerank: bool = True
    metadata_filter: MetadataFilter | None = None
    spatial_filter: SpatialFilter | None = None


class ResourceFuse:
    """Physical guardrail shared by all Controller steps and tool types.

    This deliberately has no retrieval-specific counter. The fuse protects
    runtime resources; it does not decide whether further retrieval is useful.
    """

    def __init__(
        self,
        *,
        max_steps: int,
        max_elapsed_seconds: float,
        initial_steps: int = 0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds must be positive")
        if initial_steps < 0 or initial_steps > max_steps:
            raise ValueError("initial_steps must be between 0 and max_steps")
        self.max_steps = max_steps
        self.max_elapsed_seconds = max_elapsed_seconds
        self._clock = clock
        self._started_at = clock()
        self._steps = initial_steps

    @property
    def steps(self) -> int:
        return self._steps

    @property
    def deadline_at(self) -> float:
        return self._started_at + self.max_elapsed_seconds

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_at - self._clock())

    @property
    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self._steps)

    def consume_step(self, *, tool_name: str) -> None:
        self.ensure_within_limits()
        if self._steps >= self.max_steps:
            raise ResourceFuseExceeded(
                f"RESOURCE_FUSE: max controller/tool steps exceeded before {tool_name}"
            )
        self._steps += 1

    def ensure_within_limits(self) -> None:
        elapsed = self._clock() - self._started_at
        if elapsed > self.max_elapsed_seconds:
            raise ResourceFuseExceeded("RESOURCE_FUSE: max elapsed runtime exceeded")


class ToolRuntime:
    def __init__(
        self,
        *,
        retrieval_port: RetrievalPort,
        evidence_ledger: EvidenceLedger,
        registry: ToolRegistry | None = None,
        resource_fuse: ResourceFuse | None = None,
        retrieval_constraints: RetrievalRequestConstraints | None = None,
        spatial_service: Any | None = None,
        execution_context: ToolExecutionContext | None = None,
        policy: ToolPolicy | None = None,
    ) -> None:
        self.retrieval_port = retrieval_port
        self.evidence_ledger = evidence_ledger
        self.registry = registry or build_default_tool_registry()
        self.resource_fuse = resource_fuse
        self.retrieval_constraints = retrieval_constraints or RetrievalRequestConstraints()
        self.spatial_service = spatial_service
        self.execution_context = execution_context or ToolExecutionContext()
        self.policy = policy or ToolPolicy()

    def validate_call(self, *, call: ToolCall) -> ToolCall:
        """Return the one canonical schema-validated call used by events and execution."""
        from app.services.agent.tools import CONTROL_ACTION_NAMES
        if call.name in CONTROL_ACTION_NAMES:
            raise ToolExecutionError(f"'{call.name}' is a control action, not an executable tool")

        try:
            spec = self.registry.get(call.name)
            self.policy.authorize(
                spec=spec,
                tool_call_id=call.tool_call_id,
                context=self.execution_context,
            )
            timeout_seconds = self.policy.effective_timeout_seconds(
                spec=spec,
                runtime_remaining_seconds=(
                    self.resource_fuse.remaining_seconds
                    if self.resource_fuse is not None
                    else None
                ),
            )
        except (KeyError, ToolPolicyViolation) as exc:
            raise ToolExecutionError(str(exc)) from exc

        try:
            arguments = self.registry.validate(call.name, call.arguments)
        except (KeyError, ValueError) as exc:
            raise ToolExecutionError(str(exc)) from exc

        return ToolCall(
            tool_call_id=call.tool_call_id,
            name=call.name,
            arguments=arguments,
        )

    async def execute(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        return await self.execute_validated(turn_id=turn_id, call=self.validate_call(call=call))

    async def execute_validated(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        """Execute a call already returned by validate_call without revalidating it."""
        from app.services.agent.tools import CONTROL_ACTION_NAMES
        if call.name in CONTROL_ACTION_NAMES:
            raise ToolExecutionError("control action is not an executable tool")
        try:
            self.policy.authorize(
                spec=self.registry.get(call.name),
                tool_call_id=call.tool_call_id,
                context=self.execution_context,
            )
            timeout_seconds = self.policy.effective_timeout_seconds(
                spec=self.registry.get(call.name),
                runtime_remaining_seconds=(self.resource_fuse.remaining_seconds if self.resource_fuse else None),
            )
        except (KeyError, ToolPolicyViolation):
            raise ToolExecutionError("tool is unavailable or not authorized") from None

        if self.resource_fuse is not None:
            self.resource_fuse.consume_step(tool_name=call.name)

        try:
            observation = await asyncio.wait_for(
                self._execute_validated(turn_id=turn_id, call=call),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ToolExecutionError(
                f"TOOL_TIMEOUT: '{call.name}' exceeded {timeout_seconds:.3f}s"
            ) from exc

        if observation.status == "browser_execution_required":
            payload = dict(observation.payload)
            map_action = dict(payload.get("map_action") or {})
            map_action["timeout_seconds"] = timeout_seconds
            payload["map_action"] = map_action
            observation = ToolObservation(
                tool_call_id=observation.tool_call_id,
                tool_name=observation.tool_name,
                status=observation.status,
                payload=payload,
                is_terminal=observation.is_terminal,
            )

        if self.resource_fuse is not None:
            self.resource_fuse.ensure_within_limits()
        return observation

    async def _execute_validated(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        if call.name == "retrieve_kb":
            observation = await self._retrieve_kb(turn_id=turn_id, call=call)
        elif call.name == "search_evidence_memory":
            observation = self._search_evidence_memory(turn_id=turn_id, call=call)
        elif call.name == "reuse_evidence":
            observation = self._reuse_evidence(turn_id=turn_id, call=call)
        elif call.name in {
            "import_vector_dataset",
            "set_layer_visibility",
            "set_vector_style",
            "fit_vector_layer",
            "locate_map",
            "inspect_layer_features",
            "get_feature_geometry",
        }:
            observation = self._browser_action(call=call)
        elif call.name in {"query_spatial_relation", "spatial_overlay"}:
            observation = await self._spatial_operation(turn_id=turn_id, call=call)
        else:  # pragma: no cover - registry.get() already rejects this branch.
            raise KeyError(f"unknown tool: {call.name}")
        return observation

    @staticmethod
    def _browser_action(*, call: ToolCall) -> ToolObservation:
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="browser_execution_required",
            payload={
                "map_action": {
                    "type": call.name,
                    "target": "browser_map",
                    "payload": dict(call.arguments),
                }
            },
            is_terminal=True,
        )

    async def _retrieve_kb(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        query_text = str(call.arguments["query"]).strip()
        constraints = self.retrieval_constraints

        result = await self.retrieval_port.retrieve(
            RetrievalQuery(
                query_text=query_text,
                top_k=constraints.top_k,
                threshold=constraints.threshold,
                search_mode=constraints.search_mode,
                use_rerank=constraints.use_rerank,
                metadata_filter=constraints.metadata_filter,
                spatial_filter=constraints.spatial_filter,
            )
        )
        if result.diagnostics.is_fully_unavailable:
            channels = ", ".join(result.diagnostics.unavailable_channels)
            raise RetrievalUnavailableError(
                f"RETRIEVAL_UNAVAILABLE: all attempted channels unavailable ({channels})"
            )
        admitted = self.evidence_ledger.add_candidates(
            turn_id=turn_id,
            candidates=result.candidates,
        )
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="partial" if result.diagnostics.is_degraded else "ok",
            payload={
                "evidence_ids": [item.evidence_id for item in admitted],
                "candidate_count": len(result.candidates),
                "admitted_count": len(admitted),
                "embedding_available": result.embedding_available,
                "diagnostics": result.diagnostics,
                "unavailable_channels": list(result.diagnostics.unavailable_channels),
            },
        )

    async def _spatial_operation(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        if self.spatial_service is None:
            return ToolObservation(
                tool_call_id=call.tool_call_id,
                tool_name=call.name,
                status="failed",
                payload={"error": "spatial service is unavailable"},
            )
        try:
            if call.name == "query_spatial_relation":
                result = await self.spatial_service.query_relation(
                    left=call.arguments["left"],
                    right=call.arguments["right"],
                    relation=str(call.arguments["relation"]),
                )
            else:
                result = await self.spatial_service.overlay(
                    left=call.arguments["left"],
                    right=call.arguments["right"],
                    operation=str(call.arguments["operation"]),
                )
        except Exception as exc:
            return ToolObservation(
                tool_call_id=call.tool_call_id,
                tool_name=call.name,
                status="failed",
                payload={"error": str(exc)},
            )
        evidence = self.evidence_ledger.add_observation(
            turn_id=turn_id,
            source="postgis",
            observation_key=call.tool_call_id,
            title=f"PostGIS {call.name}",
            payload=result,
        )
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="ok",
            payload={"result": result, "evidence_id": evidence.evidence_id},
        )

    def _reuse_evidence(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        query_text = str(call.arguments["query"]).strip()
        limit = int(call.arguments["limit"])
        matches = self.evidence_ledger.search_memory(
            query=query_text,
            exclude_turn_id=turn_id,
            limit=limit,
        )
        activated = self.evidence_ledger.activate_existing(
            turn_id=turn_id,
            evidence_ids=[item.evidence_id for item in matches],
        )
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="ok",
            payload={
                "evidence_ids": [item.evidence_id for item in activated],
                "match_count": len(activated),
            },
        )

    def _search_evidence_memory(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        query_text = str(call.arguments.get("query", "")).strip()
        limit = int(call.arguments.get("limit", 8))
        matches = self.evidence_ledger.search_memory(
            query=query_text,
            exclude_turn_id=None,
            limit=limit,
        )
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="ok",
            payload={
                "matches": [
                    {
                        "evidence_id": item.evidence_id,
                        "citation_id": item.citation_id,
                        "title": item.title,
                        "score": item.score,
                    }
                    for item in matches
                ],
                "evidence_ids": [item.evidence_id for item in matches],
                "matched_count": len(matches),
            },
        )


__all__ = [
    "RetrievalUnavailableError",
    "ResourceFuse",
    "ResourceFuseExceeded",
    "RetrievalRequestConstraints",
    "ToolCall",
    "ToolExecutionError",
    "ToolExecutionContext",
    "ToolObservation",
    "ToolRuntime",
    "build_default_tool_registry",
]
