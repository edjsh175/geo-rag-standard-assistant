"""Tests for Phase J-08: PostGIS Agent Tool Integration Regression Suite.

Covers:
- point in polygon (within / intersects)
- disjoint
- boundary touches
- intersection area
- difference
- missing region
- invalid geometry
- empty overlay
- large geometry limit / bounding
"""

from __future__ import annotations

import json
from typing import Any
import pytest

from app.services.spatial_service import (
    RegionAmbiguityError,
    RegionNotFoundError,
    SpatialService,
    validate_geojson_geometry,
)


class MockPostgresSession:
    def __init__(self, handler=None):
        self.handler = handler

    async def execute(self, sql, params=None):
        if self.handler:
            return self.handler(sql, params)

        sql_str = str(sql)

        class MockResult:
            def mappings(self_m):
                return self_m

            def one(self_m):
                # Relation or Overlay query result
                if "ST_Intersects" in sql_str:
                    return {"left_found": True, "right_found": True, "result": True}
                if "ST_Disjoint" in sql_str:
                    return {"left_found": True, "right_found": True, "result": True}
                if "ST_Touches" in sql_str:
                    return {"left_found": True, "right_found": True, "result": True}
                if "ST_Intersection" in sql_str:
                    return {
                        "left_found": True,
                        "right_found": True,
                        "geom_type": "ST_Polygon",
                        "n_points": 5,
                        "area_m2": 25000000.0,
                        "bbox": [104.0, 30.0, 104.5, 30.5],
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[104.0, 30.0], [104.5, 30.0], [104.5, 30.5], [104.0, 30.5], [104.0, 30.0]]
                            ],
                        },
                    }
                if "ST_Difference" in sql_str:
                    return {
                        "left_found": True,
                        "right_found": True,
                        "geom_type": "ST_Polygon",
                        "n_points": 5,
                        "area_m2": 15000000.0,
                        "bbox": [104.0, 30.0, 104.3, 30.3],
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[104.0, 30.0], [104.3, 30.0], [104.3, 30.3], [104.0, 30.3], [104.0, 30.0]]
                            ],
                        },
                    }
                return {"left_found": True, "right_found": True, "result": True}

            def all(self_m):
                return []

        return MockResult()


@pytest.fixture
def mock_spatial_db(monkeypatch: pytest.MonkeyPatch):
    def _setup_mock(handler=None):
        class MockCtx:
            async def __aenter__(self):
                return MockPostgresSession(handler)

            async def __aexit__(self, *args):
                pass

        from app.core.database import db_manager
        monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockCtx())

    return _setup_mock


@pytest.mark.asyncio
async def test_j08_point_in_polygon_relation(mock_spatial_db) -> None:
    mock_spatial_db()
    service = SpatialService()

    poly = {
        "type": "Polygon",
        "coordinates": [
            [[104.0, 30.0], [105.0, 30.0], [105.0, 31.0], [104.0, 31.0], [104.0, 30.0]]
        ],
    }
    pt_inside = {"type": "Point", "coordinates": [104.5, 30.5]}

    res = await service.query_relation(
        left={"geometry": pt_inside},
        right={"geometry": poly},
        relation="within",
    )
    assert res["operation"] == "relation"
    assert res["relation"] == "within"
    assert res["result"] is True


@pytest.mark.asyncio
async def test_j08_disjoint_relation(mock_spatial_db) -> None:
    mock_spatial_db()
    service = SpatialService()

    pt1 = {"type": "Point", "coordinates": [100.0, 20.0]}
    pt2 = {"type": "Point", "coordinates": [110.0, 30.0]}

    res = await service.query_relation(
        left={"geometry": pt1},
        right={"geometry": pt2},
        relation="disjoint",
    )
    assert res["relation"] == "disjoint"
    assert res["result"] is True


@pytest.mark.asyncio
async def test_j08_boundary_touches(mock_spatial_db) -> None:
    mock_spatial_db()
    service = SpatialService()

    poly1 = {
        "type": "Polygon",
        "coordinates": [
            [[100.0, 30.0], [101.0, 30.0], [101.0, 31.0], [100.0, 31.0], [100.0, 30.0]]
        ],
    }
    poly2 = {
        "type": "Polygon",
        "coordinates": [
            [[101.0, 30.0], [102.0, 30.0], [102.0, 31.0], [101.0, 31.0], [101.0, 30.0]]
        ],
    }

    res = await service.query_relation(
        left={"geometry": poly1},
        right={"geometry": poly2},
        relation="touches",
    )
    assert res["relation"] == "touches"
    assert res["result"] is True


@pytest.mark.asyncio
async def test_j08_intersection_area(mock_spatial_db) -> None:
    mock_spatial_db()
    service = SpatialService()

    poly1 = {
        "type": "Polygon",
        "coordinates": [
            [[104.0, 30.0], [105.0, 30.0], [105.0, 31.0], [104.0, 31.0], [104.0, 30.0]]
        ],
    }
    poly2 = {
        "type": "Polygon",
        "coordinates": [
            [[104.2, 30.2], [105.2, 30.2], [105.2, 31.2], [104.2, 31.2], [104.2, 30.2]]
        ],
    }

    res = await service.overlay(
        left={"geometry": poly1},
        right={"geometry": poly2},
        operation="intersection",
    )
    assert res["operation"] == "intersection"
    assert res["area_m2"] > 0
    assert res["bbox"] == [104.0, 30.0, 104.5, 30.5]


@pytest.mark.asyncio
async def test_j08_difference(mock_spatial_db) -> None:
    mock_spatial_db()
    service = SpatialService()

    poly1 = {
        "type": "Polygon",
        "coordinates": [
            [[104.0, 30.0], [105.0, 30.0], [105.0, 31.0], [104.0, 31.0], [104.0, 30.0]]
        ],
    }
    poly2 = {
        "type": "Polygon",
        "coordinates": [
            [[104.5, 30.0], [105.0, 30.0], [105.0, 31.0], [104.5, 31.0], [104.5, 30.0]]
        ],
    }

    res = await service.overlay(
        left={"geometry": poly1},
        right={"geometry": poly2},
        operation="difference",
    )
    assert res["operation"] == "difference"
    assert res["area_m2"] > 0


@pytest.mark.asyncio
async def test_j08_missing_region(mock_spatial_db) -> None:
    def handler(sql, params):
        class R:
            def mappings(self_r):
                return self_r

            def all(self_r):
                return []

        return R()

    mock_spatial_db(handler)
    service = SpatialService()

    with pytest.raises(RegionNotFoundError):
        await service.query_relation(
            left={"region": {"region_name": "不存在区域"}},
            right={"geometry": {"type": "Point", "coordinates": [104.0, 30.0]}},
            relation="intersects",
        )


@pytest.mark.asyncio
async def test_j08_invalid_geometry() -> None:
    service = SpatialService()

    bad_point = {"type": "Point", "coordinates": [999.0, 999.0]}
    with pytest.raises(ValueError, match="out of range"):
        await service.query_relation(
            left={"geometry": bad_point},
            right={"geometry": {"type": "Point", "coordinates": [104.0, 30.0]}},
            relation="intersects",
        )


@pytest.mark.asyncio
async def test_j08_empty_overlay(mock_spatial_db) -> None:
    def handler(sql, params):
        class R:
            def mappings(self_r):
                return self_r

            def one(self_r):
                return {
                    "left_found": True,
                    "right_found": True,
                    "geom_type": None,
                    "n_points": 0,
                    "area_m2": 0.0,
                    "bbox": None,
                    "geometry": None,
                }

        return R()

    mock_spatial_db(handler)
    service = SpatialService()

    poly1 = {"type": "Point", "coordinates": [100.0, 30.0]}
    poly2 = {"type": "Point", "coordinates": [120.0, 30.0]}

    res = await service.overlay(
        left={"geometry": poly1},
        right={"geometry": poly2},
        operation="intersection",
    )
    assert res["area_m2"] == 0.0
    assert res["point_count"] == 0
    assert res["geometry"] is None


@pytest.mark.asyncio
async def test_j08_large_geometry_bounding_and_truncation(mock_spatial_db) -> None:
    def handler(sql, params):
        class R:
            def mappings(self_r):
                return self_r

            def one(self_r):
                # Simulate large geometry whose serialized GeoJSON exceeds 8KB limit
                huge_ring = [[104.0 + (i * 0.0001), 30.0 + (i * 0.0001)] for i in range(1500)]
                huge_ring.append(huge_ring[0])
                huge_poly = {"type": "Polygon", "coordinates": [huge_ring]}
                return {
                    "left_found": True,
                    "right_found": True,
                    "geom_type": "ST_Polygon",
                    "n_points": 1501,
                    "area_m2": 99999999.0,
                    "bbox": [104.0, 30.0, 105.0, 31.0],
                    "geometry": huge_poly,
                }

        return R()

    mock_spatial_db(handler)
    service = SpatialService()

    poly1 = {"type": "Point", "coordinates": [104.5, 30.5]}
    poly2 = {"type": "Point", "coordinates": [104.5, 30.5]}

    res = await service.overlay(
        left={"geometry": poly1},
        right={"geometry": poly2},
        operation="intersection",
    )
    assert res["point_count"] == 1501
    assert res["area_m2"] == 99999999.0
    assert res["bbox"] == [104.0, 30.0, 105.0, 31.0]
    # Truncated because serialized JSON exceeds 8192 bytes
    assert res["geometry"] is None
    assert res["geometry_truncated"] is True
