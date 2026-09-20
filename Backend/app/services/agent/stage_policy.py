"""Stage-scoped reasoning policy for Agent LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


LLMStageName = Literal["controller", "answer_generation", "reviewer"]


@dataclass(frozen=True, slots=True)
class StageExecutionPolicy:
    request_reasoning: bool


@dataclass(frozen=True, slots=True)
class LLMStagePolicy:
    user_thinking: bool
    endpoint_supports_reasoning: bool

    def for_stage(self, stage: LLMStageName) -> StageExecutionPolicy:
        if stage == "controller":
            return StageExecutionPolicy(
                request_reasoning=(
                    self.user_thinking and self.endpoint_supports_reasoning
                )
            )
        if stage in {"answer_generation", "reviewer"}:
            return StageExecutionPolicy(request_reasoning=False)
        raise ValueError(f"unknown LLM stage: {stage}")
