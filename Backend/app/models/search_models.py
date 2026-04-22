"""
智能检索数据模型
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class SpatialFilter(BaseModel):
    """空间过滤器"""
    geometry: Optional[Dict[str, Any]] = None  # GeoJSON 几何对象
    distance: Optional[float] = Field(None, description="距离（米）")
    spatial_relation: str = Field("within", description="空间关系: within, intersects, near")


class MetadataFilter(BaseModel):
    """元数据过滤器"""
    document_type: Optional[str] = None
    source: Optional[str] = None
    year: Optional[int] = None
    region: Optional[str] = None
    keywords: Optional[List[str]] = None
    custom_filters: Optional[Dict[str, Any]] = None


class DocumentResult(BaseModel):
    """文档检索结果"""
    id: str = Field(..., description="文档ID")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容摘要")
    similarity: float = Field(..., description="相似度分数", ge=0, le=1)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="文档元数据")
    spatial_info: Optional[Dict[str, Any]] = Field(None, description="空间信息")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., description="文件大小（字节）")
    upload_time: datetime = Field(..., description="上传时间")
    source_url: Optional[str] = Field(None, description="源URL")

    # 字段验证器：自动将 int 类型的 id 转换为 str
    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v) -> str:
        """将 id 字段自动转换为字符串类型"""
        return str(v)


class SearchRequest(BaseModel):
    """检索请求"""
    query: str = Field(..., description="检索查询语句", min_length=1, max_length=1000)
    top_k: int = Field(10, description="返回结果数量", ge=1, le=100)
    threshold: float = Field(0.7, description="相似度阈值", ge=0, le=1)
    spatial_filter: Optional[SpatialFilter] = Field(None, description="空间过滤器")
    metadata_filter: Optional[MetadataFilter] = Field(None, description="元数据过滤器")
    use_rerank: bool = Field(True, description="是否使用重排序")
    search_mode: str = Field("hybrid", description="检索模式: semantic, keyword, hybrid")
    use_generation: bool = Field(False, description="是否使用大模型生成答案")
    stream: bool = Field(False, description="是否使用流式传输(SSE)返回答案")
    history: Optional[List[Dict[str, str]]] = Field([], description="历史对话记录")


class SearchResponse(BaseModel):
    """检索响应"""
    query: str = Field(..., description="原始查询")
    results: List[DocumentResult] = Field(default_factory=list, description="检索结果")
    total_count: int = Field(0, description="总结果数量")
    search_time: float = Field(0.0, description="检索耗时（秒）")
    search_mode: str = Field("hybrid", description="使用的检索模式")
    suggestions: Optional[List[str]] = Field(None, description="搜索建议")
    generated_answer: Optional[str] = Field(None, description="大模型生成的答案")
    generation_time: Optional[float] = Field(None, description="生成耗时（秒）")


class SearchHistory(BaseModel):
    """搜索历史记录"""
    id: str = Field(..., description="记录ID")
    query: str = Field(..., description="查询语句")
    results_count: int = Field(..., description="结果数量")
    search_time: datetime = Field(..., description="搜索时间")
    user_id: Optional[str] = Field(None, description="用户ID")
    session_id: Optional[str] = Field(None, description="会话ID")


class SearchStatistic(BaseModel):
    """搜索统计"""
    total_searches: int = Field(0, description="总搜索次数")
    average_results: float = Field(0.0, description="平均结果数量")
    popular_queries: List[Dict[str, Any]] = Field(default_factory=list, description="热门查询")
    search_trends: Dict[str, int] = Field(default_factory=dict, description="搜索趋势")


class FeedbackRequest(BaseModel):
    """搜索反馈请求"""
    query: str = Field(..., description="查询语句")
    result_id: str = Field(..., description="结果ID")
    feedback_type: str = Field(..., description="反馈类型: relevant, irrelevant, helpful, not_helpful")
    comment: Optional[str] = Field(None, description="反馈评论")
    rating: Optional[int] = Field(None, description="评分（1-5）", ge=1, le=5)