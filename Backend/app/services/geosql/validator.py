from __future__ import annotations

from app.services.geosql.contracts import GeoQueryPlan
from app.services.geosql.schema_catalog import GeoTableSchema, get_table_schema
from app.services.spatial_service import validate_geojson_geometry


class GeoQueryValidator:
    def validate(self, plan: GeoQueryPlan) -> GeoTableSchema:
        schema = get_table_schema(plan.target_table)
        selected = list(plan.select_fields)
        if plan.operation == "aggregate":
            if selected not in (["count"], []):
                raise ValueError("GeoSQL V1 aggregate supports count only")
        else:
            selected = selected or ["id", "adcode", "region_name"]
            unknown_selected = set(selected) - schema.selectable_columns
            if unknown_selected:
                raise ValueError(f"GeoSQL columns are not allowlisted: {sorted(unknown_selected)}")

        unknown_filters = {item.field for item in plan.filters} - schema.filterable_columns
        if unknown_filters:
            raise ValueError(f"GeoSQL filter columns are not allowlisted: {sorted(unknown_filters)}")

        if plan.operation == "aggregate":
            return schema

        if plan.operation in {"spatial_filter", "distance", "within", "intersects", "nearest"}:
            if schema.geometry_column is None:
                raise ValueError(f"GeoSQL table has no geometry column: {schema.name}")
            assert plan.spatial is not None
            validate_geojson_geometry(plan.spatial.geometry)
            if plan.operation == "nearest" and plan.spatial.geometry.get("type") != "Point":
                raise ValueError("GeoSQL nearest requires a Point geometry")

        if "geometry" in selected and plan.limit > 20:
            raise ValueError("GeoSQL geometry selection is limited to 20 rows")

        return schema
