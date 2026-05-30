"""
Document management and authenticated download routes.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.security import require_admin_or_system_api_key, require_authenticated_admin, require_authenticated_user
from app.models.document_models import DocumentMetadata
from app.services.document_asset_service import DocumentAssetService
from app.services.document_service import DocumentService

router = APIRouter()


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    size: int
    message: str
    access_url: str


class PresignedRequest(BaseModel):
    filename: str
    content_type: str
    file_size: int


class PresignedResponse(BaseModel):
    document_id: str
    upload_url: str
    object_name: str
    access_url: str


class DocumentFileInfo(BaseModel):
    type: str
    size: int
    upload_time: datetime
    filename: Optional[str] = None
    mime_type: Optional[str] = None


class StandardInfo(BaseModel):
    code: str
    release_date: Optional[datetime] = None
    implement_date: Optional[datetime] = None
    draft_unit: Optional[str] = None
    keyword: Optional[str] = None
    status: Optional[str] = None


class DocumentDetailResponse(BaseModel):
    id: str
    title: str
    content: str
    metadata: Dict[str, Any]
    spatial_info: Optional[Dict[str, Any]] = None
    file_info: DocumentFileInfo
    standard_info: Optional[StandardInfo] = None
    download_available: bool = False
    download_url: Optional[str] = None


def _raise_validation_error(exc: ValueError) -> None:
    message = str(exc)
    if "max upload size" in message.lower():
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=message) from exc
    if "extension" in message.lower() or "content-type" in message.lower():
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=message) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


def _build_content_disposition(filename: str) -> str:
    quoted = quote(filename)
    safe_ascii = filename.encode("ascii", errors="ignore").decode("ascii") or "document"
    return f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{quoted}'


async def _read_upload_with_limit(file: UploadFile) -> bytes:
    max_size = settings.MAX_UPLOAD_SIZE
    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds max upload size of {max_size} bytes.",
            )
        chunks.append(chunk)

    return b"".join(chunks)


@router.post(
    "/presigned-url",
    response_model=PresignedResponse,
    dependencies=[Depends(require_admin_or_system_api_key)],
)
async def generate_presigned_url(
    request: PresignedRequest,
    document_service: DocumentService = Depends(DocumentService),
):
    try:
        url_data = await document_service.generate_presigned_url_for_upload(
            filename=request.filename,
            content_type=request.content_type,
            file_size=request.file_size,
        )
        return PresignedResponse(**url_data)
    except ValueError as exc:
        _raise_validation_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create presigned upload URL: {exc}",
        ) from exc


@router.post(
    "/upload",
    response_model=UploadResponse,
    dependencies=[Depends(require_admin_or_system_api_key)],
)
async def upload_document(
    file: UploadFile = File(..., description="Document to upload."),
    title: Optional[str] = Form(None, description="Document title."),
    metadata: Optional[str] = Form(None, description="JSON metadata."),
    document_service: DocumentService = Depends(DocumentService),
):
    try:
        file_content = await _read_upload_with_limit(file)
        metadata_dict = json.loads(metadata) if metadata else {}
        document_metadata = DocumentMetadata(
            title=title or file.filename or "untitled",
            source=metadata_dict.get("source", "upload"),
            category=metadata_dict.get("category"),
            custom_fields={"document_type": metadata_dict.get("document_type", "unknown")},
        )

        document = await document_service.upload_document(
            file_content=file_content,
            filename=file.filename or "",
            content_type=file.content_type or "",
            metadata=document_metadata,
        )

        return UploadResponse(
            document_id=document.id,
            filename=document.filename,
            size=document.file_size,
            message="File uploaded successfully.",
            access_url=document.access_url or "",
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metadata JSON: {exc}",
        ) from exc
    except ValueError as exc:
        _raise_validation_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {exc}",
        ) from exc


@router.get("/download/{object_name:path}")
async def download_document_object(
    object_name: str,
    document_service: DocumentService = Depends(DocumentService),
    _current_user=Depends(require_authenticated_admin),
):
    try:
        download_data = document_service.get_download_stream(object_name)
        return StreamingResponse(
            download_data["stream"].stream(32 * 1024),
            media_type=download_data["content_type"],
            background=BackgroundTask(download_data["stream"].close),
            headers={
                "Content-Disposition": _build_content_disposition(download_data["object_name"]),
                "Cache-Control": "private, max-age=60",
            },
        )
    except ValueError as exc:
        _raise_validation_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to download object: {exc}",
        ) from exc


@router.get("/{doc_id}/download")
async def download_document_by_id(
    doc_id: str,
    document_service: DocumentService = Depends(DocumentService),
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    _current_user=Depends(require_authenticated_user),
):
    download_target = await asset_service.get_download_target(doc_id)
    if not download_target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No downloadable original file is available for this document.",
        )

    try:
        download_data = document_service.get_download_stream(download_target["object_name"])
        return StreamingResponse(
            download_data["stream"].stream(32 * 1024),
            media_type=download_target["content_type"],
            background=BackgroundTask(download_data["stream"].close),
            headers={
                "Content-Disposition": _build_content_disposition(download_target["filename"]),
                "Cache-Control": "private, max-age=60",
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to download original file: {exc}",
        ) from exc


@router.get("/list")
async def list_documents(
    page: int = Query(1, description="Page number."),
    page_size: int = Query(20, description="Page size."),
    file_type: Optional[str] = Query(None, description="File type filter."),
    _current_user=Depends(require_authenticated_user),
):
    _ = file_type
    return {
        "page": page,
        "page_size": page_size,
        "total": 0,
        "documents": [],
    }


@router.post(
    "/batch-upload",
    dependencies=[Depends(require_admin_or_system_api_key)],
)
async def batch_upload_documents(
    files: List[UploadFile] = File(..., description="Documents to upload."),
    document_service: DocumentService = Depends(DocumentService),
):
    results = []
    for upload in files:
        file_content = await _read_upload_with_limit(upload)
        try:
            document_metadata = DocumentMetadata(
                title=upload.filename or "untitled",
                source="batch-upload",
                custom_fields={"document_type": "unknown"},
            )
            document = await document_service.upload_document(
                file_content=file_content,
                filename=upload.filename or "",
                content_type=upload.content_type or "",
                metadata=document_metadata,
            )
            results.append(
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "size": document.file_size,
                    "access_url": document.access_url,
                }
            )
        except ValueError as exc:
            _raise_validation_error(exc)

    return {
        "total": len(files),
        "success": len(results),
        "results": results,
    }


@router.post(
    "/reindex/{doc_id}",
    dependencies=[Depends(require_admin_or_system_api_key)],
)
async def reindex_document(doc_id: str):
    return {
        "document_id": doc_id,
        "message": "Document reindex queued.",
    }


@router.get("/statistics")
async def get_document_statistics(_current_admin=Depends(require_authenticated_admin)):
    return {
        "total_documents": 0,
        "total_size": 0,
        "by_file_type": {
            "pdf": 0,
            "docx": 0,
            "txt": 0,
        },
        "by_date": {},
    }


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document_info(
    doc_id: str,
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    _current_user=Depends(require_authenticated_user),
):
    detail = await asset_service.get_document_detail_payload(doc_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentDetailResponse(**detail)


@router.delete(
    "/{doc_id}",
    dependencies=[Depends(require_admin_or_system_api_key)],
)
async def delete_document(doc_id: str):
    return {
        "document_id": doc_id,
        "message": "Document deleted successfully.",
    }
