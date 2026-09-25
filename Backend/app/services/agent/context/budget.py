"""Token budget management and auto-trimming for GeoAI Agent execution phases."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)


class TokenEstimator:
    """Pluggable token estimator interface."""

    def estimate(self, text: str) -> int:
        raise NotImplementedError


class CharWeightedTokenEstimator(TokenEstimator):
    """Zero-dependency weighted token estimator for mixed Chinese and English text.

    Approximation:
    - ASCII / Latin: ~4 chars per token.
    - CJK / Non-ASCII: ~1.5 chars per token.
    """

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        # Count ASCII characters
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii_chars = len(text) - ascii_chars
        tokens = int(ascii_chars / 4.0 + non_ascii_chars / 1.5)
        return max(1, tokens)


@dataclass(frozen=True)
class StageBudget:
    max_tokens: int
    system_reserve: int
    generation_reserve: int

    @property
    def available_context_tokens(self) -> int:
        return max(0, self.max_tokens - self.system_reserve - self.generation_reserve)


@dataclass(frozen=True)
class ContextBudgetConfig:
    enabled: bool = True
    controller: StageBudget = field(
        default_factory=lambda: StageBudget(max_tokens=4000, system_reserve=500, generation_reserve=800)
    )
    answer: StageBudget = field(
        default_factory=lambda: StageBudget(max_tokens=8000, system_reserve=600, generation_reserve=1500)
    )
    reviewer: StageBudget = field(
        default_factory=lambda: StageBudget(max_tokens=3000, system_reserve=400, generation_reserve=600)
    )


class ContextBudgetManager:
    """Manages token estimation and deterministic multi-stage context trimming."""

    def __init__(
        self,
        config: ContextBudgetConfig | None = None,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self.config = config or ContextBudgetConfig()
        self.estimator = estimator or CharWeightedTokenEstimator()

    def estimate_tokens(self, text: str) -> int:
        return self.estimator.estimate(text)

    def trim_controller_context(
        self,
        *,
        question: str,
        conversation_lines: Sequence[str],
        working_evidence: Sequence[Mapping[str, Any]],
        map_context: Mapping[str, Any] | None,
        tool_contracts_text: str,
    ) -> tuple[str, list[Mapping[str, Any]], dict[str, Any] | None, int]:
        """Trim Controller context to fit within the controller budget.

        Trimming priority:
        1. Conversation history (oldest first)
        2. Working evidence (lowest score or non-essential first)
        3. Map context (compacting GeoJSON features)
        """
        budget = self.config.controller
        if not self.config.enabled:
            summary = "\n".join(conversation_lines)
            tokens = self.estimator.estimate(summary + question + tool_contracts_text)
            return summary, list(working_evidence), dict(map_context or {}), tokens

        target_limit = budget.available_context_tokens
        # Tool contracts and current question are strictly protected
        fixed_cost = self.estimator.estimate(question) + self.estimator.estimate(tool_contracts_text)
        remaining = max(100, target_limit - fixed_cost)

        # 1. Trimming conversation lines (most recent first)
        selected_lines: list[str] = []
        conv_cost = 0
        for line in reversed(conversation_lines):
            line_cost = self.estimator.estimate(line)
            if selected_lines and (conv_cost + line_cost > int(remaining * 0.5)):
                break
            selected_lines.append(line)
            conv_cost += line_cost
        trimmed_summary = "\n".join(reversed(selected_lines))

        # 2. Trimming evidence
        evidence_remaining = max(100, remaining - conv_cost)
        selected_evidence: list[Mapping[str, Any]] = []
        ev_cost = 0
        # Sort evidence by score descending
        sorted_evidence = sorted(
            working_evidence,
            key=lambda x: float(x.get("score") or 0.0),
            reverse=True,
        )
        for ev in sorted_evidence:
            ev_str = json.dumps(ev, ensure_ascii=False, default=str)
            item_cost = self.estimator.estimate(ev_str)
            if selected_evidence and (ev_cost + item_cost > int(evidence_remaining * 0.7)):
                break
            selected_evidence.append(ev)
            ev_cost += item_cost

        # 3. Trimming / compacting map context
        trimmed_map: dict[str, Any] | None = None
        if map_context:
            map_str = json.dumps(map_context, ensure_ascii=False, default=str)
            map_cost = self.estimator.estimate(map_str)
            map_allowance = max(50, remaining - conv_cost - ev_cost)
            if map_cost <= map_allowance:
                trimmed_map = dict(map_context)
            else:
                # Compact map context (retain bbox and center, truncate heavy features)
                trimmed_map = {
                    k: v for k, v in map_context.items()
                    if k in {"bbox", "center", "zoom", "layers", "active_layer"}
                }
                if "features" in map_context:
                    features = map_context["features"]
                    if isinstance(features, list):
                        trimmed_map["features"] = features[:3]
                        trimmed_map["_features_truncated"] = True

        total_tokens = fixed_cost + conv_cost + ev_cost + (self.estimator.estimate(json.dumps(trimmed_map)) if trimmed_map else 0)
        return trimmed_summary, selected_evidence, trimmed_map, total_tokens

    def trim_answer_context(
        self,
        *,
        question: str,
        conversation_summary: str,
        evidence_items: Sequence[Mapping[str, Any]],
        map_context: Mapping[str, Any] | None,
    ) -> tuple[str, list[Mapping[str, Any]], dict[str, Any] | None, int]:
        """Trim Answer context to fit within the answer budget."""
        budget = self.config.answer
        if not self.config.enabled:
            tokens = self.estimator.estimate(question + conversation_summary + json.dumps(list(evidence_items)))
            return conversation_summary, list(evidence_items), dict(map_context or {}), tokens

        target_limit = budget.available_context_tokens
        question_cost = self.estimator.estimate(question)
        remaining = max(100, target_limit - question_cost)

        # Evidence is primary for Answer generation
        selected_evidence: list[Mapping[str, Any]] = []
        ev_cost = 0
        sorted_evidence = sorted(
            evidence_items,
            key=lambda x: float(x.get("score") or 0.0),
            reverse=True,
        )
        for ev in sorted_evidence:
            ev_str = json.dumps(ev, ensure_ascii=False, default=str)
            item_cost = self.estimator.estimate(ev_str)
            if selected_evidence and (ev_cost + item_cost > int(remaining * 0.8)):
                break
            selected_evidence.append(ev)
            ev_cost += item_cost

        # Conversation summary is secondary
        summary_remaining = max(50, remaining - ev_cost)
        trimmed_summary = conversation_summary
        if self.estimator.estimate(trimmed_summary) > summary_remaining:
            # trim from start
            char_budget = int(summary_remaining * 2.0)
            trimmed_summary = trimmed_summary[-char_budget:]

        total_tokens = question_cost + ev_cost + self.estimator.estimate(trimmed_summary)
        return trimmed_summary, selected_evidence, dict(map_context or {}) if map_context else None, total_tokens
