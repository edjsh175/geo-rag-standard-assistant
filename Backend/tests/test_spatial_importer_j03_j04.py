"""Tests for Phase J-03 (Migration authority) and Phase J-04 (Fail-close CRS checking) in spatial importer."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from src.geoai.spatial.importer import check_spatial_regions_table, transform_coordinates


class FakeGDF:
    def __init__(self, crs=None, bounds=(104.0, 30.0, 105.0, 31.0)):
        self.crs = crs
        self.total_bounds = bounds

    def to_crs(self, target_crs: str):
        return FakeGDF(crs=target_crs, bounds=self.total_bounds)


def test_j04_importer_fails_close_when_crs_is_missing() -> None:
    """requirement J-04: Missing CRS must fail-close instead of silently assuming EPSG:4326."""
    gdf_without_crs = FakeGDF(crs=None)

    with pytest.raises(ValueError, match="CRS.*EPSG:4326"):
        transform_coordinates(gdf_without_crs)


def test_j04_importer_accepts_explicit_source_crs() -> None:
    """requirement J-04: Importer accepts explicit source_crs when provided."""
    gdf_without_crs = FakeGDF(crs=None)

    res = transform_coordinates(gdf_without_crs, source_crs="EPSG:4490")
    assert res.crs == "EPSG:4326"


def test_j04_importer_transforms_known_crs() -> None:
    """requirement J-04: Importer transforms defined CRS to EPSG:4326."""
    gdf = FakeGDF(crs="EPSG:3857")
    res = transform_coordinates(gdf)
    assert res.crs == "EPSG:4326"


def test_j03_importer_fails_close_when_table_missing_without_ddl_authority() -> None:
    """requirement J-03: Importer must not execute DDL; missing table must raise RuntimeError directing to migrations."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulate table does not exist
    mock_cur.fetchone.return_value = [False]

    with pytest.raises(RuntimeError, match="Backend/migrations/20260927_spatial_regions.sql"):
        check_spatial_regions_table(mock_conn)

    # Ensure no CREATE TABLE was executed
    executed_statements = [str(call[0][0]) for call in mock_cur.execute.call_args_list]
    assert not any("CREATE TABLE" in stmt.upper() for stmt in executed_statements)


def test_j03_importer_proceeds_when_table_already_exists() -> None:
    """requirement J-03: Importer inspects existing schema when table exists."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulate table exists
    mock_cur.fetchone.return_value = [True]
    mock_cur.fetchall.return_value = [
        ("id", "integer"),
        ("adcode", "character varying"),
        ("region_name", "character varying"),
        ("geometry", "USER-DEFINED"),
    ]

    assert check_spatial_regions_table(mock_conn) is True
