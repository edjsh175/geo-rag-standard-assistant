"""Public tool catalogue exposed to the Agent Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, Field, ValidationError, model_validator


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


class ImportVectorDatasetInput(BaseModel):
    file_ref: str = Field(..., min_length=1)
    name: str | None = Field(None, min_length=1, max_length=200)


class SetLayerVisibilityInput(BaseModel):
    layer_ref: str = Field(..., min_length=1)
    visible: bool


class VectorStrokeStyle(BaseModel):
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    width: float | None = Field(None, ge=0, le=64)
    opacity: float | None = Field(None, ge=0, le=1)


class VectorFillStyle(BaseModel):
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    opacity: float | None = Field(None, ge=0, le=1)


class VectorStylePatch(BaseModel):
    stroke: VectorStrokeStyle | None = None
    fill: VectorFillStyle | None = None
    radius: float | None = Field(None, ge=1, le=128)


class SetVectorStyleInput(BaseModel):
    layer_ref: str = Field(..., min_length=1)
    style: VectorStylePatch


class FitVectorLayerInput(BaseModel):
    layer_ref: str = Field(..., min_length=1)


class LocateMapInput(BaseModel):
    longitude: float = Field(..., ge=-180, le=180)
    latitude: float = Field(..., ge=-90, le=90)
    zoom: float | None = Field(None, ge=1, le=22)


class InspectLayerFeaturesInput(BaseModel):
    layer_ref: str = Field(..., min_length=1)
    offset: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=50)


class GetFeatureGeometryInput(BaseModel):
    feature_ref: str = Field(..., min_length=1)


class SpatialRegionRef(BaseModel):
    adcode: str | None = Field(None, min_length=1)
    region_name: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def require_one_identity(self):
        if bool(self.adcode) == bool(self.region_name):
            raise ValueError("region requires exactly one of adcode or region_name")
        return self


class SpatialOperand(BaseModel):
    geometry: dict[str, Any] | None = None
    region: SpatialRegionRef | None = None

    @model_validator(mode="after")
    def require_one_operand(self):
        if (self.geometry is None) == (self.region is None):
            raise ValueError("operand requires exactly one of geometry or region")
        return self


class QuerySpatialRelationInput(BaseModel):
    left: SpatialOperand
    right: SpatialOperand
    relation: str = Field(..., pattern="^(intersects|within|contains|overlaps|disjoint|touches)$")


class SpatialOverlayInput(BaseModel):
    left: SpatialOperand
    right: SpatialOperand
    operation: str = Field(..., pattern="^(intersection|union|difference)$")


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
            ToolSpec(
                name="import_vector_dataset",
                description="Request browser execution to import a referenced SHP or GeoJSON dataset into the active WebGIS map.",
                input_model=ImportVectorDatasetInput,
            ),
            ToolSpec(
                name="set_layer_visibility",
                description="Request browser execution to change visibility of a stable layer_ref.",
                input_model=SetLayerVisibilityInput,
            ),
            ToolSpec(
                name="set_vector_style",
                description="Request browser execution to update display style of a stable user vector layer_ref.",
                input_model=SetVectorStyleInput,
            ),
            ToolSpec(
                name="fit_vector_layer",
                description="Request browser execution to fit the active map viewport to a stable user vector layer_ref.",
                input_model=FitVectorLayerInput,
            ),
            ToolSpec(
                name="locate_map",
                description="Request browser execution to move the active map viewport to a coordinate.",
                input_model=LocateMapInput,
            ),
            ToolSpec(
                name="inspect_layer_features",
                description="Inspect a bounded page of feature_ref identities and properties from a stable browser layer_ref.",
                input_model=InspectLayerFeaturesInput,
            ),
            ToolSpec(
                name="get_feature_geometry",
                description="Read exact GeoJSON geometry and properties for one stable browser feature_ref.",
                input_model=GetFeatureGeometryInput,
            ),
            ToolSpec(
                name="query_spatial_relation",
                description="Ask PostGIS for an authoritative spatial predicate between two GeoJSON or spatial_regions operands.",
                input_model=QuerySpatialRelationInput,
            ),
            ToolSpec(
                name="spatial_overlay",
                description="Ask PostGIS to compute intersection, union, or difference for two GeoJSON or spatial_regions operands.",
                input_model=SpatialOverlayInput,
            ),
        )
    )
