"""Shared bounded protocol for structured model candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class StructuredCandidateAttempt:
    protocol_attempt: int
    clean_retry: bool
    request_reasoning: bool | None
    temperature: float | None


class StructuredCandidateProtocolError(ValueError):
    pass


async def execute_structured_candidate(
    *,
    generate: Callable[[StructuredCandidateAttempt], Awaitable[str | None]],
    validate: Callable[[str | None], T],
) -> T:
    attempts = (
        StructuredCandidateAttempt(1, False, None, None),
        StructuredCandidateAttempt(2, True, False, 0.0),
    )
    last_error: ValueError | None = None
    for attempt in attempts:
        content = await generate(attempt)
        try:
            return validate(content)
        except ValueError as exc:
            last_error = exc
            if attempt.protocol_attempt == 2:
                raise StructuredCandidateProtocolError(str(exc)) from exc
    raise StructuredCandidateProtocolError(str(last_error or "structured candidate failed"))
