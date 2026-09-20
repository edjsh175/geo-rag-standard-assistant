"""Public tool catalogue exposed to the Agent Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, Field, ValidationError


class RetrieveKbInput(BaseModel):
    query: str = Field(..., min_length=1)


class ReuseEvidenceInput(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(8, ge=1, le=50)


class ComposeAnswerInput(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list)


class ClarifyInput(BaseModel):
    question: str = Field(..., min_length=1)


class LimitationInput(BaseModel):
    message: str = Field(..., min_length=1)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]

    @property
    def input_schema(self) -> Mapping[str, Any]:
        return self.input_model.model_json_schema()


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

    def validate(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        spec = self.get(name)
        try:
            return spec.input_model.model_validate(dict(arguments)).model_dump()
        except ValidationError as exc:
            raise ValueError(f"invalid arguments for {name}: {exc}") from exc


def build_default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        (
            ToolSpec(
                name="retrieve_kb",
                description=(
                    "Search the product knowledge base for evidence needed to resolve "
                    "the current information gap. The Controller chooses when and how "
                    "often to use this tool. Request-level retrieval constraints are "
                    "applied by the runtime and cannot be silently overridden here."
                ),
                input_model=RetrieveKbInput,
            ),
            ToolSpec(
                name="reuse_evidence",
                description=(
                    "Search evidence already admitted in this session and explicitly "
                    "activate selected matches for the current turn."
                ),
                input_model=ReuseEvidenceInput,
            ),
            ToolSpec(
                name="compose_answer",
                description=(
                    "Select current working evidence and freeze it as the immutable "
                    "citation snapshot used by answer generation."
                ),
                input_model=ComposeAnswerInput,
            ),
            ToolSpec(
                name="clarify",
                description=(
                    "Return a clarification question when the Controller cannot safely "
                    "continue without user input."
                ),
                input_model=ClarifyInput,
            ),
            ToolSpec(
                name="limitation",
                description=(
                    "End the turn with a bounded limitation when the available knowledge "
                    "base evidence cannot support a knowledge answer and no clarification "
                    "from the user would resolve that evidence gap."
                ),
                input_model=LimitationInput,
            ),
        )
    )
