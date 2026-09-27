"""
空间分析 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional
from pydantic import BaseModel

from app.core.security import require_authenticated_user

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


class SpatialQuery(BaseModel):
    """空间查询请求"""
    geometry: dict  # GeoJSON 几何对象
    distance: Optional[float] = 1000  # 距离（米）
    spatial_relation: str = "within"  # 空间关系: within, intersects, near


class SpatialResult(BaseModel):
    """空间查询结果"""
    id: str
    title: str
    geometry: dict  # GeoJSON 几何对象
    distance: Optional[float] = None


def _not_implemented(capability: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{capability} is not implemented by an authoritative spatial provider",
    )


@router.post("/query")
async def spatial_query(
    query: SpatialQuery
):
    """
    空间查询

    Args:
        query: 空间查询参数

    Returns:
        空间查询结果
    """
    _not_implemented("spatial query")


@router.post("/geocode")
async def geocode_address(
    address: str = Query(..., description="地址字符串"),
    city: Optional[str] = Query(None, description="城市")
):
    """
    地理编码（地址转坐标）

    Args:
        address: 地址
        city: 城市

    Returns:
        地理编码结果
    """
    _not_implemented("geocoding")


@router.post("/reverse-geocode")
async def reverse_geocode(
    lon: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度")
):
    """
    逆地理编码（坐标转地址）

    Args:
        lon: 经度
        lat: 纬度

    Returns:
        逆地理编码结果
    """
    _not_implemented("reverse geocoding")


@router.get("/buffer")
async def create_buffer(
    lon: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    distance: float = Query(1000, description="缓冲距离（米）")
):
    """
    创建缓冲区

    Args:
        lon: 经度
        lat: 纬度
        distance: 缓冲距离（米）

    Returns:
        缓冲区几何对象（GeoJSON）
    """
    _not_implemented("buffer analysis")


@router.post("/intersection")
async def calculate_intersection(
    geometry1: dict,
    geometry2: dict
):
    """
    计算几何对象交集

    Args:
        geometry1: 第一个几何对象（GeoJSON）
        geometry2: 第二个几何对象（GeoJSON）

    Returns:
        交集几何对象（GeoJSON）
    """
    _not_implemented("geometry intersection")


@router.get("/distance")
async def calculate_distance(
    lon1: float = Query(..., description="第一个点经度"),
    lat1: float = Query(..., description="第一个点纬度"),
    lon2: float = Query(..., description="第二个点经度"),
    lat2: float = Query(..., description="第二个点纬度")
):
    """
    计算两点间距离

    Args:
        lon1, lat1: 第一个点坐标
        lon2, lat2: 第二个点坐标

    Returns:
        距离（米）
    """
    try:
        # 使用 Haversine 公式计算大圆距离
        from math import radians, sin, cos, sqrt, atan2

        R = 6371000  # 地球半径（米）

        lat1_rad = radians(lat1)
        lon1_rad = radians(lon1)
        lat2_rad = radians(lat2)
        lon2_rad = radians(lon2)

        dlon = lon2_rad - lon1_rad
        dlat = lat2_rad - lat1_rad

        a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))

        distance = R * c

        return {
            "point1": [lon1, lat1],
            "point2": [lon2, lat2],
            "distance_meters": round(distance, 2),
            "distance_kilometers": round(distance / 1000, 3)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算距离失败: {str(e)}")


@router.get("/provinces-test")
async def get_provinces_test():
    """
    测试端点：验证路由注册
    """
    return {"message": "Provinces test endpoint works"}


@router.get("/provinces")
async def get_provinces(
    simplify: Optional[float] = Query(0.001, description="几何简化容差（度），0表示不简化")
):
    """
    获取所有省级行政区划数据（GeoJSON FeatureCollection格式）

    使用PostGIS的ST_AsGeoJSON和ST_Simplify函数查询spatial_regions表
    返回符合GeoJSON标准的FeatureCollection，前端可直接解析

    Args:
        simplify: 简化容差，单位为度（经纬度）。例如0.001约等于100米。默认0.001以提升前端性能。

    Returns:
        GeoJSON FeatureCollection
    """
    try:
        # 局部导入 SpatialService 以避免可能的循环导入问题
        from app.services.spatial_service import SpatialService

        service = SpatialService()
        result = await service.get_provinces(simplify_tolerance=simplify)
        return result
    except Exception as e:
        err_msg = str(e).lower()
        if any(term in err_msg for term in ["connection", "operationalerror", "timeout", "refused", "unavailable"]):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"空间数据库不可用: {str(e)}",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取行政区划数据失败: {str(e)}",
        )
