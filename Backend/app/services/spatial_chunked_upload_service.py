"""Resumable and chunked upload service for large spatial datasets (GeoJSON, SHP zip).

Supports chunk-by-chunk ingestion, sha256 checksum verification, state inspection,
and resumable assembly for large spatial data files.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
import re
import shutil
import time
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

DEFAULT_UPLOAD_DIR = Path(".runtime/chunked_uploads")


@dataclass
class ChunkedUploadMetadata:
    upload_id: str
    filename: str
    total_size: int
    total_chunks: int
    file_hash: Optional[str]
    uploaded_chunks: list[int]
    created_at: float
    completed: bool = False
    assembled_path: Optional[str] = None
    assembled_hash: Optional[str] = None
    principal_id: Optional[str] = None


class ChunkedUploadError(RuntimeError):
    """Base error for chunked upload failures."""


class ChunkVerificationError(ChunkedUploadError):
    """Raised when chunk or complete file checksum does not match expected hash."""


class UploadPermissionError(ChunkedUploadError):
    """Raised when a principal attempts to access another principal's upload."""


class SpatialChunkedUploadService:
    """Manages chunked and resumable uploads of spatial data files."""

    def __init__(self, base_dir: Path | str = DEFAULT_UPLOAD_DIR) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    @staticmethod
    def _validate_upload_id(upload_id: str) -> None:
        if not isinstance(upload_id, str) or not re.fullmatch(r"upl_[0-9a-f]{32}", upload_id):
            raise ValueError("upload_id must be a valid upload session identifier")

    @staticmethod
    def _validate_filename(filename: str) -> None:
        if not isinstance(filename, str) or not filename or filename in {".", ".."}:
            raise ValueError("filename must be a safe, non-empty filename")
        if (Path(filename).is_absolute() or PurePosixPath(filename).name != filename
                or PureWindowsPath(filename).name != filename
                or "/" in filename or "\\" in filename
                or PureWindowsPath(filename).drive):
            raise ValueError("filename must not contain a path")
        name = filename.casefold()
        device_stem = name.split(".", 1)[0]
        reserved_devices = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
        if (any(ord(char) < 32 for char in filename) or any(char in '<>:"|?*' for char in filename)
                or filename.endswith((".", " ")) or device_stem in reserved_devices
                or name == "meta.json" or re.fullmatch(r"chunk_[0-9]+\.part", name)):
            raise ValueError("filename is reserved or contains unsupported characters")

    def _contained_path(self, path: Path, parent: Path) -> Path:
        resolved_parent = parent.resolve()
        resolved_path = path.resolve()
        if resolved_path != resolved_parent and resolved_parent not in resolved_path.parents:
            raise ChunkedUploadError("Upload path escapes the configured upload directory")
        return resolved_path

    def _session_dir(self, upload_id: str) -> Path:
        self._validate_upload_id(upload_id)
        return self._contained_path(self.base_dir / upload_id, self.base_dir)

    def _meta_path(self, upload_id: str) -> Path:
        return self._session_dir(upload_id) / "meta.json"

    def _load_meta(
        self, upload_id: str, principal_id: Optional[str] = None
    ) -> ChunkedUploadMetadata:
        meta_file = self._contained_path(self._meta_path(upload_id), self._session_dir(upload_id))
        if not meta_file.exists():
            raise ChunkedUploadError(f"Upload session '{upload_id}' not found")
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        meta = ChunkedUploadMetadata(**data)
        self._validate_upload_id(meta.upload_id)
        self._validate_filename(meta.filename)
        if meta.upload_id != upload_id or meta.total_size <= 0 or meta.total_chunks <= 0:
            raise ChunkedUploadError("Upload metadata is invalid")
        if meta.principal_id != principal_id:
            raise UploadPermissionError("Upload session access denied")
        if meta.assembled_path is not None:
            assembled = self._contained_path(Path(meta.assembled_path), self._session_dir(upload_id))
            if assembled.name != meta.filename:
                raise ChunkedUploadError("Upload metadata contains an invalid assembled path")
        return meta

    def _save_meta(self, meta: ChunkedUploadMetadata) -> None:
        meta_file = self._contained_path(self._meta_path(meta.upload_id), self._session_dir(meta.upload_id))
        meta_file.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")

    async def initiate_upload(
        self,
        *,
        filename: str,
        total_size: int,
        total_chunks: int,
        file_hash: Optional[str] = None,
        principal_id: Optional[str] = None,
    ) -> ChunkedUploadMetadata:
        """Initialize a new chunked upload session."""
        self._validate_filename(filename)
        if total_chunks <= 0:
            raise ValueError("total_chunks must be greater than 0")
        if total_size <= 0:
            raise ValueError("total_size must be greater than 0")

        upload_id = f"upl_{uuid4().hex}"
        session_dir = self._session_dir(upload_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        meta = ChunkedUploadMetadata(
            upload_id=upload_id,
            filename=filename,
            total_size=total_size,
            total_chunks=total_chunks,
            file_hash=file_hash.lower() if file_hash else None,
            uploaded_chunks=[],
            created_at=time.time(),
            completed=False,
            principal_id=principal_id,
        )
        self._save_meta(meta)
        return meta

    async def upload_chunk(
        self,
        *,
        upload_id: str,
        chunk_index: int,
        chunk_bytes: bytes,
        chunk_hash: Optional[str] = None,
        principal_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save a chunk and record progress."""
        if chunk_hash:
            actual_hash = hashlib.sha256(chunk_bytes).hexdigest()
            if actual_hash.lower() != chunk_hash.lower():
                raise ChunkVerificationError(
                    f"Chunk {chunk_index} checksum mismatch: expected {chunk_hash}, got {actual_hash}"
                )

        async with self._lock:
            meta = self._load_meta(upload_id, principal_id)
            if meta.completed:
                raise ChunkedUploadError(f"Upload session '{upload_id}' is already completed")
            if chunk_index < 0 or chunk_index >= meta.total_chunks:
                raise ValueError(f"chunk_index {chunk_index} out of bounds [0, {meta.total_chunks - 1}]")

            chunk_file = self._session_dir(upload_id) / f"chunk_{chunk_index}.part"
            current_size = sum(
                (self._session_dir(upload_id) / f"chunk_{idx}.part").stat().st_size
                for idx in meta.uploaded_chunks
                if idx != chunk_index and (self._session_dir(upload_id) / f"chunk_{idx}.part").exists()
            )
            if current_size + len(chunk_bytes) > meta.total_size:
                raise ValueError("Uploaded chunks exceed declared total_size")
            chunk_file.write_bytes(chunk_bytes)

            if chunk_index not in meta.uploaded_chunks:
                meta.uploaded_chunks.append(chunk_index)
                meta.uploaded_chunks.sort()
                self._save_meta(meta)

            return {
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "uploaded_chunks_count": len(meta.uploaded_chunks),
                "total_chunks": meta.total_chunks,
                "ready_to_complete": len(meta.uploaded_chunks) == meta.total_chunks,
            }

    async def get_status(
        self, upload_id: str, principal_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Query uploaded chunks to resume interrupted uploads."""
        meta = self._load_meta(upload_id, principal_id)
        return {
            "upload_id": meta.upload_id,
            "filename": meta.filename,
            "total_size": meta.total_size,
            "total_chunks": meta.total_chunks,
            "uploaded_chunks": meta.uploaded_chunks,
            "missing_chunks": [i for i in range(meta.total_chunks) if i not in meta.uploaded_chunks],
            "completed": meta.completed,
            "assembled_path": meta.assembled_path,
        }

    async def complete_upload(
        self, upload_id: str, principal_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Concatenate all chunks into final file and verify overall checksum."""
        async with self._lock:
            meta = self._load_meta(upload_id, principal_id)
            if meta.completed:
                return {
                    "upload_id": upload_id,
                    "filename": meta.filename,
                    "completed": True,
                    "assembled_path": meta.assembled_path,
                    "file_hash": meta.assembled_hash,
                }

            if len(meta.uploaded_chunks) != meta.total_chunks:
                missing = [i for i in range(meta.total_chunks) if i not in meta.uploaded_chunks]
                raise ChunkedUploadError(
                    f"Cannot complete upload; missing chunks: {missing}"
                )

            session_dir = self._session_dir(upload_id)
            assembled_file = session_dir / meta.filename
            assembled_file = self._contained_path(assembled_file, session_dir)
            actual_size = sum(
                (session_dir / f"chunk_{idx}.part").stat().st_size
                for idx in range(meta.total_chunks)
                if (session_dir / f"chunk_{idx}.part").exists()
            )
            if actual_size != meta.total_size:
                raise ChunkedUploadError(
                    f"Uploaded data size {actual_size} does not match declared total_size {meta.total_size}"
                )
            hasher = hashlib.sha256()

            with open(assembled_file, "wb") as out_f:
                for idx in range(meta.total_chunks):
                    chunk_path = session_dir / f"chunk_{idx}.part"
                    if not chunk_path.exists():
                        raise ChunkedUploadError(f"Chunk file {chunk_path} missing during assembly")
                    data = chunk_path.read_bytes()
                    hasher.update(data)
                    out_f.write(data)

            assembled_hash = hasher.hexdigest()
            if meta.file_hash and meta.file_hash.lower() != assembled_hash.lower():
                assembled_file.unlink(missing_ok=True)
                raise ChunkVerificationError(
                    f"Final file checksum mismatch: expected {meta.file_hash}, got {assembled_hash}"
                )

            # Cleanup part files
            for idx in range(meta.total_chunks):
                part = session_dir / f"chunk_{idx}.part"
                part.unlink(missing_ok=True)

            meta.completed = True
            meta.assembled_path = str(assembled_file)
            meta.assembled_hash = assembled_hash
            self._save_meta(meta)

            return {
                "upload_id": upload_id,
                "filename": meta.filename,
                "completed": True,
                "total_size": assembled_file.stat().st_size,
                "assembled_path": str(assembled_file),
                "file_hash": assembled_hash,
            }


_default_chunk_service: Optional[SpatialChunkedUploadService] = None


def get_spatial_chunked_upload_service() -> SpatialChunkedUploadService:
    global _default_chunk_service
    if _default_chunk_service is None:
        _default_chunk_service = SpatialChunkedUploadService()
    return _default_chunk_service
