"""Tests for Phase 3: Spatial Chunked and Resumable Upload."""

from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from app.services.spatial_chunked_upload_service import (
    ChunkVerificationError,
    ChunkedUploadError,
    UploadPermissionError,
    SpatialChunkedUploadService,
)


@pytest.mark.asyncio
async def test_chunked_upload_full_lifecycle(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)

    part1 = b"Chunk 1: GeoJSON Header {"
    part2 = b"'type': 'FeatureCollection', "
    part3 = b"'features': []}"
    full_content = part1 + part2 + part3
    full_hash = hashlib.sha256(full_content).hexdigest()

    # 1. Initiate upload
    meta = await svc.initiate_upload(
        filename="roads.geojson",
        total_size=len(full_content),
        total_chunks=3,
        file_hash=full_hash,
    )
    assert meta.upload_id.startswith("upl_")
    assert meta.total_chunks == 3

    # 2. Upload chunks in random order (e.g. chunk 1, then chunk 0, then chunk 2)
    s1 = await svc.upload_chunk(
        upload_id=meta.upload_id,
        chunk_index=1,
        chunk_bytes=part2,
        chunk_hash=hashlib.sha256(part2).hexdigest(),
    )
    assert s1["ready_to_complete"] is False

    # 3. Check status for resumption
    status = await svc.get_status(meta.upload_id)
    assert status["uploaded_chunks"] == [1]
    assert status["missing_chunks"] == [0, 2]

    # Upload chunk 0
    await svc.upload_chunk(
        upload_id=meta.upload_id,
        chunk_index=0,
        chunk_bytes=part1,
    )

    # Upload chunk 2
    s3 = await svc.upload_chunk(
        upload_id=meta.upload_id,
        chunk_index=2,
        chunk_bytes=part3,
    )
    assert s3["ready_to_complete"] is True

    # 4. Complete upload and verify assembled file
    completed = await svc.complete_upload(meta.upload_id)
    assert completed["completed"] is True
    assert completed["file_hash"] == full_hash
    assert Path(completed["assembled_path"]).read_bytes() == full_content


@pytest.mark.asyncio
async def test_chunk_hash_mismatch_rejected(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(
        filename="data.shp",
        total_size=100,
        total_chunks=1,
    )

    with pytest.raises(ChunkVerificationError):
        await svc.upload_chunk(
            upload_id=meta.upload_id,
            chunk_index=0,
            chunk_bytes=b"corrupted bytes",
            chunk_hash="bad_hash_hex_12345",
        )


@pytest.mark.asyncio
async def test_completion_without_all_chunks_fails(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(
        filename="incomplete.geojson",
        total_size=200,
        total_chunks=2,
    )
    await svc.upload_chunk(
        upload_id=meta.upload_id,
        chunk_index=0,
        chunk_bytes=b"part 1",
    )

    with pytest.raises(ChunkedUploadError, match="missing chunks"):
        await svc.complete_upload(meta.upload_id)

@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../escape.geojson", "/tmp/escape.geojson", r"..\\escape.geojson", r"C:\\temp\\escape.geojson"])
async def test_initiate_rejects_unsafe_filename(tmp_path: Path, filename: str) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    with pytest.raises(ValueError):
        await svc.initiate_upload(filename=filename, total_size=1, total_chunks=1)



@pytest.mark.asyncio
async def test_completion_rejects_assembled_size_mismatch(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(filename="data.geojson", total_size=3, total_chunks=1)
    await svc.upload_chunk(upload_id=meta.upload_id, chunk_index=0, chunk_bytes=b"abc")
    (tmp_path / meta.upload_id / "chunk_0.part").write_bytes(b"oversized")
    with pytest.raises(ChunkedUploadError, match="size"):
        await svc.complete_upload(meta.upload_id)


@pytest.mark.asyncio
async def test_upload_chunk_rejects_aggregate_size_overflow(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(filename="data.geojson", total_size=3, total_chunks=2)
    await svc.upload_chunk(upload_id=meta.upload_id, chunk_index=0, chunk_bytes=b"ab")
    with pytest.raises(ValueError, match="size"):
        await svc.upload_chunk(upload_id=meta.upload_id, chunk_index=1, chunk_bytes=b"cd")

@pytest.mark.asyncio
@pytest.mark.parametrize("upload_id", ["../outside", r"..\\outside", "/tmp/outside", "C:\\outside", "upl_../../outside"])
async def test_rejects_unsafe_upload_id(tmp_path: Path, upload_id: str) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    with pytest.raises(ValueError, match="upload_id"):
        await svc.get_status(upload_id)

@pytest.mark.asyncio
async def test_rejects_metadata_assembled_path_outside_session(tmp_path: Path) -> None:
    import json

    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(filename="data.geojson", total_size=3, total_chunks=1)
    meta_path = tmp_path / meta.upload_id / "meta.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["assembled_path"] = str(tmp_path.parent / "outside.geojson")
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ChunkedUploadError, match="escapes"):
        await svc.get_status(meta.upload_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["meta.json", "chunk_0.part", "META.JSON", "data:stream", "CON", "nul.geojson", "data.geojson.", "data.geojson ", "bad\x00name"])
async def test_initiate_rejects_internal_and_windows_special_names(tmp_path: Path, filename: str) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    with pytest.raises(ValueError, match="filename"):
        await svc.initiate_upload(filename=filename, total_size=1, total_chunks=1)

@pytest.mark.asyncio
async def test_upload_owner_can_resume_but_other_principal_cannot(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(
        filename="owned.geojson", total_size=4, total_chunks=2, principal_id="user:alice"
    )
    await svc.upload_chunk(
        upload_id=meta.upload_id, chunk_index=0, chunk_bytes=b"ab", principal_id="user:alice"
    )

    with pytest.raises(UploadPermissionError):
        await svc.get_status(meta.upload_id, principal_id="user:bob")
    with pytest.raises(UploadPermissionError):
        await svc.upload_chunk(
            upload_id=meta.upload_id, chunk_index=1, chunk_bytes=b"cd", principal_id="user:bob"
        )
    with pytest.raises(UploadPermissionError):
        await svc.complete_upload(meta.upload_id, principal_id="user:bob")

    status = await svc.get_status(meta.upload_id, principal_id="user:alice")
    assert status["uploaded_chunks"] == [0]
    await svc.upload_chunk(
        upload_id=meta.upload_id, chunk_index=1, chunk_bytes=b"cd", principal_id="user:alice"
    )
    completed = await svc.complete_upload(meta.upload_id, principal_id="user:alice")
    assert completed["completed"] is True
    assert Path(completed["assembled_path"]).read_bytes() == b"abcd"


@pytest.mark.asyncio
async def test_legacy_unowned_session_fails_closed_for_api_principals(tmp_path: Path) -> None:
    svc = SpatialChunkedUploadService(base_dir=tmp_path)
    meta = await svc.initiate_upload(filename="legacy.geojson", total_size=2, total_chunks=1)
    with pytest.raises(UploadPermissionError):
        await svc.get_status(meta.upload_id, principal_id="user:alice")
    assert (await svc.get_status(meta.upload_id))["upload_id"] == meta.upload_id
