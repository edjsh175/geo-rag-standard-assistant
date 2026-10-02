"""Public tool catalogue exposed to the Agent Controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.geosql.contracts import GeoQueryPlan


BROWSER_TOOL_NAMES = frozenset(
    {
        "import_vector_dataset",
        "set_layer_visibility",
        "set_vector_style",
        "fit_vector_layer",
        "locate_map",
        "inspect_layer_features",
        "get_feature_geometry",
        "render_geojson_layer",
    }
)


class RetrieveKbInput(BaseModel):
    query: str = Field(..., min_length=1)


class ReuseEvidenceInput(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(8, ge=1, le=50)


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
    model_config = ConfigDict(allow_inf_nan=False)

    longitude: float
    latitude: float
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
        if self.geometry is not None:
            from app.services.spatial_service import validate_geojson_geometry

            validate_geojson_geometry(self.geometry)
        return self


class QuerySpatialRelationInput(BaseModel):
    left: SpatialOperand
    right: SpatialOperand
    relation: str = Field(..., pattern="^(intersects|within|contains|overlaps|disjoint|touches)$")


class SpatialOverlayInput(BaseModel):
    left: SpatialOperand
    right: SpatialOperand
    operation: str = Field(..., pattern="^(intersection|union|difference)$")


class CreateBufferInput(BaseModel):
    center: tuple[float, float]
    distance_m: float = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_center(self):
        lon, lat = self.center
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("center coordinates out of bounds")
        return self


class RenderGeoJsonLayerInput(BaseModel):
    geojson: dict[str, Any]
    name: str = Field("Spatial result", min_length=1, max_length=200)
    style: VectorStylePatch | None = None

    @model_validator(mode="after")
    def validate_geojson(self):
        from app.services.spatial_service import validate_geojson_geometry
        validate_geojson_geometry(self.geojson)
        return self


class SearchEvidenceMemoryInput(BaseModel):
    query: str = Field(..., min_length=1, description="检索词或目标问题")
    limit: int = Field(8, ge=1, le=50, description="最多返回条数")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    use_when: str = ""
    avoid_when: str = ""
    result_semantics: str = ""
    failure_semantics: str = ""
    side_effect: bool = False
    confirmation_required: bool = False
    timeout: float = 30.0
    cancel_supported: bool = False
    provider: str = "server"  # "server", "browser", "postgis", "kb"
    permission: str | None = None

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

    def specs_for(self, names: set[str] | frozenset[str] | Sequence[str]) -> tuple[ToolSpec, ...]:
        name_set = set(names)
        return tuple(spec for spec in self._specs.values() if spec.name in name_set)

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

    def validate_arguments(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self.validate(name, arguments)


CONTROL_ACTION_NAMES = frozenset(
    {
        "compose_answer",
        "direct_answer",
        "clarify",
        "limitation",
    }
)


def executable_tool_names(
    registry: ToolRegistry | None = None,
    map_context: Mapping[str, Any] | None = None,
    provider_health: Mapping[str, bool] | None = None,
) -> frozenset[str]:
    """Return the physical capability tool surface executable for the current request.

    Control actions (compose_answer, direct_answer, clarify, limitation) are control
    protocol actions, not tools, and are strictly excluded from the capability surface.
    Non-browser tools are filtered by provider health. Browser tools are admitted only
    when the active browser runtime explicitly reports them through map_context.supported_tools.
    """
    if registry is None:
        return frozenset()

    candidates = (registry.names() - BROWSER_TOOL_NAMES) - CONTROL_ACTION_NAMES

    # Provider health filter (P0-8 / P0-10)
    if provider_health:
        health_map = dict(provider_health)

        def _is_unhealthy(val: Any) -> bool:
            if val is False:
                return True
            if isinstance(val, str) and val.strip().lower() in {"degraded", "unhealthy", "down", "offline", "false"}:
                return True
            return False

        filtered: set[str] = set()
        for name in candidates:
            spec = registry.get(name)
            # Database / KB health check
            if spec.provider == "kb":
                if _is_unhealthy(health_map.get("postgres")) or _is_unhealthy(health_map.get("db")) or _is_unhealthy(health_map.get("kb")):
                    continue
            # PostGIS / Spatial service health check
            elif spec.provider == "postgis":
                if _is_unhealthy(health_map.get("postgis")) or _is_unhealthy(health_map.get("spatial")) or _is_unhealthy(health_map.get("postgres")):
                    continue
            filtered.add(name)
        non_browser = filtered
    else:
        non_browser = set(candidates)

    if not isinstance(map_context, Mapping):
        return frozenset(non_browser)
    if map_context.get("ready") is not True:
        return frozenset(non_browser)
    raw_supported = map_context.get("supported_tools")
    if not isinstance(raw_supported, (list, tuple, set, frozenset)):
        return frozenset(non_browser)
    supported = {
        str(name)
        for name in raw_supported
        if isinstance(name, str) and name in BROWSER_TOOL_NAMES
    }
    return frozenset(non_browser | (supported & registry.names()))


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
                input_model=RetrieveKbInput,
                use_when="需要查询知识库以解决当前信息缺失时由 Controller 自主规划调用。",
                avoid_when="当前会话已存在足够证据，或纯闲聊无需知识库时禁止调用。",
                result_semantics="将知识库召回的候选文档通过证据账本准入为可引用的 EvidenceItem。",
                failure_semantics="检索通道全部不可用时抛出异常或返回空结果。",
                provider="kb",
            ),
            ToolSpec(
                name="search_evidence_memory",
                description="Search historical evidence already admitted in this session by query.",
                input_model=SearchEvidenceMemoryInput,
                use_when="当前会话有多轮历史证据，且需要主动按语义搜索未在当前轮次直接投影的证据时调用。",
                avoid_when="当前工作证据已足够或尚未产生任何历史证据时禁止调用。",
                result_semantics="返回历史证据匹配项列表及 evidence_id，供后续决策或 compose_answer 挑选。",
                provider="server",
            ),
            ToolSpec(
                name="reuse_evidence",
                description=(
                    "Search evidence already admitted in this session and explicitly "
                    "activate selected matches for the current turn."
                ),
                input_model=ReuseEvidenceInput,
                use_when="搜索历史证据并将其激活进入当前轮次工作证据集。",
                provider="server",
            ),
            ToolSpec(
                name="import_vector_dataset",
                description="Request browser execution to import a referenced SHP or GeoJSON dataset into the active WebGIS map.",
                input_model=ImportVectorDatasetInput,
                use_when="用户明确要求在地图上加载/导入矢量数据图层时调用。",
                result_semantics="浏览器端异步解析并渲染新图层，返回包含 layer_ref 的收据。",
                side_effect=True,
                provider="browser",
            ),
            ToolSpec(
                name="set_layer_visibility",
                description="Request browser execution to change visibility of a stable layer_ref.",
                input_model=SetLayerVisibilityInput,
                use_when="需要显隐地图上的特定图层时调用。",
                side_effect=True,
                provider="browser",
            ),
            ToolSpec(
                name="set_vector_style",
                description="Request browser execution to update display style of a stable user vector layer_ref.",
                input_model=SetVectorStyleInput,
                use_when="需要修改矢量图层的描边、填充、半透明度或点半径等样式时调用。",
                side_effect=True,
                provider="browser",
            ),
            ToolSpec(
                name="fit_vector_layer",
                description="Request browser execution to fit the active map viewport to a stable user vector layer_ref.",
                input_model=FitVectorLayerInput,
                use_when="导入或选择图层后，需要将地图视角平滑缩放到该图层范围时调用。",
                side_effect=True,
                provider="browser",
            ),
            ToolSpec(
                name="locate_map",
                description="Request browser execution to move the active map viewport to a coordinate.",
                input_model=LocateMapInput,
                use_when="需要将地图定位到特定的经纬度坐标中心或缩放级别时调用。",
                side_effect=True,
                provider="browser",
            ),
            ToolSpec(
                name="inspect_layer_features",
                description="Inspect a bounded page of feature_ref identities and properties from a stable browser layer_ref.",
                input_model=InspectLayerFeaturesInput,
                use_when="需要查看图层内部要素的属性表或分页信息时调用。",
                provider="browser",
            ),
            ToolSpec(
                name="get_feature_geometry",
                description="Read exact GeoJSON geometry and properties for one stable browser feature_ref.",
                input_model=GetFeatureGeometryInput,
                use_when="需要提取地图中具体要素的几何图形（GeoJSON）进行进一步空间分析时调用。",
                provider="browser",
            ),
            ToolSpec(
                name="query_spatial_relation",
                description="Ask PostGIS for an authoritative spatial predicate between two GeoJSON or spatial_regions operands.",
                input_model=QuerySpatialRelationInput,
                use_when="需要判断两个地理实体或图斑之间的空间拓扑关系（相交、包含、重叠等）时调用。",
                result_semantics="返回权威空间谓词计算结果（布尔值或详细关系）。",
                provider="postgis",
            ),
            ToolSpec(
                name="create_buffer",
                description="Ask PostGIS to create a meter-based buffer around a WGS84 coordinate.",
                input_model=CreateBufferInput,
                use_when="需要围绕明确经纬度按米生成缓冲区时调用。",
                result_semantics="返回 PostGIS 生成的 GeoJSON Polygon，并写入 Evidence Ledger。",
                provider="postgis",
            ),
            ToolSpec(
                name="spatial_overlay",
                description="Ask PostGIS to compute intersection, union, or difference for two GeoJSON or spatial_regions operands.",
                input_model=SpatialOverlayInput,
                use_when="需要计算两个区域或要素的几何叠加（求交集、并集、差集）时调用。",
                result_semantics="返回叠加分析后的几何体与面积等统计属性。",
                provider="postgis",
            ),
            ToolSpec(
                name="query_geospatial_data",
                description="Execute a validated GeoQueryPlan without SQL text. Current catalog: spatial_regions; selectable columns: id, adcode, region_name, geometry, created_at; filterable columns exclude geometry.",
                input_model=GeoQueryPlan,
                use_when="需要按属性、空间关系、距离或最近邻查询受控空间数据时调用。",
                result_semantics="返回受限行集并写入 Evidence Ledger；若结果含 geometry，同时返回可渲染 GeoJSON。",
                provider="postgis",
            ),
            ToolSpec(
                name="render_geojson_layer",
                description="Request the active browser GIS runtime to render a validated GeoJSON geometry as a user vector layer.",
                input_model=RenderGeoJsonLayerInput,
                use_when="PostGIS 或 GeoSQL 已产生需要显示在地图上的 GeoJSON 几何结果时调用。",
                result_semantics="浏览器创建用户矢量图层并返回稳定 layer_ref 与更新后的 map_context receipt。",
                side_effect=True,
                provider="browser",
            ),
        )
    )
