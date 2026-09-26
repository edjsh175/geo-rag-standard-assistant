"""Provider-neutral model contracts used by Agent stages."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from time import monotonic
from typing import Any, Awaitable, Callable, Mapping, Protocol

from app.models.agent_context import ModelInputAuditRecord


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def model_request_messages_hash(messages: tuple[Mapping[str, str], ...]) -> str:
    return _sha256([dict(message) for message in messages])


def build_model_input_audit_record(request: "ModelRequest") -> ModelInputAuditRecord:
    context = dict(request.audit_context or {})
    if not request.call_id:
        raise ValueError("audited ModelRequest requires call_id")
    required_context = ("principal_id", "session_id", "turn_id")
    missing = [key for key in required_context if not str(context.get(key) or "").strip()]
    if missing:
        raise ValueError(
            "audited ModelRequest missing audit context: " + ", ".join(missing)
        )
    return ModelInputAuditRecord(
        audit_id=f"{request.call_id}:{request.attempt}",
        principal_id=str(context["principal_id"]),
        session_id=str(context["session_id"]),
        turn_id=str(context["turn_id"]),
        stage=request.stage,
        call_id=request.call_id,
        attempt=int(request.attempt),
        model_name=request.model_name,
        request_reasoning=bool(request.request_reasoning),
        temperature=float(request.temperature),
        timeout_seconds=request.timeout_seconds,
        response_schema_hash=(
            _sha256(dict(request.response_schema))
            if request.response_schema is not None
            else None
        ),
        messages_hash=model_request_messages_hash(request.messages),
        messages_section_hashes=tuple(
            _sha256(dict(message)) for message in request.messages
        ),
        context_snapshot_id=(
            str(context["context_snapshot_id"])
            if context.get("context_snapshot_id")
            else None
        ),
        frozen_evidence_snapshot_id=(
            str(context["frozen_evidence_snapshot_id"])
            if context.get("frozen_evidence_snapshot_id")
            else None
        ),
        action_surface_hash=(
            str(context["action_surface_hash"])
            if context.get("action_surface_hash")
            else (_sha256(context["action_surface"]) if "action_surface" in context else None)
        ),
        tool_contract_hash=(
            str(context["tool_contract_hash"])
            if context.get("tool_contract_hash")
            else (_sha256(context["tool_contracts"]) if "tool_contracts" in context else None)
        ),
        created_at=datetime.now(timezone.utc),
    )


@dataclass(frozen=True, slots=True)
class ModelRequest:
    stage: str
    messages: tuple[Mapping[str, str], ...]
    request_reasoning: bool = False
    model_name: str | None = None
    temperature: float = 0.2
    call_id: str | None = None
    attempt: int = 1
    timeout_seconds: float | None = None
    response_schema: Mapping[str, Any] | None = None
    audit_context: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ModelCallAudit:
    call_id: str | None
    stage: str
    attempt: int
    model_name: str | None
    timeout_seconds: float | None
    elapsed_seconds: float
    outcome: str


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str | None
    reasoning_content: str | None = None


class StageModelClient(Protocol):
    @property
    def supports_reasoning(self) -> bool:
        """Whether this adapter can explicitly honor reasoning control."""

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return provider output without interpreting stage semantics."""

    def resolve_main_model(self, *, thinking: bool) -> str | None:
        """Resolve the request-scoped Main model identity once."""


class LLMConfigStageModelClient:
    """Adapter over the repository's existing LLMConfig text-completion API.

    Reasoning capability is declared by LLMConfig. Stage policy remains
    provider-neutral; provider/model selection stays inside the LLM adapter.
    """

    def __init__(
        self,
        llm_config,
        *,
        audit_sink: Callable[[ModelInputAuditRecord], Awaitable[None]] | None = None,
    ) -> None:
        self.llm_config = llm_config
        self.audit_sink = audit_sink
        self.audit_log: deque[ModelCallAudit] = deque(maxlen=1000)

    @property
    def supports_reasoning(self) -> bool:
        return bool(getattr(self.llm_config, "supports_reasoning", False))

    def resolve_main_model(self, *, thinking: bool) -> str | None:
        resolver = getattr(self.llm_config, "resolve_main_model", None)
        if callable(resolver):
            return resolver(thinking=thinking)
        return None

    async def complete(self, request: ModelRequest) -> ModelResponse:
        started_at = monotonic()
        outcome = "error"
        if request.audit_context is not None:
            audit_record = build_model_input_audit_record(request)
            if self.audit_sink is None:
                raise RuntimeError("audited ModelRequest requires an audit sink")
            await self.audit_sink(audit_record)
        from app.core.config import settings
        is_deepseek = (
            getattr(settings, "LLM_PROVIDER", None) == "deepseek"
            or "deepseek" in str(request.model_name or "").lower()
        )
        try:
            if request.response_schema and not is_deepseek:
                structured_output = {
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"{request.stage}_decision",
                            "schema": dict(request.response_schema),
                        },
                    }
                }
            elif request.response_schema or request.stage in {"controller", "answer_generation", "reviewer"}:
                structured_output = {"response_format": {"type": "json_object"}}
            else:
                structured_output = {}

            try:
                content = await self.llm_config.chat_completion(
                    messages=[dict(message) for message in request.messages],
                    model=request.model_name,
                    temperature=request.temperature,
                    request_reasoning=request.request_reasoning,
                    timeout_seconds=request.timeout_seconds,
                    **structured_output,
                )
            except Exception:
                # If provider rejects json_schema, fallback to json_object
                if structured_output.get("response_format", {}).get("type") == "json_schema":
                    content = await self.llm_config.chat_completion(
                        messages=[dict(message) for message in request.messages],
                        model=request.model_name,
                        temperature=request.temperature,
                        request_reasoning=request.request_reasoning,
                        timeout_seconds=request.timeout_seconds,
                        response_format={"type": "json_object"},
                    )
                else:
                    raise
            outcome = "success"
            return ModelResponse(content=content)
        finally:
            self.audit_log.append(
                ModelCallAudit(
                    call_id=request.call_id,
                    stage=request.stage,
                    attempt=request.attempt,
                    model_name=request.model_name,
                    timeout_seconds=request.timeout_seconds,
                    elapsed_seconds=max(0.0, monotonic() - started_at),
                    outcome=outcome,
                )
            )
