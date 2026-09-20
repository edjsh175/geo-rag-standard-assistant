"""Provider-neutral model contracts used by Agent stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


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
