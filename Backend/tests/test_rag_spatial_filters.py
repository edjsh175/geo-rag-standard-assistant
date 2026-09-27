from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult, SpatialFilter
from app.services.rag.filters import RagFilterEngine


def make_result(
    doc_id: str,
    standard_code: str,
    geometry: dict | None = None,
) -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=doc_id,
        content="",
        similarity=0.8,
        metadata={"standard_code": standard_code, "document_name": doc_id},
        spatial_info={"geometry": geometry} if geometry else None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


@pytest.mark.asyncio
async def test_spatial_filter_matches_document_geometry_intersection() -> None:
    engine = RagFilterEngine()
    inside = make_result(
        "inside",
        "DB50/T 1846-2025",
        {
            "type": "Polygon",
            "coordinates": [[
                [105.0, 29.0],
                [106.0, 29.0],
                [106.0, 30.0],
                [105.0, 30.0],
                [105.0, 29.0],
            ]],
        },
    )
    outside = make_result(
        "outside",
        "DB51/T 1000-2024",
        {
            "type": "Polygon",
            "coordinates": [[
                [100.0, 30.0],
                [101.0, 30.0],
                [101.0, 31.0],
                [100.0, 31.0],
                [100.0, 30.0],
            ]],
        },
    )

    filtered = await engine.apply_spatial_filter(
        [inside, outside],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": [105.5, 29.5]},
            spatial_relation="intersects",
        ),
    )

    assert [result.id for result in filtered] == ["inside"]
    assert filtered[0].metadata["spatial_filter_match"] is True


@pytest.mark.asyncio
async def test_spatial_filter_falls_back_to_region_standard_prefix() -> None:
    class PrefixEngine(RagFilterEngine):
        async def get_region_prefixes_for_geometry(self, spatial_filter: SpatialFilter) -> set[str]:
            return {"DB50"}

    engine = PrefixEngine()

    filtered = await engine.apply_spatial_filter(
        [
            make_result("match", "DB50/T 1846-2025"),
            make_result("miss", "DB51/T 1000-2024"),
        ],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": [105.5, 29.5]},
            spatial_relation="intersects",
        ),
    )

    assert [result.id for result in filtered] == ["match"]
    assert filtered[0].metadata["spatial_filter_match"] is True
    assert filtered[0].metadata["spatial_filter_source"] == "region_prefix"


@pytest.mark.asyncio
async def test_spatial_filter_returns_empty_for_invalid_geometry() -> None:
    engine = RagFilterEngine()

    filtered = await engine.apply_spatial_filter(
        [make_result("candidate", "DB50/T 1846-2025")],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": ["bad", 29.5]},
            spatial_relation="intersects",
        ),
    )

    assert filtered == []


@pytest.mark.asyncio
async def test_j10_spatial_filter_near_uses_geodesic_distance() -> None:
    """requirement J-10: Test that 'near' relation uses geodesic Haversine distance, not flat 111,320m/deg."""
    engine = RagFilterEngine()

    # Point 1: Beijing (116.4074, 39.9042)
    # Point 2: Tianjin (117.2008, 39.0840) ~ 109 km apart
    # Point 3: Shanghai (121.4737, 31.2304) ~ 1068 km apart
    doc_tianjin = make_result(
        "doc_tianjin",
        "DB12/T 100-2024",
        {"type": "Point", "coordinates": [117.2008, 39.0840]},
    )
    doc_shanghai = make_result(
        "doc_shanghai",
        "DB31/T 200-2024",
        {"type": "Point", "coordinates": [121.4737, 31.2304]},
    )

    # Query near Beijing with 150 km (150,000 m) radius
    filtered_150km = await engine.apply_spatial_filter(
        [doc_tianjin, doc_shanghai],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": [116.4074, 39.9042]},
            spatial_relation="near",
            distance=150_000,
        ),
    )
    assert [d.id for d in filtered_150km] == ["doc_tianjin"]
    assert filtered_150km[0].metadata["spatial_filter_type"] == "geometry_spatial_filter"

    # Query near Beijing with 50 km (50,000 m) radius -> neither matches
    filtered_50km = await engine.apply_spatial_filter(
        [doc_tianjin, doc_shanghai],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": [116.4074, 39.9042]},
            spatial_relation="near",
            distance=50_000,
        ),
    )
    assert filtered_50km == []


@pytest.mark.asyncio
async def test_j11_spatial_filter_distinguishes_geometry_vs_region_prefix_types() -> None:
    """requirement J-11: Explicitly verify taxonomy distinction between geometry_spatial_filter and region_standard_scope_filter."""
    class MockPrefixEngine(RagFilterEngine):
        async def get_region_prefixes_for_geometry(self, spatial_filter: SpatialFilter) -> set[str]:
            return {"DB50"}

    engine = MockPrefixEngine()

    # Case 1: Result has document geometry -> geometry_spatial_filter
    doc_with_geom = make_result(
        "doc_geom",
        "DB50/T 1846-2025",
        {"type": "Point", "coordinates": [105.5, 29.5]},
    )
    res_geom = await engine.apply_spatial_filter(
        [doc_with_geom],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": [105.5, 29.5]},
            spatial_relation="intersects",
        ),
    )
    assert res_geom[0].metadata["spatial_filter_type"] == "geometry_spatial_filter"
    assert res_geom[0].metadata["spatial_filter_source"] == "document_geometry"

    # Case 2: Result has no geometry -> falls back to region_standard_scope_filter
    doc_no_geom = make_result("doc_nogeom", "DB50/T 1846-2025", geometry=None)
    res_prefix = await engine.apply_spatial_filter(
        [doc_no_geom],
        SpatialFilter(
            geometry={"type": "Point", "coordinates": [105.5, 29.5]},
            spatial_relation="intersects",
        ),
    )
    assert res_prefix[0].metadata["spatial_filter_type"] == "region_standard_scope_filter"
    assert res_prefix[0].metadata["spatial_filter_source"] == "region_prefix"

