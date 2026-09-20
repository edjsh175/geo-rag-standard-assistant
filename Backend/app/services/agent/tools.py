"""Public tool catalogue exposed to the Agent Controller."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))


class ToolRegistry:
    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        by_name = {spec.name: spec for spec in specs}
        if len(by_name) != len(specs):
            raise ValueError("tool names must be unique")
        self._specs = by_name

    def names(self) -> set[str]:
        return set(self._specs)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc


def build_default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        (
            ToolSpec(
                name="retrieve_kb",
                description=(
                    "Search the product knowledge base for evidence needed to resolve "
                    "the current information gap. The Controller chooses when and how "
                    "often to use this tool."
                ),
                input_schema={
                    "query": "string",
                    "top_k": "integer?",
                    "threshold": "number?",
                    "search_mode": "hybrid|semantic|keyword|exact?",
                    "use_rerank": "boolean?",
                },
            ),
            ToolSpec(
                name="reuse_evidence",
                description=(
                    "Search evidence already admitted in this session and explicitly "
                    "activate selected matches for the current turn."
                ),
                input_schema={"query": "string", "limit": "integer?"},
            ),
            ToolSpec(
                name="compose_answer",
                description=(
                    "Select current working evidence and freeze it as the immutable "
                    "citation snapshot used by answer generation."
                ),
                input_schema={"evidence_ids": "string[]"},
            ),
            ToolSpec(
                name="clarify",
                description=(
                    "Return a clarification question when the Controller cannot safely "
                    "continue without user input."
                ),
                input_schema={"question": "string"},
            ),
        )
    )
