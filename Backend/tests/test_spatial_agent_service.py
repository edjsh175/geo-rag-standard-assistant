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


def test_j06_validate_geojson_geometry_accepts_valid_geometries() -> None:
    from app.services.spatial_service import validate_geojson_geometry

    # Valid Point
    validate_geojson_geometry({"type": "Point", "coordinates": [104.0, 30.0]})
    # Valid LineString
    validate_geojson_geometry({"type": "LineString", "coordinates": [[104.0, 30.0], [105.0, 31.0]]})
    # Valid Polygon (closed ring >= 4 coords)
    validate_geojson_geometry({
        "type": "Polygon",
        "coordinates": [
            [[100.0, 20.0], [101.0, 20.0], [101.0, 21.0], [100.0, 21.0], [100.0, 20.0]]
        ],
    })


@pytest.mark.parametrize(
    ("bad_geom", "match_str"),
    [
        ({"type": "InvalidType", "coordinates": [100, 20]}, "unsupported or missing GeoJSON geometry type"),
        ({"type": "Point", "coordinates": []}, "coordinates cannot be empty"),
        ({"type": "Point", "coordinates": [190.0, 30.0]}, "longitude 190.0 out of range"),
        ({"type": "Point", "coordinates": [100.0, 95.0]}, "latitude 95.0 out of range"),
        ({"type": "LineString", "coordinates": [[100, 20]]}, "LineString must contain at least 2 points"),
        (
            {
                "type": "Polygon",
                "coordinates": [[[100, 20], [101, 20], [100, 20]]],
            },
            "must contain at least 4 coordinates",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [[[100, 20], [101, 20], [101, 21], [100, 22]]],
            },
            "is not closed",
        ),
        (
            {
                "type": "Point",
                "coordinates": [100, 20],
                "crs": {"properties": {"name": "EPSG:3857"}},
            },
            "unsupported CRS",
        ),
    ],
)
def test_j06_validate_geojson_geometry_rejects_invalid_inputs(bad_geom: dict, match_str: str) -> None:
    from app.services.spatial_service import validate_geojson_geometry

    with pytest.raises(ValueError, match=match_str):
        validate_geojson_geometry(bad_geom)


def test_j06_operand_sql_rejects_invalid_geojson() -> None:
    bad_geometry = {"type": "Point", "coordinates": [250.0, 30.0]}
    with pytest.raises(ValueError, match="longitude 250.0 out of range"):
        SpatialService._operand_sql("left", {"geometry": bad_geometry})


@pytest.mark.asyncio
async def test_j02_unimplemented_spatial_methods_fail_close_without_mocking() -> None:
    service = SpatialService()
    from app.models.spatial_models import GeocodeRequest, ReverseGeocodeRequest, SpatialQuery

    with pytest.raises(NotImplementedError, match="Authoritative geocoding provider is not configured"):
        await service.geocode(GeocodeRequest(address="北京市海淀区"))

    with pytest.raises(NotImplementedError, match="Authoritative reverse geocoding provider is not configured"):
        await service.reverse_geocode(ReverseGeocodeRequest(lon=116.4, lat=39.9))

    with pytest.raises(NotImplementedError, match="Authoritative spatial query provider is not implemented"):
        await service.spatial_query(SpatialQuery(geometry={"type": "Point", "coordinates": [104.0, 30.0]}))

    with pytest.raises(NotImplementedError, match="Authoritative spatial_analysis is not implemented"):
        await service.spatial_analysis(
            geometry1={"type": "Point", "coordinates": [104.0, 30.0]},
            geometry2={"type": "Point", "coordinates": [104.0, 30.0]},
        )


@pytest.mark.asyncio
async def test_j02_create_buffer_validates_inputs_and_uses_postgis(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SpatialService()

    # Invalid coordinates
    with pytest.raises(ValueError, match="out of bounds"):
        await service.create_buffer(center=[200.0, 30.0], distance=100.0)

    # Invalid distance
    with pytest.raises(ValueError, match="distance must be positive"):
        await service.create_buffer(center=[104.0, 30.0], distance=-50.0)

    # Valid call executes PostGIS
    class MockRow:
        def mappings(self):
            return self

        def one(self):
            return {"geometry": {"type": "Polygon", "coordinates": [[[104, 30], [104.1, 30], [104.1, 30.1], [104, 30.1], [104, 30]]]}}

    class MockSession:
        async def execute(self, sql, params):
            assert ":distance" in str(sql)
            assert params["distance"] == 500.0
            assert params["lon"] == 104.0
            return MockRow()

    class MockContext:
        async def __aenter__(self):
            return MockSession()

        async def __aexit__(self, *args):
            pass

    from app.core.database import db_manager
    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockContext())

    res = await service.create_buffer(center=[104.0, 30.0], distance=500.0)
    assert res["type"] == "Polygon"


def test_j07_operand_sql_has_no_silent_limit_one() -> None:
    """requirement J-07: Verify that _operand_sql eliminates silent 'LIMIT 1' in region queries."""
    sql_adcode, params_adcode = SpatialService._operand_sql("left", {"region": {"adcode": "510000"}})
    assert "LIMIT 1" not in sql_adcode
    assert ":left_adcode" in sql_adcode

    sql_name, params_name = SpatialService._operand_sql("right", {"region": {"region_name": "四川省"}})
    assert "LIMIT 1" not in sql_name
    assert ":right_region_name" in sql_name


@pytest.mark.asyncio
async def test_j07_resolve_region_by_adcode(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SpatialService()

    class MockResult:
        def mappings(self):
            return self

        def all(self):
            return [{"adcode": "510000", "region_name": "四川省"}]

    class MockSession:
        async def execute(self, sql, params):
            assert "adcode = :adcode" in str(sql)
            assert params["adcode"] == "510000"
            return MockResult()

    class MockContext:
        async def __aenter__(self):
            return MockSession()

        async def __aexit__(self, *args):
            pass

    from app.core.database import db_manager
    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockContext())

    resolved = await service.resolve_region(adcode="510000")
    assert resolved == {"adcode": "510000", "region_name": "四川省"}


@pytest.mark.asyncio
async def test_j07_resolve_region_by_adcode_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.spatial_service import RegionNotFoundError

    service = SpatialService()

    class MockResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class MockSession:
        async def execute(self, sql, params):
            return MockResult()

    class MockContext:
        async def __aenter__(self):
            return MockSession()

        async def __aexit__(self, *args):
            pass

    from app.core.database import db_manager
    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockContext())

    with pytest.raises(RegionNotFoundError, match="adcode '999999' does not exist"):
        await service.resolve_region(adcode="999999")


@pytest.mark.asyncio
async def test_j07_resolve_region_ambiguous_name_fails_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """requirement J-07: Verify that multiple matching region names raise RegionAmbiguityError with candidate details."""
    from app.services.spatial_service import RegionAmbiguityError

    service = SpatialService()

    class MockResult:
        def mappings(self):
            return self

        def all(self):
            # Duplicate names e.g. 朝阳区 in Beijing and Changchun
            return [
                {"adcode": "110105", "region_name": "朝阳区"},
                {"adcode": "220104", "region_name": "朝阳区"},
            ]

    class MockSession:
        async def execute(self, sql, params):
            return MockResult()

    class MockContext:
        async def __aenter__(self):
            return MockSession()

        async def __aexit__(self, *args):
            pass

    from app.core.database import db_manager
    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockContext())

    with pytest.raises(RegionAmbiguityError) as exc_info:
        await service.resolve_region(region_name="朝阳区")

    assert exc_info.value.region_name == "朝阳区"
    assert len(exc_info.value.candidates) == 2
    assert "110105" in str(exc_info.value)
    assert "220104" in str(exc_info.value)


@pytest.mark.asyncio
async def test_j07_resolve_region_prefix_fallback_and_ambiguity(monkeypatch: pytest.MonkeyPatch) -> None:
    """requirement J-07: Test prefix/alias fallback and ambiguous prefix detection."""
    from app.services.spatial_service import RegionAmbiguityError, RegionNotFoundError

    service = SpatialService()

    # Case 1: Prefix match has exactly 1 candidate (e.g. "四川" -> "四川省")
    class MockPrefixSingleSession:
        async def execute(self, sql, params):
            class R:
                def mappings(self):
                    return self

                def all(self_r):
                    if "region_name = :region_name" in str(sql):
                        return []
                    if "region_name LIKE :prefix" in str(sql):
                        return [{"adcode": "510000", "region_name": "四川省"}]
                    return []
            return R()

    class MockCtx1:
        async def __aenter__(self):
            return MockPrefixSingleSession()

        async def __aexit__(self, *args):
            pass

    from app.core.database import db_manager
    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockCtx1())

    resolved = await service.resolve_region(region_name="四川")
    assert resolved == {"adcode": "510000", "region_name": "四川省"}

    # Case 2: Prefix match has multiple candidates (e.g. "山" -> 山东省, 山西省) -> Ambiguous
    class MockPrefixMultiSession:
        async def execute(self, sql, params):
            class R:
                def mappings(self):
                    return self

                def all(self_r):
                    if "region_name = :region_name" in str(sql):
                        return []
                    if "region_name LIKE :prefix" in str(sql):
                        return [
                            {"adcode": "370000", "region_name": "山东省"},
                            {"adcode": "140000", "region_name": "山西省"},
                        ]
                    return []
            return R()

    class MockCtx2:
        async def __aenter__(self):
            return MockPrefixMultiSession()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockCtx2())
    with pytest.raises(RegionAmbiguityError) as exc_info:
        await service.resolve_region(region_name="山")
    assert len(exc_info.value.candidates) == 2

    # Case 3: Neither exact nor prefix match -> RegionNotFoundError
    class MockEmptySession:
        async def execute(self, sql, params):
            class R:
                def mappings(self):
                    return self

                def all(self_r):
                    return []
            return R()

    class MockCtx3:
        async def __aenter__(self):
            return MockEmptySession()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(db_manager, "get_postgres_session", lambda: MockCtx3())
    with pytest.raises(RegionNotFoundError, match="不存在|does not exist"):
        await service.resolve_region(region_name="虚拟行政区")


