"""Provider-neutral model contracts used by Agent stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ModelRequest:
    stage: str
    messages: tuple[Mapping[str, str], ...]
    request_reasoning: bool = False


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


class LLMConfigStageModelClient:
    """Adapter over the repository's existing LLMConfig text-completion API.

    Reasoning capability is declared by LLMConfig. Stage policy remains
    provider-neutral; provider/model selection stays inside the LLM adapter.
    """

    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config

    @property
    def supports_reasoning(self) -> bool:
        return bool(getattr(self.llm_config, "supports_reasoning", False))

    async def complete(self, request: ModelRequest) -> ModelResponse:
        content = await self.llm_config.chat_completion(
            messages=[dict(message) for message in request.messages],
            temperature=0.2,
            request_reasoning=request.request_reasoning,
        )
        return ModelResponse(content=content)
