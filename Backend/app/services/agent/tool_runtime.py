"""Deterministic execution boundary for Controller-selected Agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable, Mapping

from app.services.agent.evidence import EvidenceLedger
from app.services.agent.tools import ToolRegistry, build_default_tool_registry
from app.services.rag.contracts import RetrievalPort, RetrievalQuery


class ToolExecutionError(ValueError):
    """Raised when a tool call violates its explicit input contract."""


class ResourceFuseExceeded(RuntimeError):
    """Raised when a physical runtime safety limit has been exhausted."""


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
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds must be positive")
        self.max_steps = max_steps
        self.max_elapsed_seconds = max_elapsed_seconds
        self._clock = clock
        self._started_at = clock()
        self._steps = 0

    @property
    def steps(self) -> int:
        return self._steps

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
    ) -> None:
        self.retrieval_port = retrieval_port
        self.evidence_ledger = evidence_ledger
        self.registry = registry or build_default_tool_registry()
        self.resource_fuse = resource_fuse

    async def execute(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        self.registry.get(call.name)
        if self.resource_fuse is not None:
            self.resource_fuse.consume_step(tool_name=call.name)

        if call.name == "retrieve_kb":
            observation = await self._retrieve_kb(turn_id=turn_id, call=call)
        elif call.name == "reuse_evidence":
            observation = self._reuse_evidence(turn_id=turn_id, call=call)
        elif call.name == "compose_answer":
            observation = self._compose_answer(turn_id=turn_id, call=call)
        elif call.name == "clarify":
            observation = self._clarify(call=call)
        else:  # pragma: no cover - registry.get() already rejects this branch.
            raise KeyError(f"unknown tool: {call.name}")

        if self.resource_fuse is not None:
            self.resource_fuse.ensure_within_limits()
        return observation

    async def _retrieve_kb(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        query_text = self._required_text(call, "query")
        top_k = self._positive_int(call.arguments.get("top_k", 10), name="top_k")
        threshold = self._number(call.arguments.get("threshold", 0.7), name="threshold")
        search_mode = str(call.arguments.get("search_mode", "hybrid") or "hybrid")
        use_rerank = self._boolean(call.arguments.get("use_rerank", True), name="use_rerank")

        result = await self.retrieval_port.retrieve(
            RetrievalQuery(
                query_text=query_text,
                top_k=top_k,
                threshold=threshold,
                search_mode=search_mode,
                use_rerank=use_rerank,
            )
        )
        admitted = self.evidence_ledger.add_candidates(
            turn_id=turn_id,
            candidates=result.candidates,
        )
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="ok",
            payload={
                "evidence_ids": [item.evidence_id for item in admitted],
                "candidate_count": len(result.candidates),
                "admitted_count": len(admitted),
                "embedding_available": result.embedding_available,
                "diagnostics": result.diagnostics,
            },
        )

    def _reuse_evidence(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        query_text = self._required_text(call, "query")
        limit = self._positive_int(call.arguments.get("limit", 8), name="limit")
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

    def _compose_answer(self, *, turn_id: str, call: ToolCall) -> ToolObservation:
        raw_ids = call.arguments.get("evidence_ids")
        if not isinstance(raw_ids, (list, tuple)):
            raise ToolExecutionError("evidence_ids must be a list of strings")
        evidence_ids = [str(value).strip() for value in raw_ids if str(value).strip()]
        snapshot = self.evidence_ledger.freeze(
            turn_id=turn_id,
            evidence_ids=evidence_ids,
        )
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="ok",
            payload={"snapshot": snapshot},
            is_terminal=True,
        )

    def _clarify(self, *, call: ToolCall) -> ToolObservation:
        question = self._required_text(call, "question")
        return ToolObservation(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            status="ok",
            payload={"question": question},
            is_terminal=True,
        )

    @staticmethod
    def _required_text(call: ToolCall, name: str) -> str:
        value = call.arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ToolExecutionError(f"{name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _positive_int(value: Any, *, name: str) -> int:
        if isinstance(value, bool):
            raise ToolExecutionError(f"{name} must be a positive integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(f"{name} must be a positive integer") from exc
        if parsed <= 0:
            raise ToolExecutionError(f"{name} must be a positive integer")
        return parsed

    @staticmethod
    def _number(value: Any, *, name: str) -> float:
        if isinstance(value, bool):
            raise ToolExecutionError(f"{name} must be a number")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(f"{name} must be a number") from exc

    @staticmethod
    def _boolean(value: Any, *, name: str) -> bool:
        if not isinstance(value, bool):
            raise ToolExecutionError(f"{name} must be a boolean")
        return value


__all__ = [
    "ResourceFuse",
    "ResourceFuseExceeded",
    "ToolCall",
    "ToolExecutionError",
    "ToolObservation",
    "ToolRuntime",
    "build_default_tool_registry",
]
