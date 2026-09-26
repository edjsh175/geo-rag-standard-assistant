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


@dataclass(frozen=True)
class EvidenceBudgetCheck:
    allowed: bool
    evidence_tokens: int
    max_evidence_tokens: int
    answer_context_limit: int
    reviewer_context_limit: int | None
    question_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "evidence_tokens": self.evidence_tokens,
            "max_evidence_tokens": self.max_evidence_tokens,
            "answer_context_limit": self.answer_context_limit,
            "reviewer_context_limit": self.reviewer_context_limit,
            "question_tokens": self.question_tokens,
        }


@dataclass(frozen=True)
class ReviewerBudgetCheck:
    allowed: bool
    estimated_tokens: int
    max_context_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "estimated_tokens": self.estimated_tokens,
            "max_context_tokens": self.max_context_tokens,
        }


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

    def _truncate_text_to_budget(self, text: str, max_tokens: int) -> str:
        """Deterministically project text with an explicit truncation marker."""
        if not text or max_tokens <= 0:
            return ""
        if self.estimator.estimate(text) <= max_tokens:
            return text
        marker = "\n[conversation-memory-truncated]"
        if self.estimator.estimate(marker) > max_tokens:
            return ""
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.estimator.estimate(text[:mid] + marker) <= max_tokens:
                low = mid
            else:
                high = mid - 1
        return text[:low] + marker

    @staticmethod
    def _evidence_field(item: Any, name: str, default: str = "") -> str:
        if isinstance(item, Mapping):
            return str(item.get(name) or default)
        return str(getattr(item, name, default) or default)

    def estimate_publication_evidence_tokens(self, items: Sequence[Any]) -> int:
        """Estimate the full evidence text that Answer/Reviewer must both receive."""
        answer_text = "\n\n".join(
            f"[{self._evidence_field(item, 'citation_id')}] "
            f"{self._evidence_field(item, 'title')}\n"
            f"{self._evidence_field(item, 'text', self._evidence_field(item, 'excerpt'))}"
            for item in items
        )
        reviewer_text = "\n\n".join(
            f"[{self._evidence_field(item, 'citation_id')}] "
            f"{self._evidence_field(item, 'text', self._evidence_field(item, 'excerpt'))}"
            for item in items
        )
        return max(
            self.estimator.estimate(answer_text),
            self.estimator.estimate(reviewer_text),
        )

    def check_evidence_selection(
        self,
        *,
        question: str,
        items: Sequence[Any],
        reviewer_enabled: bool,
    ) -> EvidenceBudgetCheck:
        """Validate evidence before freeze; never silently trim a Controller selection."""
        evidence_tokens = self.estimate_publication_evidence_tokens(items)
        question_tokens = self.estimator.estimate(question)
        answer_limit = self.config.answer.available_context_tokens
        reviewer_limit = (
            self.config.reviewer.available_context_tokens if reviewer_enabled else None
        )
        if not self.config.enabled:
            max_evidence_tokens = max(evidence_tokens, 0)
            return EvidenceBudgetCheck(
                allowed=True,
                evidence_tokens=evidence_tokens,
                max_evidence_tokens=max_evidence_tokens,
                answer_context_limit=answer_limit,
                reviewer_context_limit=reviewer_limit,
                question_tokens=question_tokens,
            )
        answer_allowance = max(0, answer_limit - question_tokens)
        reviewer_allowance = (
            max(0, reviewer_limit - question_tokens)
            if reviewer_limit is not None
            else answer_allowance
        )
        max_evidence_tokens = min(answer_allowance, reviewer_allowance)
        return EvidenceBudgetCheck(
            allowed=evidence_tokens <= max_evidence_tokens,
            evidence_tokens=evidence_tokens,
            max_evidence_tokens=max_evidence_tokens,
            answer_context_limit=answer_limit,
            reviewer_context_limit=reviewer_limit,
            question_tokens=question_tokens,
        )

    def check_reviewer_input(
        self,
        *,
        question: str,
        draft_answer: str,
        items: Sequence[Any],
    ) -> ReviewerBudgetCheck:
        """Validate the complete Reviewer semantic payload after the draft exists."""
        evidence_tokens = self.estimate_publication_evidence_tokens(items)
        estimated_tokens = (
            self.estimator.estimate(question)
            + self.estimator.estimate(draft_answer)
            + evidence_tokens
        )
        limit = self.config.reviewer.available_context_tokens
        return ReviewerBudgetCheck(
            allowed=(not self.config.enabled) or estimated_tokens <= limit,
            estimated_tokens=estimated_tokens,
            max_context_tokens=limit,
        )

    def _json_token_cost(self, value: Any) -> int:
        return self.estimator.estimate(
            json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        )

    @staticmethod
    def _prioritize_by_question(
        items: Sequence[Mapping[str, Any]],
        *,
        question: str,
        ref_keys: Sequence[str],
    ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
        referenced: list[Mapping[str, Any]] = []
        remaining: list[Mapping[str, Any]] = []
        for item in items:
            refs = [str(item.get(key) or "") for key in ref_keys]
            if any(ref and ref in question for ref in refs):
                referenced.append(item)
            else:
                remaining.append(item)
        return referenced, remaining

    @staticmethod
    def _flatten_layer_tree(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []

        def walk(items: Sequence[Mapping[str, Any]], inherited_parent: str | None = None) -> None:
            for raw in items:
                if not isinstance(raw, Mapping):
                    continue
                layer_ref = str(raw.get("layer_ref") or "")
                parent_ref = raw.get("parent_ref") or inherited_parent
                node = {
                    key: raw.get(key)
                    for key in ("layer_ref", "name", "kind", "visible", "opacity", "z_index")
                    if raw.get(key) is not None
                }
                if parent_ref:
                    node["parent_ref"] = parent_ref
                flattened.append(node)
                children = raw.get("children")
                if isinstance(children, (list, tuple)):
                    walk(children, layer_ref or inherited_parent)

        walk(nodes)
        return flattened

    def _compact_map_context_v2(
        self,
        *,
        map_context: Mapping[str, Any],
        question: str,
        allowance_tokens: int,
    ) -> dict[str, Any]:
        protected = {
            key: map_context.get(key)
            for key in (
                "schema_version",
                "dimension",
                "ready",
                "revision",
                "supported_tools",
                "viewport",
                "active_region",
            )
            if key in map_context
        }
        raw_tree = map_context.get("layer_tree")
        raw_users = map_context.get("user_layers")
        raw_files = map_context.get("available_files")
        flat_tree = self._flatten_layer_tree(raw_tree if isinstance(raw_tree, (list, tuple)) else ())
        user_layers = [item for item in (raw_users if isinstance(raw_users, (list, tuple)) else ()) if isinstance(item, Mapping)]
        files = [item for item in (raw_files if isinstance(raw_files, (list, tuple)) else ()) if isinstance(item, Mapping)]

        ref_tree, other_tree = self._prioritize_by_question(
            flat_tree, question=question, ref_keys=("layer_ref", "parent_ref")
        )
        ref_users, other_users = self._prioritize_by_question(
            user_layers, question=question, ref_keys=("layer_ref",)
        )
        ref_files, other_files = self._prioritize_by_question(
            files, question=question, ref_keys=("file_ref",)
        )

        def compact_user(item: Mapping[str, Any], ref_cap: int) -> dict[str, Any]:
            refs = [str(value) for value in item.get("feature_refs", ()) if str(value)]
            mentioned = [ref for ref in refs if ref in question]
            remaining = [ref for ref in refs if ref not in mentioned]
            selected = list(dict.fromkeys(mentioned + remaining[:ref_cap]))
            projected = {
                key: item.get(key)
                for key in ("layer_ref", "name", "geometry_types", "feature_count", "visible", "style")
                if item.get(key) is not None
            }
            projected["feature_refs"] = selected
            if len(selected) < len(refs):
                projected["_feature_refs"] = {
                    "truncated": True,
                    "total_count": len(refs),
                    "projected_count": len(selected),
                }
            return projected

        def compact_file(item: Mapping[str, Any], parts_cap: int) -> dict[str, Any]:
            parts = [str(value) for value in item.get("parts", ()) if str(value)]
            projected = {
                key: item.get(key)
                for key in ("file_ref", "name", "format")
                if item.get(key) is not None
            }
            projected["parts"] = parts[:parts_cap]
            if parts_cap < len(parts):
                projected["_parts"] = {
                    "truncated": True,
                    "total_count": len(parts),
                    "projected_count": min(parts_cap, len(parts)),
                }
            return projected

        for extra_cap in (64, 32, 16, 8, 4, 2, 1, 0):
            selected_tree = list(ref_tree) + list(other_tree[:extra_cap])
            selected_users = list(ref_users) + list(other_users[:extra_cap])
            selected_files = list(ref_files) + list(other_files[:extra_cap])
            ref_cap = min(5, extra_cap) if extra_cap else 0
            parts_cap = min(4, extra_cap) if extra_cap else 0
            projected = dict(protected)
            projected["layer_tree"] = [dict(item) for item in selected_tree]
            projected["user_layers"] = [compact_user(item, ref_cap) for item in selected_users]
            projected["available_files"] = [compact_file(item, parts_cap) for item in selected_files]
            projected["_projection"] = {
                "truncated": (
                    len(selected_tree) < len(flat_tree)
                    or len(selected_users) < len(user_layers)
                    or len(selected_files) < len(files)
                    or any("_feature_refs" in item for item in projected["user_layers"])
                    or any("_parts" in item for item in projected["available_files"])
                ),
                "layer_tree": {
                    "total_count": len(flat_tree),
                    "projected_count": len(selected_tree),
                    "flattened": True,
                },
                "user_layers": {
                    "total_count": len(user_layers),
                    "projected_count": len(selected_users),
                },
                "available_files": {
                    "total_count": len(files),
                    "projected_count": len(selected_files),
                },
            }
            if self._json_token_cost(projected) <= allowance_tokens:
                return projected

        return {
            **protected,
            "layer_tree": [dict(item) for item in ref_tree],
            "user_layers": [compact_user(item, 0) for item in ref_users],
            "available_files": [compact_file(item, 0) for item in ref_files],
            "_projection": {
                "truncated": True,
                "layer_tree": {"total_count": len(flat_tree), "projected_count": len(ref_tree), "flattened": True},
                "user_layers": {"total_count": len(user_layers), "projected_count": len(ref_users)},
                "available_files": {"total_count": len(files), "projected_count": len(ref_files)},
            },
        }

    def trim_controller_context(
        self,
        *,
        question: str,
        conversation_lines: Sequence[str],
        conversation_memory_text: str = "",
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
            recent_text = "\n".join(conversation_lines)
            summary = "\n".join(
                value for value in (conversation_memory_text, recent_text) if value
            )
            tokens = self.estimator.estimate(summary + question + tool_contracts_text)
            return summary, list(working_evidence), dict(map_context or {}), tokens

        target_limit = budget.available_context_tokens
        # Tool contracts and current question are strictly protected
        protected_cost = (
            self.estimator.estimate(question)
            + self.estimator.estimate(tool_contracts_text)
        )
        optional_budget = max(0, target_limit - protected_cost)
        # Rolling memory is compressed historical semantics. It must never crowd
        # out the fresher/authoritative sections or make the projection exceed
        # the stage context limit.
        memory_allowance = int(optional_budget * 0.40)
        projected_memory = self._truncate_text_to_budget(
            conversation_memory_text,
            memory_allowance,
        )
        memory_cost = self.estimator.estimate(projected_memory)
        fixed_cost = protected_cost + memory_cost
        remaining = max(0, optional_budget - memory_cost)

        # 1. Trimming conversation lines (most recent first)
        selected_lines: list[str] = []
        conv_cost = 0
        conversation_allowance = int(remaining * 0.5)
        for line in reversed(conversation_lines):
            line_cost = self.estimator.estimate(line)
            if conv_cost + line_cost > conversation_allowance:
                break
            selected_lines.append(line)
            conv_cost += line_cost
        recent_text = "\n".join(reversed(selected_lines))
        trimmed_summary = "\n".join(
            value for value in (projected_memory, recent_text) if value
        )

        # 2. Trimming evidence
        evidence_remaining = max(0, remaining - conv_cost)
        evidence_allowance = int(evidence_remaining * 0.7)
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
            if ev_cost + item_cost > evidence_allowance:
                continue
            selected_evidence.append(ev)
            ev_cost += item_cost

        # 3. Trimming / compacting map context
        trimmed_map: dict[str, Any] | None = None
        if map_context:
            map_str = json.dumps(map_context, ensure_ascii=False, default=str)
            map_cost = self.estimator.estimate(map_str)
            map_allowance = max(0, remaining - conv_cost - ev_cost)
            if map_cost <= map_allowance:
                trimmed_map = dict(map_context)
            elif map_allowance > 0:
                if map_context.get("schema_version") == 2:
                    trimmed_map = self._compact_map_context_v2(
                        map_context=map_context,
                        question=question,
                        allowance_tokens=map_allowance,
                    )
                else:
                    # Compatibility path for older/non-browser map context shapes.
                    trimmed_map = {
                        k: v for k, v in map_context.items()
                        if k in {"bbox", "center", "zoom", "layers", "active_layer"}
                    }
                    if "features" in map_context:
                        features = map_context["features"]
                        if isinstance(features, list):
                            trimmed_map["features"] = features[:3]
                            trimmed_map["_features_truncated"] = True

                if trimmed_map is not None:
                    projected_map_cost = self.estimator.estimate(
                        json.dumps(
                            trimmed_map,
                            ensure_ascii=False,
                            default=lambda o: dict(o) if hasattr(o, "items") else str(o),
                        )
                    )
                    if projected_map_cost > map_allowance:
                        trimmed_map = None

        total_tokens = fixed_cost + conv_cost + ev_cost + (
            self.estimator.estimate(json.dumps(trimmed_map, ensure_ascii=False, default=lambda o: dict(o) if hasattr(o, "items") else str(o)))
            if trimmed_map else 0
        )
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
            tokens = self.estimator.estimate(
                question + conversation_summary + json.dumps(list(evidence_items), ensure_ascii=False, default=lambda o: dict(o) if hasattr(o, "items") else str(o))
            )
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
