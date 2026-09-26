from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.spatial_routes import (
    SpatialQuery,
    calculate_intersection,
    create_buffer,
    geocode_address,
    reverse_geocode,
    spatial_query,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "capability"),
    [
        (
            lambda: spatial_query(
                SpatialQuery(geometry={"type": "Point", "coordinates": [104, 30]})
            ),
            "spatial query",
        ),
        (lambda: geocode_address(address="任意地址", city=None), "geocoding"),
        (lambda: reverse_geocode(lon=104, lat=30), "reverse geocoding"),
        (lambda: create_buffer(lon=104, lat=30, distance=1000), "buffer analysis"),
        (
            lambda: calculate_intersection(
                {"type": "Point", "coordinates": [104, 30]},
                {"type": "Point", "coordinates": [104, 30]},
            ),
            "geometry intersection",
        ),
    ],
)
async def test_unimplemented_public_spatial_routes_fail_closed(call, capability: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await call()

    assert exc_info.value.status_code == 501
    assert capability in str(exc_info.value.detail)
