"""
文档数据模型
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
import re


class DocumentMetadata(BaseModel):
    """文档元数据"""
    title: str = Field(..., description="文档标题", min_length=1, max_length=500)
    author: Optional[str] = Field(None, description="作者")
    description: Optional[str] = Field(None, description="描述")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    publish_date: Optional[datetime] = Field(None, description="发布日期")
    source: Optional[str] = Field(None, description="来源")
    language: str = Field("zh", description="语言代码")
    category: Optional[str] = Field(None, description="分类")
    tags: List[str] = Field(default_factory=list, description="标签")
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="自定义字段")


class SpatialMetadata(BaseModel):
    """空间元数据"""
    geometry: Optional[Dict[str, Any]] = Field(None, description="空间几何对象（GeoJSON）")
    bounding_box: Optional[List[float]] = Field(None, description="边界框 [min_lon, min_lat, max_lon, max_lat]")
    address: Optional[str] = Field(None, description="地址")
    city: Optional[str] = Field(None, description="城市")
    province: Optional[str] = Field(None, description="省份")
    country: Optional[str] = Field(None, description="国家")
    coordinate_system: str = Field("EPSG:4326", description="坐标系")


class Document(BaseModel):
    """文档模型"""
    id: str = Field(..., description="文档ID")
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）", ge=0)
    content_hash: str = Field(..., description="内容哈希值")
    upload_time: datetime = Field(..., description="上传时间")
    last_modified: datetime = Field(..., description="最后修改时间")
    metadata: DocumentMetadata = Field(..., description="文档元数据")
    spatial_metadata: Optional[SpatialMetadata] = Field(None, description="空间元数据")
    vector_embedding: Optional[List[float]] = Field(None, description="向量嵌入")
    is_indexed: bool = Field(False, description="是否已索引")
    indexing_status: str = Field("pending", description="索引状态: pending, processing, completed, failed")
    storage_path: str = Field(..., description="存储路径")
    access_url: Optional[str] = Field(None, description="访问URL")
    version: int = Field(1, description="版本号")


class UploadRequest(BaseModel):
    """上传请求"""
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    metadata: DocumentMetadata = Field(..., description="文档元数据")
    spatial_metadata: Optional[SpatialMetadata] = Field(None, description="空间元数据")
    chunk_number: Optional[int] = Field(None, description="分块编号（用于大文件分块上传）")
    total_chunks: Optional[int] = Field(None, description="总分块数")

    @validator('file_type')
    def validate_file_type(cls, v):
        """验证文件类型"""
        allowed_types = {
            'pdf', 'docx', 'doc', 'txt', 'md', 'html', 'json', 'xml',
            'csv', 'xlsx', 'xls', 'ppt', 'pptx', 'jpg', 'jpeg', 'png',
            'tiff', 'geojson', 'shp', 'kml', 'kmz'
        }
        if v.lower() not in allowed_types:
            raise ValueError(f"不支持的文件类型: {v}")
        return v.lower()


class DocumentUpdateRequest(BaseModel):
    """文档更新请求"""
    metadata: Optional[DocumentMetadata] = Field(None, description="文档元数据")
    spatial_metadata: Optional[SpatialMetadata] = Field(None, description="空间元数据")
    reindex: bool = Field(False, description="是否重新索引")


class DocumentBatchRequest(BaseModel):
    """文档批量操作请求"""
    document_ids: List[str] = Field(..., description="文档ID列表")
    operation: str = Field(..., description="操作类型: delete, reindex, export")


class DocumentStatistics(BaseModel):
    """文档统计"""
    total_documents: int = Field(0, description="总文档数")
    total_size: int = Field(0, description="总大小（字节）")
    indexed_count: int = Field(0, description="已索引文档数")
    failed_count: int = Field(0, description="索引失败文档数")
    by_file_type: Dict[str, int] = Field(default_factory=dict, description="按文件类型统计")
    by_category: Dict[str, int] = Field(default_factory=dict, description="按分类统计")
    by_date: Dict[str, int] = Field(default_factory=dict, description="按日期统计")


class DocumentExportRequest(BaseModel):
    """文档导出请求"""
    document_ids: List[str] = Field(..., description="导出的文档ID列表")
    export_format: str = Field("json", description="导出格式: json, csv, geojson")
    include_content: bool = Field(False, description="是否包含内容")
    include_vectors: bool = Field(False, description="是否包含向量")
    include_metadata: bool = Field(True, description="是否包含元数据")


class DocumentPreview(BaseModel):
    """文档预览"""
    id: str = Field(..., description="文档ID")
    title: str = Field(..., description="标题")
    file_type: str = Field(..., description="文件类型")
    size: str = Field(..., description="格式化大小")
    upload_time: str = Field(..., description="格式化上传时间")
    indexing_status: str = Field(..., description="索引状态")
    preview_content: Optional[str] = Field(None, description="预览内容")
    thumbnail_url: Optional[str] = Field(None, description="缩略图URL")