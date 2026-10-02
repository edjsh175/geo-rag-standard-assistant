from __future__ import annotations

import json
from typing import Any

from app.services.geosql.contracts import CompiledGeoQuery, GeoQueryPlan
from app.services.geosql.validator import GeoQueryValidator


class GeoQueryCompiler:
    def __init__(self, validator: GeoQueryValidator | None = None) -> None:
        self.validator = validator or GeoQueryValidator()

    def compile(self, plan: GeoQueryPlan) -> CompiledGeoQuery:
        schema = self.validator.validate(plan)
        params: dict[str, Any] = {}
        where: list[str] = []

        for index, item in enumerate(plan.filters):
            column = item.field
            param = f"f_{index}"
            if item.operator == "eq":
                where.append(f"{column} = :{param}")
                params[param] = item.value
            elif item.operator == "ne":
                where.append(f"{column} <> :{param}")
                params[param] = item.value
            elif item.operator in {"lt", "lte", "gt", "gte"}:
                op = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[item.operator]
                where.append(f"{column} {op} :{param}")
                params[param] = item.value
            elif item.operator == "contains":
                where.append(f"{column} ILIKE :{param}")
                params[param] = f"%{item.value}%"
            elif item.operator == "in":
                values = list(item.value) if isinstance(item.value, (list, tuple, set, frozenset)) else []
                if not values:
                    raise ValueError("GeoSQL 'in' filter requires a non-empty list")
                placeholders = []
                for value_index, value in enumerate(values):
                    value_param = f"{param}_{value_index}"
                    placeholders.append(f":{value_param}")
                    params[value_param] = value
                where.append(f"{column} IN ({', '.join(placeholders)})")
            else:  # pragma: no cover - Pydantic literal closes this branch.
                raise ValueError(f"unsupported GeoSQL filter operator: {item.operator}")

        spatial_expr = None
        if plan.spatial is not None:
            spatial_expr = "ST_SetSRID(ST_GeomFromGeoJSON(:spatial_geometry), 4326)"
            params["spatial_geometry"] = json.dumps(plan.spatial.geometry, separators=(",", ":"))

        selected = plan.select_fields or ["id", "adcode", "region_name"]
        returns_geometry = "geometry" in selected
        if plan.operation == "aggregate":
            select_sql = "COUNT(*) AS count"
        else:
            select_parts: list[str] = []
            for field in selected:
                if field == "geometry":
                    select_parts.append(
                        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(geometry, 0.001))::json AS geometry"
                    )
                else:
                    select_parts.append(field)
            if plan.operation in {"distance", "nearest"}:
                assert spatial_expr is not None
                select_parts.append(f"ST_Distance(geometry::geography, {spatial_expr}::geography) AS distance_m")
            select_sql = ", ".join(select_parts)

        if plan.operation in {"spatial_filter", "within"}:
            assert spatial_expr is not None
            where.append(f"ST_Within({schema.geometry_column}, {spatial_expr})")
        elif plan.operation == "intersects":
            assert spatial_expr is not None
            where.append(f"ST_Intersects({schema.geometry_column}, {spatial_expr})")
        elif plan.operation == "distance":
            assert spatial_expr is not None
            assert plan.spatial is not None
            if plan.spatial.distance_m is None:
                raise ValueError("GeoSQL distance requires distance_m")
            where.append(
                f"ST_DWithin({schema.geometry_column}::geography, {spatial_expr}::geography, :distance_m)"
            )
            params["distance_m"] = plan.spatial.distance_m

        sql = f"SELECT {select_sql} FROM {schema.name}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if plan.operation == "nearest":
            assert spatial_expr is not None
            sql += f" ORDER BY {schema.geometry_column} <-> {spatial_expr}"
        sql += " LIMIT :_limit"
        params["_limit"] = plan.limit

        return CompiledGeoQuery(sql=sql, params=params, returns_geometry=returns_geometry)
