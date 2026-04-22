"""
文档管理 API 路由
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from typing import List, Optional, Dict
from pydantic import BaseModel
import shutil
import os

from app.core.config import settings
from app.services.document_service import DocumentService

router = APIRouter()


class DocumentInfo(BaseModel):
    """文档信息"""
    id: str
    title: str
    file_type: str
    size: int
    upload_time: str
    metadata: Optional[dict] = None


class UploadResponse(BaseModel):
    """上传响应"""
    document_id: str
    filename: str
    size: int
    message: str


class PresignedRequest(BaseModel):
    filename: str

class PresignedResponse(BaseModel):
    document_id: str
    upload_url: str
    object_name: str
    access_url: str

@router.post("/presigned-url", response_model=PresignedResponse)
async def generate_presigned_url(
    request: PresignedRequest,
    document_service: DocumentService = Depends(DocumentService)
):
    """前端直接请求 MinIO 预签名 URL 用于直传"""
    try:
        url_data = await document_service.generate_presigned_url_for_upload(request.filename)
        return PresignedResponse(**url_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取上传预签名失败: {str(e)}")

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(..., description="上传的文件"),
    title: Optional[str] = Form(None, description="文档标题"),
    metadata: Optional[str] = Form(None, description="JSON格式的元数据"),
    document_service: DocumentService = Depends(DocumentService)
):
    """
    服务端上传文档 (Legacy/Fallback)
    """
    try:
        file_content = await file.read()
        
        import json
        from app.models.document_models import DocumentMetadata
        metadata_dict = json.loads(metadata) if metadata else {}
        doc_meta = DocumentMetadata(
            title=title or file.filename,
            source=metadata_dict.get("source", "upload"),
            document_type=metadata_dict.get("document_type", "unknown")
        )

        doc = await document_service.upload_document(
            file_content=file_content,
            filename=file.filename,
            metadata=doc_meta
        )

        return UploadResponse(
            document_id=doc.id,
            filename=doc.filename,
            size=doc.file_size,
            message="文件上传通过服务端中转成功"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")


@router.get("/list")
async def list_documents(
    page: int = Query(1, description="页码"),
    page_size: int = Query(20, description="每页数量"),
    file_type: Optional[str] = Query(None, description="文件类型过滤")
):
    """
    获取文档列表

    Args:
        page: 页码
        page_size: 每页数量
        file_type: 文件类型过滤

    Returns:
        文档列表
    """
    try:
        # TODO: 从数据库获取文档列表
        documents = []

        return {
            "page": page,
            "page_size": page_size,
            "total": len(documents),
            "documents": documents
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")


@router.get("/{doc_id}")
async def get_document_info(doc_id: str):
    """
    获取文档详情

    Args:
        doc_id: 文档ID

    Returns:
        文档详情
    """
    try:
        # TODO: 从数据库获取文档详情
        document = {
            "id": doc_id,
            "title": "示例文档",
            "file_type": "pdf",
            "size": 102400,
            "upload_time": "2024-01-01 10:00:00",
            "metadata": {}
        }

        return document
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档详情失败: {str(e)}")


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """
    删除文档

    Args:
        doc_id: 文档ID

    Returns:
        删除结果
    """
    try:
        # TODO: 从数据库删除文档记录
        # TODO: 删除对应的向量嵌入
        # TODO: 删除物理文件

        return {
            "document_id": doc_id,
            "message": "文档删除成功"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除文档失败: {str(e)}")


@router.post("/batch-upload")
async def batch_upload_documents(
    files: List[UploadFile] = File(..., description="批量上传的文件列表")
):
    """
    批量上传文档

    Args:
        files: 文件列表

    Returns:
        批量上传结果
    """
    try:
        results = []
        for file in files:
            # 调用单个上传逻辑
            result = await upload_document(file)
            results.append(result)

        return {
            "total": len(files),
            "success": len(results),
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量上传失败: {str(e)}")


@router.post("/reindex/{doc_id}")
async def reindex_document(doc_id: str):
    """
    重新索引文档（重新生成向量嵌入）

    Args:
        doc_id: 文档ID

    Returns:
        重新索引结果
    """
    try:
        # TODO: 重新提取文本内容
        # TODO: 重新生成向量嵌入
        # TODO: 更新向量数据库

        return {
            "document_id": doc_id,
            "message": "文档重新索引成功"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新索引失败: {str(e)}")


@router.get("/statistics")
async def get_document_statistics():
    """
    获取文档统计信息

    Returns:
        文档统计信息
    """
    try:
        # TODO: 从数据库获取统计信息
        statistics = {
            "total_documents": 0,
            "total_size": 0,
            "by_file_type": {
                "pdf": 0,
                "docx": 0,
                "txt": 0
            },
            "by_date": {}
        }

        return statistics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")