from __future__ import annotations

import json
import pytest

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


@pytest.mark.asyncio
async def test_overlay_returns_bounded_facts_and_truncates_oversized_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SpatialService()

    class MockRow:
        def __init__(self, data: dict):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

        def __getitem__(self, key):
            return self._data[key]

    class MockResult:
        def mappings(self):
            return self

        def one(self):
            return MockRow({
                "left_found": True,
                "right_found": True,
                "geom_type": "ST_Polygon",
                "n_points": 500,
                "area_m2": 1500000.0,
                "bbox": [103.9, 30.5, 104.2, 30.8],
                "geometry": {"type": "Polygon", "coordinates": [[[103.9, 30.5], [104.2, 30.5], [104.2, 30.8], [103.9, 30.8], [103.9, 30.5]]]},
            })

    class MockSession:
        async def execute(self, *args, **kwargs):
            return MockResult()

    class MockContext:
        async def __aenter__(self):
            return MockSession()

        async def __aexit__(self, *args):
            pass

    from app.core.database import db_manager
    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockContext())

    res = await service.overlay(
        left={"geometry": {"type": "Point", "coordinates": [104.0, 30.0]}},
        right={"geometry": {"type": "Point", "coordinates": [104.0, 30.0]}},
        operation="intersection",
    )

    assert res["operation"] == "intersection"
    assert res["geometry_type"] == "ST_Polygon"
    assert res["area_m2"] == 1500000.0
    assert res["bbox"] == [103.9, 30.5, 104.2, 30.8]
    assert res["point_count"] == 500
    assert res["is_simplified"] is True
    assert res["geometry_truncated"] is False
    assert res["geometry"] is not None
