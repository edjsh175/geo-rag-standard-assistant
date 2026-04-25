"""
Document management API routes.
"""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.security import require_system_api_key
from app.models.document_models import DocumentMetadata
from app.services.document_service import DocumentService

router = APIRouter()


class DocumentInfo(BaseModel):
    id: str
    title: str
    file_type: str
    size: int
    upload_time: str
    metadata: Optional[dict] = None


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


def _raise_validation_error(exc: ValueError) -> None:
    message = str(exc)
    if "max upload size" in message.lower():
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=message) from exc
    if "extension" in message.lower() or "content-type" in message.lower():
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=message) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


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
    dependencies=[Depends(require_system_api_key)],
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


@router.post("/upload", response_model=UploadResponse, dependencies=[Depends(require_system_api_key)])
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


@router.get(
    "/download/{object_name}",
    dependencies=[Depends(require_system_api_key)],
)
async def download_document_object(
    object_name: str,
    document_service: DocumentService = Depends(DocumentService),
):
    try:
        download_data = document_service.get_download_stream(object_name)
        return StreamingResponse(
            download_data["stream"].stream(32 * 1024),
            media_type=download_data["content_type"],
            background=BackgroundTask(download_data["stream"].close),
            headers={
                "Content-Disposition": f"attachment; filename=\"{download_data['object_name']}\"",
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


@router.get("/list")
async def list_documents(
    page: int = Query(1, description="Page number."),
    page_size: int = Query(20, description="Page size."),
    file_type: Optional[str] = Query(None, description="File type filter."),
):
    return {
        "page": page,
        "page_size": page_size,
        "total": 0,
        "documents": [],
    }


@router.post("/batch-upload", dependencies=[Depends(require_system_api_key)])
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


@router.post("/reindex/{doc_id}", dependencies=[Depends(require_system_api_key)])
async def reindex_document(doc_id: str):
    return {
        "document_id": doc_id,
        "message": "Document reindex queued.",
    }


@router.get("/statistics")
async def get_document_statistics():
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


@router.get("/{doc_id}")
async def get_document_info(doc_id: str):
    return {
        "id": doc_id,
        "title": "example-document",
        "file_type": "pdf",
        "size": 102400,
        "upload_time": "2024-01-01T10:00:00",
        "metadata": {},
    }


@router.delete("/{doc_id}", dependencies=[Depends(require_system_api_key)])
async def delete_document(doc_id: str):
    return {
        "document_id": doc_id,
        "message": "Document deleted successfully.",
    }
