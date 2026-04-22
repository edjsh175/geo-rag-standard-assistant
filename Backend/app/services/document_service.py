"""
文档管理服务
"""

import logging
import uuid
import os
import shutil
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.core.database import db_manager
from app.models.document_models import (
    Document, DocumentMetadata, SpatialMetadata,
    UploadRequest, DocumentUpdateRequest
)

logger = logging.getLogger(__name__)


from minio import Minio
from minio.error import S3Error
from datetime import timedelta

class DocumentService:
    """文档/空间资产管理服务 (MinIO Native)"""

    def __init__(self):
        self.upload_dir = settings.UPLOAD_DIR
        self.minio_client = Minio(
            settings.MINIO_URL,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=False
        )
        self.bucket_name = settings.MINIO_BUCKET
        self._ensure_bucket()

    def _ensure_bucket(self):
        """确保 MinIO bucket 存在"""
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)
                # 设置桶策略为可公开读取
                policy = f'{{"Version":"2012-10-17","Statement":[{{"Effect":"Allow","Principal":{{"AWS":["*"]}},"Action":["s3:GetBucketLocation","s3:ListBucket"],"Resource":["arn:aws:s3:::{self.bucket_name}"]}},{{"Effect":"Allow","Principal":{{"AWS":["*"]}},"Action":["s3:GetObject"],"Resource":["arn:aws:s3:::{self.bucket_name}/*"]}}]}}'
                self.minio_client.set_bucket_policy(self.bucket_name, policy)
                logger.info(f"MinIO 桶 '{self.bucket_name}' 创建成功并设置为了公开只读")
        except Exception as e:
            logger.warning(f"确保 MinIO bucket 存在时发生异常: {e}")

    async def generate_presigned_url_for_upload(self, filename: str) -> Dict[str, str]:
        """
        生成前端直传 MinIO 的预签名 URL (Presigned URL)
        极大释放 FastAPI 网络 I/O，前端拿 URL 后直接 PUT 数据到存储。
        
        Args:
            filename: 文件名
            
        Returns:
            {"upload_url": "...", "object_name": "...", "document_id": "..."}
        """
        try:
            file_extension = Path(filename).suffix
            document_id = str(uuid.uuid4())
            object_name = f"{document_id}{file_extension}"
            
            # 生成 1 小时有效的上传 URL，无需网络请求（纯本地密码学计算）
            upload_url = self.minio_client.presigned_put_object(
                self.bucket_name,
                object_name,
                expires=timedelta(hours=1)
            )
            
            access_url = f"http://{settings.MINIO_URL}/{self.bucket_name}/{object_name}"
            
            return {
                "document_id": document_id,
                "upload_url": upload_url,
                "object_name": object_name,
                "access_url": access_url
            }
        except Exception as e:
            logger.error(f"生成 Presigned URL 失败: {e}", exc_info=True)
            raise

    async def upload_document(
        self,
        file_content: bytes,
        filename: str,
        metadata: DocumentMetadata,
        spatial_metadata: Optional[SpatialMetadata] = None
    ) -> Document:
        """
        [Legacy / Fallback] 服务端直接上传文档（对于小文件保留向后兼容）
        """
        try:
            import io
            
            file_extension = Path(filename).suffix
            document_id = str(uuid.uuid4())
            object_name = f"{document_id}{file_extension}"
            
            file_size = len(file_content)
            
            # 使用 io.BytesIO 转换为流，以便 minio 客户端上传
            data_stream = io.BytesIO(file_content)
            
            self.minio_client.put_object(
                self.bucket_name,
                object_name,
                data_stream,
                length=file_size
            )
            
            import hashlib
            content_hash = hashlib.md5(file_content).hexdigest()

            now = datetime.now()
            document = Document(
                id=document_id,
                filename=filename,
                file_type=file_extension.lstrip(".").lower(),
                file_size=file_size,
                content_hash=content_hash,
                upload_time=now,
                last_modified=now,
                metadata=metadata,
                spatial_metadata=spatial_metadata,
                vector_embedding=None,
                is_indexed=False,
                indexing_status="pending",
                storage_path=object_name,
                access_url=f"http://{settings.MINIO_URL}/{self.bucket_name}/{object_name}",
                version=1
            )

            logger.info(f"服务端 fallback 模式文档上传 MinIO 成功: {document.id}")
            return document

        except Exception as e:
            logger.error(f"服务端文档上传失败: {e}")
            raise

    async def get_document(self, doc_id: str) -> Optional[Document]:
        """
        获取文档

        Args:
            doc_id: 文档ID

        Returns:
            文档对象，如果不存在返回None
        """
        # TODO: 从数据库获取文档
        try:
            # 模拟实现
            return None
        except Exception as e:
            logger.error(f"获取文档失败: {e}")
            return None

    async def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        获取文档列表

        Args:
            page: 页码
            page_size: 每页数量
            filters: 过滤条件

        Returns:
            文档列表
        """
        # TODO: 从数据库查询文档列表
        try:
            documents = []
            return documents
        except Exception as e:
            logger.error(f"获取文档列表失败: {e}")
            return []

    async def update_document(
        self,
        doc_id: str,
        update_request: DocumentUpdateRequest
    ) -> Optional[Document]:
        """
        更新文档

        Args:
            doc_id: 文档ID
            update_request: 更新请求

        Returns:
            更新后的文档对象，如果不存在返回None
        """
        # TODO: 更新文档信息
        try:
            # 模拟实现
            return None
        except Exception as e:
            logger.error(f"更新文档失败: {e}")
            return None

    async def delete_document(self, doc_id: str) -> bool:
        """
        删除文档

        Args:
            doc_id: 文档ID

        Returns:
            是否删除成功
        """
        try:
            # TODO: 从数据库删除文档记录
            # TODO: 删除向量嵌入
            # TODO: 删除物理文件
            logger.info(f"文档删除成功: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return False

    async def reindex_document(self, doc_id: str) -> bool:
        """
        重新索引文档

        Args:
            doc_id: 文档ID

        Returns:
            是否重新索引成功
        """
        try:
            # TODO: 重新提取文本内容
            # TODO: 重新生成向量嵌入
            # TODO: 更新向量数据库
            logger.info(f"文档重新索引成功: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"重新索引失败: {e}")
            return False

    async def get_document_statistics(self) -> Dict[str, Any]:
        """
        获取文档统计信息

        Returns:
            文档统计信息
        """
        # TODO: 从数据库获取统计信息
        try:
            statistics = {
                "total_documents": 0,
                "total_size": 0,
                "indexed_count": 0,
                "failed_count": 0,
                "by_file_type": {},
                "by_category": {},
                "by_date": {}
            }
            return statistics
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    async def search_documents(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10
    ) -> List[Document]:
        """
        搜索文档（基于元数据）

        Args:
            query: 搜索查询
            filters: 过滤条件
            limit: 返回数量

        Returns:
            文档列表
        """
        # TODO: 实现文档搜索逻辑
        try:
            documents = []
            return documents
        except Exception as e:
            logger.error(f"搜索文档失败: {e}")
            return []

    async def export_documents(
        self,
        doc_ids: List[str],
        export_format: str = "json"
    ) -> bytes:
        """
        导出文档

        Args:
            doc_ids: 文档ID列表
            export_format: 导出格式

        Returns:
            导出文件内容
        """
        # TODO: 实现文档导出逻辑
        try:
            import json
            data = {"documents": []}
            if export_format == "json":
                return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            else:
                raise ValueError(f"不支持的导出格式: {export_format}")
        except Exception as e:
            logger.error(f"导出文档失败: {e}")
            raise