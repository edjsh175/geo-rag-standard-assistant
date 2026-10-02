from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeoTableSchema:
    name: str
    selectable_columns: frozenset[str]
    filterable_columns: frozenset[str]
    geometry_column: str | None = None


DEFAULT_GEOSQL_CATALOG: dict[str, GeoTableSchema] = {
    "spatial_regions": GeoTableSchema(
        name="spatial_regions",
        selectable_columns=frozenset({"id", "adcode", "region_name", "geometry", "created_at"}),
        filterable_columns=frozenset({"id", "adcode", "region_name", "created_at"}),
        geometry_column="geometry",
    ),
}


def get_table_schema(table_name: str) -> GeoTableSchema:
    try:
        return DEFAULT_GEOSQL_CATALOG[table_name]
    except KeyError as exc:
        raise ValueError(f"GeoSQL table is not allowlisted: {table_name}") from exc
