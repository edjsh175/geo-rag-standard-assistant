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
