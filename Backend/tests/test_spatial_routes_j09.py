"""Tests for Phase J-09: Spatial routes error taxonomy and 503 DB unavailable mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException, status

from app.api.spatial_routes import get_provinces


@pytest.mark.asyncio
async def test_j09_get_provinces_maps_db_unavailable_to_503() -> None:
    """requirement J-09: DB operational/connection failures must map to 503 SERVICE_UNAVAILABLE."""
    with patch("app.services.spatial_service.SpatialService.get_provinces", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = RuntimeError("OperationalError: connection to server on socket failed: Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await get_provinces(simplify=0.001)

        assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "空间数据库不可用" in exc_info.value.detail


@pytest.mark.asyncio
async def test_j09_get_provinces_maps_unexpected_error_to_500() -> None:
    """requirement J-09: Non-connection internal errors map to 500 INTERNAL_SERVER_ERROR."""
    with patch("app.services.spatial_service.SpatialService.get_provinces", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = ValueError("Corrupted GeoJSON parsing internal error")

        with pytest.raises(HTTPException) as exc_info:
            await get_provinces(simplify=0.001)

        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "获取行政区划数据失败" in exc_info.value.detail


@pytest.mark.asyncio
async def test_j09_get_provinces_returns_feature_collection_on_success() -> None:
    """requirement J-09: Successful query returns 200 FeatureCollection."""
    expected = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": 1,
                "properties": {"adcode": "510000", "region_name": "四川省"},
                "geometry": {"type": "Polygon", "coordinates": [[[104, 30], [105, 30], [105, 31], [104, 31], [104, 30]]]},
            }
        ],
    }
    with patch("app.services.spatial_service.SpatialService.get_provinces", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = expected
        result = await get_provinces(simplify=0.001)
        assert result == expected
