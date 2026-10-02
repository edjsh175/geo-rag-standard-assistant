from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.spatial_region_export import (
    build_region_feature_collection,
    compute_region_source_hash,
    export_region_dataset,
    load_region_export_rows,
)


def _sample_rows() -> list[dict]:
    return [
        {
            "adcode": "110000",
            "region_name": "北京市",
            "source_geometry_hex": "0106000020E61000000100000001030000000100000005000000",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[116.0, 39.0], [117.0, 39.0], [117.0, 40.0], [116.0, 40.0], [116.0, 39.0]]]],
            },
        },
        {
            "adcode": "120000",
            "region_name": "天津市",
            "source_geometry_hex": "0106000020E61000000100000001030000000100000005000001",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[117.0, 39.0], [118.0, 39.0], [118.0, 40.0], [117.0, 40.0], [117.0, 39.0]]]],
            },
        },
    ]


def test_compute_region_source_hash_deterministic() -> None:
    rows = _sample_rows()
    hash1 = compute_region_source_hash(rows)
    # Reversed order should produce the exact same hash because it sorts by adcode
    hash2 = compute_region_source_hash(list(reversed(rows)))
    assert hash1.startswith("sha256:")
    assert hash1 == hash2


def test_compute_region_source_hash_sensitive_to_geometry() -> None:
    rows1 = _sample_rows()
    rows2 = _sample_rows()
    rows2[0]["source_geometry_hex"] = "different_hex_value"
    assert compute_region_source_hash(rows1) != compute_region_source_hash(rows2)


def test_build_region_feature_collection_meta_and_ordering() -> None:
    rows = _sample_rows()
    doc = build_region_feature_collection(
        list(reversed(rows)),
        generated_at="2026-09-30T12:00:00Z",
        simplify_tolerance=0.001,
    )

    assert doc["type"] == "FeatureCollection"
    meta = doc["dataset_meta"]
    assert meta["dataset_version"].startswith("spatial-regions-v1-")
    assert meta["generated_at"] == "2026-09-30T12:00:00Z"
    assert meta["source_hash"].startswith("sha256:")
    assert meta["source_relation"] == "spatial_regions"
    assert meta["simplify_tolerance"] == 0.001
    assert meta["feature_count"] == 2

    # Features must be sorted by adcode
    features = doc["features"]
    assert len(features) == 2
    assert features[0]["properties"]["adcode"] == "110000"
    assert features[0]["properties"]["name"] == "北京市"
    assert features[1]["properties"]["adcode"] == "120000"
    assert features[1]["properties"]["name"] == "天津市"


@pytest.mark.asyncio
async def test_load_region_export_rows_queries_spatial_regions() -> None:
    mock_session = AsyncMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = _sample_rows()
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    mock_session.execute.return_value = mock_result

    rows = await load_region_export_rows(mock_session, simplify_tolerance=0.002)

    assert len(rows) == 2
    assert rows[0]["adcode"] == "110000"
    mock_session.execute.assert_called_once()
    sql_text = str(mock_session.execute.call_args[0][0])
    assert "FROM spatial_regions" in sql_text
    assert mock_session.execute.call_args[0][1] == {"simplify": 0.002}


@pytest.mark.asyncio
async def test_export_region_dataset_writes_file(tmp_path: Path) -> None:
    mock_session = AsyncMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = _sample_rows()
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    mock_session.execute.return_value = mock_result

    output_file = tmp_path / "data" / "china-provinces.json"
    doc = await export_region_dataset(mock_session, output_file, simplify_tolerance=0.001)

    assert output_file.exists()
    content = json.loads(output_file.read_text(encoding="utf-8"))
    assert content["type"] == "FeatureCollection"
    assert "dataset_meta" in content
    assert content["dataset_meta"]["feature_count"] == 2
    assert doc == content


@pytest.mark.asyncio
async def test_export_region_dataset_refuses_empty_dataset(tmp_path: Path) -> None:
    mock_session = AsyncMock()
    mock_mappings = MagicMock()
    mock_mappings.all.return_value = []
    mock_result = MagicMock()
    mock_result.mappings.return_value = mock_mappings
    mock_session.execute.return_value = mock_result

    output_file = tmp_path / "data" / "china-provinces.json"
    with pytest.raises(RuntimeError, match="refusing to publish an empty region artifact"):
        await export_region_dataset(mock_session, output_file)
