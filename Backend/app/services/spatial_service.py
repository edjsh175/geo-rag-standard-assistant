"""
空间分析服务
"""

import json
import logging
from typing import List, Optional, Dict, Any
import asyncio

from app.core.database import db_manager
from app.models.spatial_models import (
    Point, Polygon, SpatialQuery, GeocodeRequest,
    GeocodeResponse, ReverseGeocodeRequest, ReverseGeocodeResponse
)

logger = logging.getLogger(__name__)


class SpatialService:
    """空间分析服务"""

    def __init__(self):
        pass

    @staticmethod
    def _operand_sql(prefix: str, operand: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        geometry = operand.get("geometry")
        region = operand.get("region")
        if geometry is not None:
            return (
                f"ST_SetSRID(ST_GeomFromGeoJSON(:{prefix}_geometry), 4326)",
                {f"{prefix}_geometry": json.dumps(geometry, ensure_ascii=False)},
            )
        if isinstance(region, dict):
            if region.get("adcode"):
                return (
                    f"(SELECT geometry FROM spatial_regions WHERE adcode = :{prefix}_adcode LIMIT 1)",
                    {f"{prefix}_adcode": str(region["adcode"])},
                )
            if region.get("region_name"):
                return (
                    f"(SELECT geometry FROM spatial_regions WHERE region_name = :{prefix}_region_name LIMIT 1)",
                    {f"{prefix}_region_name": str(region["region_name"])},
                )
        raise ValueError("invalid spatial operand")

    async def query_relation(
        self,
        *,
        left: Dict[str, Any],
        right: Dict[str, Any],
        relation: str,
    ) -> Dict[str, Any]:
        relation_functions = {
            "intersects": "ST_Intersects",
            "within": "ST_Within",
            "contains": "ST_Contains",
            "overlaps": "ST_Overlaps",
            "disjoint": "ST_Disjoint",
            "touches": "ST_Touches",
        }
        function = relation_functions.get(relation)
        if function is None:
            raise ValueError(f"unsupported spatial relation: {relation}")
        left_sql, left_params = self._operand_sql("left", left)
        right_sql, right_params = self._operand_sql("right", right)
        from sqlalchemy import text

        sql = text(
            f"""
            WITH operands AS (
                SELECT {left_sql} AS left_geom, {right_sql} AS right_geom
            )
            SELECT
                left_geom IS NOT NULL AS left_found,
                right_geom IS NOT NULL AS right_found,
                CASE WHEN left_geom IS NULL OR right_geom IS NULL
                    THEN NULL ELSE {function}(left_geom, right_geom) END AS result
            FROM operands
            """
        )
        async with db_manager.get_postgres_session() as session:
            row = (await session.execute(sql, {**left_params, **right_params})).mappings().one()
        if not row["left_found"] or not row["right_found"]:
            raise ValueError("spatial operand was not found")
        return {"operation": "relation", "relation": relation, "result": bool(row["result"])}

    async def overlay(
        self,
        *,
        left: Dict[str, Any],
        right: Dict[str, Any],
        operation: str,
    ) -> Dict[str, Any]:
        overlay_functions = {
            "intersection": "ST_Intersection",
            "union": "ST_Union",
            "difference": "ST_Difference",
        }
        function = overlay_functions.get(operation)
        if function is None:
            raise ValueError(f"unsupported spatial overlay: {operation}")
        left_sql, left_params = self._operand_sql("left", left)
        right_sql, right_params = self._operand_sql("right", right)
        from sqlalchemy import text

        sql = text(
            f"""
            WITH operands AS (
                SELECT {left_sql} AS left_geom, {right_sql} AS right_geom
            ), result AS (
                SELECT left_geom, right_geom,
                    CASE WHEN left_geom IS NULL OR right_geom IS NULL
                        THEN NULL ELSE {function}(left_geom, right_geom) END AS result_geom
                FROM operands
            )
            SELECT
                left_geom IS NOT NULL AS left_found,
                right_geom IS NOT NULL AS right_found,
                CASE WHEN result_geom IS NULL THEN NULL ELSE ST_AsGeoJSON(result_geom)::json END AS geometry,
                CASE WHEN result_geom IS NULL OR ST_IsEmpty(result_geom) THEN 0
                    ELSE ST_Area(result_geom::geography) END AS area_m2
            FROM result
            """
        )
        async with db_manager.get_postgres_session() as session:
            row = (await session.execute(sql, {**left_params, **right_params})).mappings().one()
        if not row["left_found"] or not row["right_found"]:
            raise ValueError("spatial operand was not found")
        return {
            "operation": operation,
            "geometry": row["geometry"],
            "area_m2": float(row["area_m2"] or 0),
        }

    async def geocode(self, request: GeocodeRequest) -> GeocodeResponse:
        """
        地理编码（地址转坐标）

        Args:
            request: 地理编码请求

        Returns:
            地理编码响应
        """
        # TODO: 实现地理编码逻辑
        # 可以使用第三方API如百度地图、高德地图、腾讯地图等
        try:
            # 模拟实现
            coordinates = [116.4074, 39.9042]  # 北京坐标示例

            return GeocodeResponse(
                address=request.address,
                coordinates=coordinates,
                formatted_address=f"{request.address} (模拟)",
                city=request.city or "北京市",
                district="海淀区",
                country="中国",
                confidence=0.8
            )
        except Exception as e:
            logger.error(f"地理编码失败: {e}")
            raise

    async def reverse_geocode(self, request: ReverseGeocodeRequest) -> ReverseGeocodeResponse:
        """
        逆地理编码（坐标转地址）

        Args:
            request: 逆地理编码请求

        Returns:
            逆地理编码响应
        """
        # TODO: 实现逆地理编码逻辑
        try:
            return ReverseGeocodeResponse(
                coordinates=[request.lon, request.lat],
                address=f"坐标 ({request.lon}, {request.lat})",
                formatted_address=f"经度: {request.lon}, 纬度: {request.lat} (模拟)",
                city="北京市",
                district="海淀区",
                country="中国",
                distance=0.0
            )
        except Exception as e:
            logger.error(f"逆地理编码失败: {e}")
            raise

    async def spatial_query(self, query: SpatialQuery) -> List[Dict[str, Any]]:
        """
        空间查询

        Args:
            query: 空间查询参数

        Returns:
            空间查询结果
        """
        # TODO: 实现空间查询逻辑
        # 使用PostGIS进行空间查询
        try:
            results = []
            return results
        except Exception as e:
            logger.error(f"空间查询失败: {e}")
            raise

    async def calculate_distance(
        self,
        point1: List[float],
        point2: List[float]
    ) -> float:
        """
        计算两点间距离（米）

        Args:
            point1: 第一个点 [经度, 纬度]
            point2: 第二个点 [经度, 纬度]

        Returns:
            距离（米）
        """
        try:
            from math import radians, sin, cos, sqrt, atan2

            R = 6371000  # 地球半径（米）

            lat1_rad = radians(point1[1])
            lon1_rad = radians(point1[0])
            lat2_rad = radians(point2[1])
            lon2_rad = radians(point2[0])

            dlon = lon2_rad - lon1_rad
            dlat = lat2_rad - lat1_rad

            a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))

            distance = R * c
            return distance

        except Exception as e:
            logger.error(f"计算距离失败: {e}")
            raise

    async def create_buffer(
        self,
        center: List[float],
        distance: float
    ) -> Dict[str, Any]:
        """
        创建缓冲区

        Args:
            center: 中心点 [经度, 纬度]
            distance: 缓冲距离（米）

        Returns:
            缓冲区几何对象（GeoJSON）
        """
        # TODO: 实现缓冲区创建逻辑
        try:
            buffer_geometry = {
                "type": "Polygon",
                "coordinates": [[
                    [center[0] - 0.01, center[1] - 0.01],
                    [center[0] + 0.01, center[1] - 0.01],
                    [center[0] + 0.01, center[1] + 0.01],
                    [center[0] - 0.01, center[1] + 0.01],
                    [center[0] - 0.01, center[1] - 0.01]
                ]]
            }
            return buffer_geometry
        except Exception as e:
            logger.error(f"创建缓冲区失败: {e}")
            raise

    async def spatial_analysis(
        self,
        geometry1: Dict[str, Any],
        geometry2: Dict[str, Any],
        analysis_type: str = "intersection"
    ) -> Dict[str, Any]:
        """
        空间分析

        Args:
            geometry1: 第一个几何对象
            geometry2: 第二个几何对象
            analysis_type: 分析类型

        Returns:
            空间分析结果
        """
        # TODO: 实现空间分析逻辑
        try:
            result = {
                "analysis_type": analysis_type,
                "is_valid": True,
                "result_geometry": None,
                "distance": None,
                "area": None
            }
            return result
        except Exception as e:
            logger.error(f"空间分析失败: {e}")
            raise

    async def get_provinces(self, simplify_tolerance: float = 0.001) -> Dict[str, Any]:
        """
        获取所有省级行政区划数据（GeoJSON FeatureCollection格式）

        使用PostGIS的ST_AsGeoJSON和ST_Simplify函数查询spatial_regions表
        返回符合GeoJSON标准的FeatureCollection，前端可直接解析

        Args:
            simplify_tolerance: 几何简化容差（度），0表示不简化

        Returns:
            GeoJSON FeatureCollection字典
        """
        try:
            async with db_manager.get_postgres_session() as session:
                # 构建SQL查询
                # 使用json_build_object和json_agg直接构建FeatureCollection
                sql = """
                    SELECT json_build_object(
                        'type', 'FeatureCollection',
                        'features', COALESCE(json_agg(feature), '[]'::json)
                    ) AS feature_collection
                    FROM (
                        SELECT json_build_object(
                            'type', 'Feature',
                            'id', id,
                            'properties', json_build_object(
                                'adcode', adcode,
                                'region_name', region_name
                            ),
                            'geometry', CASE
                                WHEN :simplify > 0 THEN ST_AsGeoJSON(ST_Simplify(geometry, :simplify))::json
                                ELSE ST_AsGeoJSON(geometry)::json
                            END
                        ) AS feature
                        FROM spatial_regions
                        WHERE geometry IS NOT NULL
                        ORDER BY adcode
                    ) AS features
                """

                from sqlalchemy import text
                result = await session.execute(text(sql), {"simplify": simplify_tolerance})
                row = result.fetchone()

                if row is None or row[0] is None:
                    logger.warning("未找到行政区划数据，返回空FeatureCollection")
                    return {
                        "type": "FeatureCollection",
                        "features": []
                    }

                feature_collection = row[0]
                # 确保features字段存在（即使为空）
                if "features" not in feature_collection:
                    feature_collection["features"] = []

                logger.info(f"成功获取 {len(feature_collection.get('features', []))} 个行政区划要素")
                return feature_collection

        except Exception as e:
            logger.error(f"获取行政区划数据失败: {e}")
            # 返回空FeatureCollection而不是抛出异常，确保前端不会崩溃
            return {
                "type": "FeatureCollection",
                "features": []
            }
