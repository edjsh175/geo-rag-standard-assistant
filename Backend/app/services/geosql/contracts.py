from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

GeoOperation = Literal["select", "spatial_filter", "aggregate", "distance", "within", "intersects", "nearest"]
FilterOperator = Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "in"]


class GeoFilter(BaseModel):
    field: str = Field(..., min_length=1)
    operator: FilterOperator
    value: Any


class GeoSpatialClause(BaseModel):
    geometry: dict[str, Any]
    distance_m: float | None = Field(None, gt=0)


class GeoQueryPlan(BaseModel):
    operation: GeoOperation
    target_table: str = Field(..., min_length=1)
    select_fields: list[str] = Field(default_factory=list)
    filters: list[GeoFilter] = Field(default_factory=list)
    spatial: GeoSpatialClause | None = None
    limit: int = Field(20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_operation_shape(self):
        if self.operation in {"spatial_filter", "distance", "within", "intersects", "nearest"} and self.spatial is None:
            raise ValueError(f"{self.operation} requires spatial clause")
        if self.operation == "aggregate" and self.spatial is not None:
            raise ValueError("aggregate does not accept spatial clause in GeoSQL V1")
        return self


class CompiledGeoQuery(BaseModel):
    sql: str
    params: dict[str, Any]
    returns_geometry: bool = False
