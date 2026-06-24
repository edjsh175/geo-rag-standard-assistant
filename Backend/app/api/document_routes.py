"""
Document management and authenticated download routes.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.security import require_admin_or_system_api_key, require_authenticated_admin, require_authenticated_user
from app.models.document_models import (
    DocumentBatchRequest,
    DocumentBatchResponse,
    DocumentBatchResult,
    DocumentJobResponse,
    DocumentListResponse,
    DocumentMetadata,
    DocumentUpdateRequest,
)
from app.services.document_contract_service import DocumentContractService
from app.services.document_asset_service import DocumentAssetService
from app.services.document_lifecycle_service import DocumentLifecycleService
from app.services.document_repository import DocumentRepository
from app.services.document_service import DocumentService

router = APIRouter()

DOCUMENT_UPLOAD_DISABLED_DETAIL = (
    "Document upload and object-storage workflows are disabled. "
    "Set DOCUMENT_UPLOAD_ENABLED=True and configure MinIO/Celery before using this endpoint."
)


def require_document_upload_enabled() -> None:
    if not settings.DOCUMENT_UPLOAD_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DOCUMENT_UPLOAD_DISABLED_DETAIL,
        )


def get_document_service() -> DocumentService:
    require_document_upload_enabled()
    return DocumentService()


def get_document_repository() -> DocumentRepository:
    return DocumentRepository()


def get_document_lifecycle_service() -> DocumentLifecycleService:
    return DocumentLifecycleService()


class UploadResponse(BaseModel):
    document_id: str
    version_id: str
    job_id: str
    filename: str
    size: int
    index_status: str
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


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def _json_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _build_uploaded_detail_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _json_mapping(row.get("metadata"))
    spatial_metadata = _json_mapping(row.get("spatial_metadata")) if row.get("spatial_metadata") else None
    title = row.get("title") or metadata.get("title") or row.get("filename") or str(row.get("id"))
    content = row.get("content_preview") or metadata.get("description") or ""
    custom_fields = _json_mapping(metadata.get("custom_fields"))
    standard_code = metadata.get("standard_code") or custom_fields.get("standard_code")

    return {
        "id": str(row["id"]),
        "title": title,
        "content": content,
        "metadata": {
            **metadata,
            "title": title,
            "description": metadata.get("description") or content,
            "custom_fields": {
                **custom_fields,
                "index_status": row.get("index_status"),
                "chunk_count": row.get("chunk_count", 0),
                "last_error": row.get("last_error"),
            },
        },
        "spatial_info": spatial_metadata,
        "file_info": {
            "type": row.get("file_type") or "unknown",
            "size": int(row.get("file_size") or 0),
            "upload_time": row.get("created_at"),
            "filename": row.get("filename"),
            "mime_type": row.get("mime_type") or "application/octet-stream",
        },
        "standard_info": {
            "code": standard_code or "",
            "release_date": metadata.get("release_date"),
            "implement_date": metadata.get("implement_date"),
            "draft_unit": metadata.get("draft_unit"),
            "keyword": metadata.get("keyword"),
            "status": metadata.get("standard_status"),
        }
        if standard_code
        else None,
        "download_available": bool(row.get("download_url")),
        "download_url": row.get("download_url"),
    }


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
    document_service: DocumentService = Depends(get_document_service),
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
)
async def upload_document(
    file: UploadFile = File(..., description="Document to upload."),
    title: Optional[str] = Form(None, description="Document title."),
    metadata: Optional[str] = Form(None, description="JSON metadata."),
    document_service: DocumentService = Depends(get_document_service),
    actor=Depends(require_admin_or_system_api_key),
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
            requested_by=str(actor),
        )

        return UploadResponse(
            document_id=document.id,
            version_id=document.current_version_id or "",
            job_id=document.job_id or "",
            filename=document.filename,
            size=document.file_size,
            index_status=document.indexing_status,
            message="File uploaded and indexing queued.",
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
    document_service: DocumentService = Depends(get_document_service),
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
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    repository: DocumentRepository = Depends(get_document_repository),
    _current_user=Depends(require_authenticated_user),
):
    if _is_uuid(doc_id):
        uploaded_target = await repository.get_download_target(doc_id)
        if uploaded_target:
            require_document_upload_enabled()
            try:
                document_service = get_document_service()
                download_data = document_service.get_download_stream(uploaded_target["object_name"])
                return StreamingResponse(
                    download_data["stream"].stream(32 * 1024),
                    media_type=uploaded_target["content_type"],
                    background=BackgroundTask(download_data["stream"].close),
                    headers={
                        "Content-Disposition": _build_content_disposition(uploaded_target["filename"]),
                        "Cache-Control": "private, max-age=60",
                    },
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Failed to download uploaded document: {exc}",
                ) from exc

    if await contract_service.is_document_deleted(doc_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    download_target = await asset_service.get_download_target(doc_id)
    if not download_target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No downloadable original file is available for this document.",
        )

    require_document_upload_enabled()
    try:
        document_service = get_document_service()
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


@router.get("/list", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, description="Page number."),
    page_size: int = Query(20, description="Page size."),
    file_type: Optional[str] = Query(None, description="File type filter."),
    repository: DocumentRepository = Depends(get_document_repository),
    _current_user=Depends(require_authenticated_user),
):
    result = await repository.list_documents(page=page, page_size=page_size, file_type=file_type)
    return {
        "page": page,
        "page_size": page_size,
        "total": result["total"],
        "documents": [
            {
                **document,
                "download_available": bool(document.get("download_url")),
            }
            for document in result["documents"]
        ],
    }


@router.post(
    "/batch-upload",
    dependencies=[Depends(require_admin_or_system_api_key)],
)
async def batch_upload_documents(
    files: List[UploadFile] = File(..., description="Documents to upload."),
    document_service: DocumentService = Depends(get_document_service),
    actor=Depends(require_admin_or_system_api_key),
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
                requested_by=str(actor),
            )
            results.append(
                {
                    "document_id": document.id,
                    "version_id": document.current_version_id,
                    "job_id": document.job_id,
                    "index_status": document.indexing_status,
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


@router.post("/reindex/{doc_id}")
async def reindex_document(
    doc_id: str,
    contract_service: DocumentContractService = Depends(DocumentContractService),
    lifecycle_service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
    actor=Depends(require_admin_or_system_api_key),
):
    if _is_uuid(doc_id):
        require_document_upload_enabled()
        job_id = await lifecycle_service.queue_reindex_job(doc_id, str(actor))
        if job_id:
            return {
                "document_id": doc_id,
                "job_id": job_id,
                "message": "Document reindex queued.",
            }
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return {
        "document_id": doc_id,
        "job_id": await contract_service.queue_reindex_job(doc_id, str(actor)),
        "message": "Document reindex queued.",
    }


@router.post(
    "/batch",
    response_model=DocumentBatchResponse,
)
async def batch_document_operation(
    request: DocumentBatchRequest,
    contract_service: DocumentContractService = Depends(DocumentContractService),
    lifecycle_service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
    repository: DocumentRepository = Depends(get_document_repository),
    actor=Depends(require_admin_or_system_api_key),
):
    results: list[DocumentBatchResult] = []
    legacy_ids: list[str] = []

    for doc_id in request.document_ids:
        if not _is_uuid(doc_id):
            legacy_ids.append(doc_id)
            continue

        try:
            if request.operation != "delete":
                require_document_upload_enabled()
            if request.operation == "delete":
                deleted = await repository.soft_delete(doc_id, str(actor))
                results.append(
                    DocumentBatchResult(
                        document_id=doc_id,
                        success=deleted,
                        status="deleted" if deleted else "not_found",
                        message="Document soft-deleted." if deleted else "Document not found.",
                    )
                )
            else:
                job_id = await lifecycle_service.queue_reindex_job(doc_id, str(actor))
                results.append(
                    DocumentBatchResult(
                        document_id=doc_id,
                        success=bool(job_id),
                        status="queued" if job_id else "not_found",
                        message="Document reindex queued." if job_id else "Document not found.",
                        job_id=job_id,
                    )
                )
        except Exception as exc:
            results.append(
                DocumentBatchResult(
                    document_id=doc_id,
                    success=False,
                    status="failed",
                    message=str(exc),
                )
            )

    if legacy_ids:
        legacy_response = await contract_service.batch_operation(
            DocumentBatchRequest(operation=request.operation, document_ids=legacy_ids),
            requested_by=str(actor),
        )
        results.extend(legacy_response.results)

    success_count = sum(1 for item in results if item.success)
    return DocumentBatchResponse(
        operation=request.operation,
        total=len(results),
        success=success_count,
        failed=len(results) - success_count,
        results=results,
    )


@router.get("/statistics")
async def get_document_statistics(
    repository: DocumentRepository = Depends(get_document_repository),
    _current_admin=Depends(require_authenticated_admin),
):
    return await repository.statistics()


@router.get("/jobs/{job_id}", response_model=DocumentJobResponse)
async def get_document_job(
    job_id: str,
    repository: DocumentRepository = Depends(get_document_repository),
    _current_user=Depends(require_authenticated_user),
):
    job = await repository.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document index job not found.")
    return DocumentJobResponse(**job)


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document_info(
    doc_id: str,
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    repository: DocumentRepository = Depends(get_document_repository),
    _current_user=Depends(require_authenticated_user),
):
    if _is_uuid(doc_id):
        uploaded_detail = await repository.get_uploaded_document_detail(doc_id)
        if uploaded_detail:
            return DocumentDetailResponse(**_build_uploaded_detail_payload(uploaded_detail))

    if await contract_service.is_document_deleted(doc_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    detail = await asset_service.get_document_detail_payload(doc_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    merged_detail = await contract_service.apply_document_overrides(doc_id, detail)
    if not merged_detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentDetailResponse(**merged_detail)


@router.patch(
    "/{doc_id}",
    response_model=DocumentDetailResponse,
)
async def update_document_info(
    doc_id: str,
    update_request: DocumentUpdateRequest,
    asset_service: DocumentAssetService = Depends(DocumentAssetService),
    contract_service: DocumentContractService = Depends(DocumentContractService),
    lifecycle_service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
    repository: DocumentRepository = Depends(get_document_repository),
    actor=Depends(require_admin_or_system_api_key),
):
    if _is_uuid(doc_id):
        if update_request.metadata:
            updated = await repository.update_metadata(doc_id, update_request.metadata)
            if not updated:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        if update_request.reindex:
            require_document_upload_enabled()
            await lifecycle_service.queue_reindex_job(doc_id, str(actor))
        uploaded_detail = await repository.get_uploaded_document_detail(doc_id)
        if not uploaded_detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        return DocumentDetailResponse(**_build_uploaded_detail_payload(uploaded_detail))

    if await contract_service.is_document_deleted(doc_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    detail = await asset_service.get_document_detail_payload(doc_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    merged_detail = await contract_service.update_document_metadata(
        doc_id=doc_id,
        current_detail=detail,
        update_request=update_request,
        requested_by=str(actor),
    )
    if not merged_detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentDetailResponse(**merged_detail)


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    contract_service: DocumentContractService = Depends(DocumentContractService),
    repository: DocumentRepository = Depends(get_document_repository),
    actor=Depends(require_admin_or_system_api_key),
):
    if _is_uuid(doc_id):
        deleted = await repository.soft_delete(doc_id, str(actor))
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        return {
            "document_id": doc_id,
            "message": "Document soft-deleted successfully.",
        }

    await contract_service.soft_delete_document(doc_id, str(actor))
    return {
        "document_id": doc_id,
        "message": "Document soft-deleted successfully.",
    }
