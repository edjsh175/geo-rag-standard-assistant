"""Shared bounded protocol for structured model candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")
U = TypeVar("U")


def extract_json_object(content: str | None) -> dict[str, Any]:
    """Robustly extract and decode a JSON object from raw model output, handling markdown fences and surrounding commentary."""
    if not content or not str(content).strip():
        raise ValueError("structured output is empty")
    raw = str(content).strip()
    if "```" in raw:
        lines = [line.strip() for line in raw.splitlines()]
        code_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                code_lines.append(line)
        if code_lines:
            raw = "\n".join(code_lines).strip()
        else:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw = raw[start : end + 1]
    elif not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid structured output: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("structured output must be a json object")
    return payload


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
    generate: Callable[[StructuredCandidateAttempt], Awaitable[U]],
    validate: Callable[[U], T],
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
