from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import spatial_routes
from app.core.auth import UserIdentity
from app.services.spatial_chunked_upload_service import UploadPermissionError


class UploadServiceStub:
    def __init__(self) -> None:
        self.calls = []

    async def initiate_upload(self, **kwargs):
        self.calls.append(("initiate", kwargs))
        return SimpleNamespace(upload_id="upl_0123456789abcdef0123456789abcdef", filename=kwargs["filename"], total_chunks=1, total_size=2)

    async def upload_chunk(self, **kwargs):
        self.calls.append(("chunk", kwargs))
        return {"upload_id": kwargs["upload_id"]}

    async def get_status(self, upload_id, *, principal_id):
        kwargs = {"upload_id": upload_id, "principal_id": principal_id}
        self.calls.append(("status", kwargs))
        return {"upload_id": upload_id}

    async def complete_upload(self, upload_id, *, principal_id):
        kwargs = {"upload_id": upload_id, "principal_id": principal_id}
        self.calls.append(("complete", kwargs))
        return {"upload_id": upload_id, "assembled_path": "server/path"}


class RequestStub:
    async def body(self) -> bytes:
        return b"ok"


@pytest.mark.asyncio
async def test_upload_routes_bind_authenticated_principal_to_all_operations(monkeypatch) -> None:
    service = UploadServiceStub()
    monkeypatch.setattr(
        "app.services.spatial_chunked_upload_service.get_spatial_chunked_upload_service",
        lambda: service,
    )
    identity = UserIdentity(username="demo", role="visitor", visitor_id="visitor-42", ip_hash="ip")

    await spatial_routes.init_chunked_upload(
        spatial_routes.ChunkedUploadInitRequest(filename="data.geojson", total_size=2, total_chunks=1),
        current_user=identity,
    )
    await spatial_routes.upload_spatial_chunk(
        upload_id="upl_0123456789abcdef0123456789abcdef",
        chunk_index=0,
        chunk_hash=None,
        request=RequestStub(),
        current_user=identity,
    )
    await spatial_routes.get_chunked_upload_status(
        upload_id="upl_0123456789abcdef0123456789abcdef", current_user=identity
    )
    await spatial_routes.complete_chunked_upload(
        spatial_routes.ChunkedUploadCompleteRequest(upload_id="upl_0123456789abcdef0123456789abcdef"),
        current_user=identity,
    )

    assert [entry[1]["principal_id"] for entry in service.calls] == ["visitor:visitor-42"] * 4


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chunk", "status", "complete"])
async def test_upload_routes_map_owner_mismatch_to_forbidden(monkeypatch, operation: str) -> None:
    class ForbiddenService(UploadServiceStub):
        async def upload_chunk(self, **kwargs):
            raise UploadPermissionError("Upload session access denied")

        async def get_status(self, upload_id, *, principal_id):
            raise UploadPermissionError("Upload session access denied")

        async def complete_upload(self, upload_id, *, principal_id):
            raise UploadPermissionError("Upload session access denied")

    monkeypatch.setattr(
        "app.services.spatial_chunked_upload_service.get_spatial_chunked_upload_service",
        ForbiddenService,
    )
    identity = UserIdentity(username="alice", role="admin")
    with pytest.raises(HTTPException) as exc_info:
        if operation == "chunk":
            await spatial_routes.upload_spatial_chunk(
                upload_id="upl_0123456789abcdef0123456789abcdef",
                chunk_index=0,
                chunk_hash=None,
                request=RequestStub(),
                current_user=identity,
            )
        elif operation == "status":
            await spatial_routes.get_chunked_upload_status(
                upload_id="upl_0123456789abcdef0123456789abcdef",
                current_user=identity,
            )
        else:
            await spatial_routes.complete_chunked_upload(
                spatial_routes.ChunkedUploadCompleteRequest(
                    upload_id="upl_0123456789abcdef0123456789abcdef"
                ),
                current_user=identity,
            )
    assert exc_info.value.status_code == 403