"""Stage-scoped reasoning policy for Agent LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Literal


LLMStageName = Literal["controller", "answer_generation", "reviewer"]


@dataclass(frozen=True, slots=True)
class StageExecutionPolicy:
    request_reasoning: bool
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class LLMStagePolicy:
    user_thinking: bool
    endpoint_supports_reasoning: bool
    runtime_deadline_at: float | None = None

    def for_stage(self, stage: LLMStageName) -> StageExecutionPolicy:
        if stage == "controller":
            reasoning = self.user_thinking and self.endpoint_supports_reasoning
            timeout_seconds = 45.0
        elif stage in {"answer_generation", "reviewer"}:
            reasoning = False
            timeout_seconds = 60.0
        else:
            raise ValueError(f"unknown LLM stage: {stage}")

        if self.runtime_deadline_at is not None:
            timeout_seconds = min(
                timeout_seconds,
                max(0.0, self.runtime_deadline_at - monotonic()),
            )
        return StageExecutionPolicy(
            request_reasoning=reasoning,
            timeout_seconds=timeout_seconds,
        )
