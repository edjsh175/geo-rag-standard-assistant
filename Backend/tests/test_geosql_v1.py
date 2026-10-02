from __future__ import annotations

import pytest

from app.services.geosql import GeoFilter, GeoQueryCompiler, GeoQueryPlan, GeoSpatialClause


def test_geosql_rejects_non_allowlisted_table_and_column() -> None:
    compiler = GeoQueryCompiler()
    with pytest.raises(ValueError, match="table is not allowlisted"):
        compiler.compile(GeoQueryPlan(operation="select", target_table="users", select_fields=["id"]))

    with pytest.raises(ValueError, match="columns are not allowlisted"):
        compiler.compile(
            GeoQueryPlan(
                operation="select",
                target_table="spatial_regions",
                select_fields=["password"],
            )
        )


def test_geosql_parameterizes_values_and_forces_limit() -> None:
    compiler = GeoQueryCompiler()
    malicious = "成都%' OR 1=1 --"
    compiled = compiler.compile(
        GeoQueryPlan(
            operation="select",
            target_table="spatial_regions",
            select_fields=["id", "adcode", "region_name"],
            filters=[GeoFilter(field="region_name", operator="contains", value=malicious)],
            limit=7,
        )
    )

    assert malicious not in compiled.sql
    assert "region_name ILIKE :f_0" in compiled.sql
    assert compiled.params["f_0"] == f"%{malicious}%"
    assert compiled.sql.endswith("LIMIT :_limit")
    assert compiled.params["_limit"] == 7


def test_geosql_spatial_operations_use_only_fixed_postgis_templates() -> None:
    geometry = {"type": "Point", "coordinates": [104.0, 30.0]}
    compiled = GeoQueryCompiler().compile(
        GeoQueryPlan(
            operation="intersects",
            target_table="spatial_regions",
            select_fields=["adcode", "region_name"],
            spatial=GeoSpatialClause(geometry=geometry),
            limit=5,
        )
    )

    assert "ST_Intersects(geometry, ST_SetSRID(ST_GeomFromGeoJSON(:spatial_geometry), 4326))" in compiled.sql
    assert compiled.params["spatial_geometry"] == '{"type":"Point","coordinates":[104.0,30.0]}'


def test_geosql_nearest_requires_point_and_uses_spatial_index_ordering() -> None:
    compiler = GeoQueryCompiler()
    with pytest.raises(ValueError, match="nearest requires a Point"):
        compiler.compile(
            GeoQueryPlan(
                operation="nearest",
                target_table="spatial_regions",
                select_fields=["adcode"],
                spatial=GeoSpatialClause(
                    geometry={
                        "type": "Polygon",
                        "coordinates": [[[104, 30], [105, 30], [105, 31], [104, 30]]],
                    }
                ),
            )
        )

    compiled = compiler.compile(
        GeoQueryPlan(
            operation="nearest",
            target_table="spatial_regions",
            select_fields=["adcode", "region_name"],
            spatial=GeoSpatialClause(geometry={"type": "Point", "coordinates": [104, 30]}),
            limit=3,
        )
    )
    assert "ORDER BY geometry <-> ST_SetSRID(ST_GeomFromGeoJSON(:spatial_geometry), 4326)" in compiled.sql
    assert "ST_Distance(" in compiled.sql


def test_geosql_v1_aggregate_is_count_only() -> None:
    compiled = GeoQueryCompiler().compile(
        GeoQueryPlan(
            operation="aggregate",
            target_table="spatial_regions",
            select_fields=[],
            filters=[GeoFilter(field="adcode", operator="contains", value="51")],
        )
    )
    assert compiled.sql.startswith("SELECT COUNT(*) AS count FROM spatial_regions")

    with pytest.raises(ValueError, match="count only"):
        GeoQueryCompiler().compile(
            GeoQueryPlan(
                operation="aggregate",
                target_table="spatial_regions",
                select_fields=["region_name"],
            )
        )


@pytest.mark.asyncio
async def test_geosql_executor_uses_read_only_transaction_and_statement_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager
    from app.services.geosql import CompiledGeoQuery, GeoQueryExecutor
    from app.services.geosql import executor as executor_module

    class FakeMappings:
        def all(self):
            return [{"adcode": "510100", "region_name": "Chengdu"}]

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeSession:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None):
            sql = str(statement)
            self.calls.append((sql, dict(params or {})))
            if sql.startswith("SELECT adcode"):
                return FakeResult()
            return FakeResult()

    fake_session = FakeSession()

    @asynccontextmanager
    async def fake_get_postgres_session():
        yield fake_session

    monkeypatch.setattr(executor_module.db_manager, "get_postgres_session", fake_get_postgres_session)

    rows = await GeoQueryExecutor(statement_timeout_ms=1500).execute(
        CompiledGeoQuery(
            sql="SELECT adcode, region_name FROM spatial_regions LIMIT :_limit",
            params={"_limit": 1},
        )
    )

    assert rows == [{"adcode": "510100", "region_name": "Chengdu"}]
    assert fake_session.calls[0][0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in fake_session.calls[1][0]
    assert fake_session.calls[1][1] == {"timeout_ms": "1500"}
    assert fake_session.calls[2] == (
        "SELECT adcode, region_name FROM spatial_regions LIMIT :_limit",
        {"_limit": 1},
    )


@pytest.mark.asyncio
async def test_geosql_executor_rejects_non_select_even_if_compiled_query_is_constructed_directly() -> None:
    from app.services.geosql import CompiledGeoQuery, GeoQueryExecutor
    executor = GeoQueryExecutor()
    with pytest.raises(ValueError, match="one SELECT statement only"):
        await executor.execute(CompiledGeoQuery(sql="DELETE FROM spatial_regions", params={}))
    with pytest.raises(ValueError, match="one SELECT statement only"):
        await executor.execute(CompiledGeoQuery(sql="SELECT 1; SELECT 2", params={}))
