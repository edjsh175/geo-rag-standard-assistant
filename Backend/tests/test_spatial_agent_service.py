from __future__ import annotations

import json

from app.services.spatial_service import SpatialService


def test_region_operand_uses_bound_parameter_instead_of_inline_value() -> None:
    malicious_name = "x' OR TRUE --"

    sql, params = SpatialService._operand_sql(
        "left",
        {"region": {"region_name": malicious_name}},
    )

    assert ":left_region_name" in sql
    assert malicious_name not in sql
    assert params == {"left_region_name": malicious_name}


def test_geojson_operand_is_serialized_into_bound_parameter() -> None:
    geometry = {"type": "Point", "coordinates": [104.0, 30.0]}

    sql, params = SpatialService._operand_sql("right", {"geometry": geometry})

    assert ":right_geometry" in sql
    assert "104.0" not in sql
    assert json.loads(params["right_geometry"]) == geometry
