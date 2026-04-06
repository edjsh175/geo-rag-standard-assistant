"""
空间数据模型
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
import json


class Point(BaseModel):
    """点几何"""
    type: str = Field("Point", description="几何类型")
    coordinates: List[float] = Field(..., description="坐标 [经度, 纬度]", min_items=2, max_items=3)

    @validator('coordinates')
    def validate_coordinates(cls, v):
        """验证坐标范围"""
        if len(v) >= 2:
            lon, lat = v[0], v[1]
            if not (-180 <= lon <= 180):
                raise ValueError(f"经度 {lon} 超出范围 [-180, 180]")
            if not (-90 <= lat <= 90):
                raise ValueError(f"纬度 {lat} 超出范围 [-90, 90]")
        return v


class LineString(BaseModel):
    """线几何"""
    type: str = Field("LineString", description="几何类型")
    coordinates: List[List[float]] = Field(..., description="坐标列表 [[lon, lat], ...]")


class Polygon(BaseModel):
    """面几何"""
    type: str = Field("Polygon", description="几何类型")
    coordinates: List[List[List[float]]] = Field(..., description="坐标环列表 [[[lon, lat], ...], ...]")


class GeometryCollection(BaseModel):
    """几何集合"""
    type: str = Field("GeometryCollection", description="几何类型")
    geometries: List[Dict[str, Any]] = Field(..., description="几何对象列表")


class Feature(BaseModel):
    """要素"""
    type: str = Field("Feature", description="要素类型")
    geometry: Dict[str, Any] = Field(..., description="几何对象")
    properties: Dict[str, Any] = Field(default_factory=dict, description="属性")


class FeatureCollection(BaseModel):
    """要素集合"""
    type: str = Field("FeatureCollection", description="要素集合类型")
    features: List[Feature] = Field(..., description="要素列表")


class BoundingBox(BaseModel):
    """边界框"""
    min_lon: float = Field(..., description="最小经度", ge=-180, le=180)
    min_lat: float = Field(..., description="最小纬度", ge=-90, le=90)
    max_lon: float = Field(..., description="最大经度", ge=-180, le=180)
    max_lat: float = Field(..., description="最大纬度", ge=-90, le=90)

    def to_list(self) -> List[float]:
        """转换为列表格式 [min_lon, min_lat, max_lon, max_lat]"""
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]


class SpatialQuery(BaseModel):
    """空间查询"""
    geometry: Dict[str, Any] = Field(..., description="查询几何对象（GeoJSON）")
    distance: Optional[float] = Field(None, description="距离（米）", ge=0)
    spatial_relation: str = Field(
        "intersects",
        description="空间关系",
        pattern="^(intersects|within|contains|near|overlaps|disjoint)$"
    )
    buffer_distance: Optional[float] = Field(None, description="缓冲区距离（米）", ge=0)


class GeocodeRequest(BaseModel):
    """地理编码请求"""
    address: str = Field(..., description="地址字符串", min_length=1, max_length=500)
    city: Optional[str] = Field(None, description="城市")
    country: Optional[str] = Field(None, description="国家")


class GeocodeResponse(BaseModel):
    """地理编码响应"""
    address: str = Field(..., description="原始地址")
    coordinates: List[float] = Field(..., description="坐标 [经度, 纬度]")
    formatted_address: str = Field(..., description="格式化地址")
    city: Optional[str] = Field(None, description="城市")
    district: Optional[str] = Field(None, description="区县")
    country: Optional[str] = Field(None, description="国家")
    confidence: float = Field(..., description="置信度", ge=0, le=1)


class ReverseGeocodeRequest(BaseModel):
    """逆地理编码请求"""
    lon: float = Field(..., description="经度", ge=-180, le=180)
    lat: float = Field(..., description="纬度", ge=-90, le=90)


class ReverseGeocodeResponse(BaseModel):
    """逆地理编码响应"""
    coordinates: List[float] = Field(..., description="坐标 [经度, 纬度]")
    address: str = Field(..., description="地址")
    formatted_address: str = Field(..., description="格式化地址")
    city: Optional[str] = Field(None, description="城市")
    district: Optional[str] = Field(None, description="区县")
    country: Optional[str] = Field(None, description="国家")
    distance: Optional[float] = Field(None, description="距离原始点的距离（米）")


class SpatialAnalysisRequest(BaseModel):
    """空间分析请求"""
    geometry1: Dict[str, Any] = Field(..., description="第一个几何对象")
    geometry2: Dict[str, Any] = Field(..., description="第二个几何对象")
    analysis_type: str = Field(
        "intersection",
        description="分析类型",
        pattern="^(intersection|union|difference|distance|buffer)$"
    )
    buffer_distance: Optional[float] = Field(None, description="缓冲区距离（米）", ge=0)


class SpatialAnalysisResponse(BaseModel):
    """空间分析响应"""
    analysis_type: str = Field(..., description="分析类型")
    result_geometry: Optional[Dict[str, Any]] = Field(None, description="结果几何对象")
    distance: Optional[float] = Field(None, description="距离（米）")
    area: Optional[float] = Field(None, description="面积（平方米）")
    is_valid: bool = Field(..., description="分析结果是否有效")