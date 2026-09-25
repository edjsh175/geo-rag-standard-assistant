"""Provider-neutral model contracts used by Agent stages."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Mapping, Protocol


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

    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config
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
        try:
            if request.response_schema:
                structured_output = {
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"{request.stage}_decision",
                            "schema": dict(request.response_schema),
                        },
                    }
                }
            elif request.stage in {"controller", "answer_generation", "reviewer"}:
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
