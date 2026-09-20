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
    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return provider output without interpreting stage semantics."""


class LLMConfigStageModelClient:
    """Adapter over the repository's existing LLMConfig text-completion API.

    The current LLMConfig contract has no provider-neutral switch for explicit
    reasoning control. Therefore this adapter rejects reasoning requests rather
    than silently pretending that the endpoint honored them.
    """

    def __init__(self, llm_config) -> None:
        self.llm_config = llm_config

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if request.request_reasoning:
            raise RuntimeError(
                "configured LLM adapter does not support explicit reasoning control"
            )
        content = await self.llm_config.chat_completion(
            messages=[dict(message) for message in request.messages],
            temperature=0.2,
        )
        return ModelResponse(content=content)
