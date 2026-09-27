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


ALLOWED_GEOMETRY_TYPES = frozenset(
    {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }
)

MAX_GEOJSON_PAYLOAD_BYTES = 262144  # 256 KB


def _validate_coord(coord: Any) -> None:
    if not isinstance(coord, (list, tuple)):
        raise ValueError(f"coordinate must be a list or tuple, got {type(coord).__name__}")
    if len(coord) < 2 or len(coord) > 3:
        raise ValueError(f"coordinate must have 2 or 3 elements [lon, lat, (elev)], got {len(coord)}")
    lon, lat = coord[0], coord[1]
    if isinstance(lon, bool) or isinstance(lat, bool) or not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        raise ValueError("coordinate values must be numeric")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"longitude {lon} out of range [-180, 180]")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"latitude {lat} out of range [-90, 90]")


def validate_geojson_geometry(geometry: Any, _depth: int = 0) -> None:
    """严格校验 GeoJSON 几何体对象的领域契约。

    检验项包括：
    - 字典结构与最大负载大小 (256 KB)
    - 允许的几何类型 (RFC 7946)
    - 递归深度限制 (<= 3)
    - 坐标合法经纬度范围 (lon [-180, 180], lat [-90, 90])
    - 非空坐标
    - 多边形线性环最小点数 (>= 4) 与首尾坐标严格闭合
    - CRS 声明（如存在则仅支持 WGS84 / EPSG:4326）
    """
    if _depth > 3:
        raise ValueError("GeoJSON nesting depth exceeded maximum (3)")
    if not isinstance(geometry, dict):
        raise ValueError(f"GeoJSON geometry must be a dictionary, got {type(geometry).__name__}")

    raw_json = json.dumps(geometry, ensure_ascii=False)
    if len(raw_json.encode("utf-8")) > MAX_GEOJSON_PAYLOAD_BYTES:
        raise ValueError(f"GeoJSON payload exceeds maximum allowed size ({MAX_GEOJSON_PAYLOAD_BYTES} bytes)")

    geom_type = geometry.get("type")
    if not isinstance(geom_type, str) or geom_type not in ALLOWED_GEOMETRY_TYPES:
        raise ValueError(
            f"unsupported or missing GeoJSON geometry type: {geom_type!r}. "
            f"Allowed types: {sorted(ALLOWED_GEOMETRY_TYPES)}"
        )

    crs = geometry.get("crs")
    if crs is not None:
        if isinstance(crs, dict):
            props = crs.get("properties", {})
            name = props.get("name", "") if isinstance(props, dict) else ""
            if name and name.upper() not in {
                "EPSG:4326",
                "URN:OGC:DEF:CRS:OGC:1.3:CRS84",
                "URN:OGC:DEF:CRS:EPSG::4326",
                "CRS84",
            }:
                raise ValueError(f"unsupported CRS: {name!r}. Expected WGS84 (EPSG:4326 / CRS84)")
        else:
            raise ValueError("CRS must be a dictionary")

    if geom_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list) or len(geometries) == 0:
            raise ValueError("GeometryCollection must have a non-empty 'geometries' list")
        for g in geometries:
            validate_geojson_geometry(g, _depth=_depth + 1)
        return

    coords = geometry.get("coordinates")
    if coords is None:
        raise ValueError(f"GeoJSON {geom_type} missing 'coordinates' field")
    if not isinstance(coords, list) or len(coords) == 0:
        raise ValueError(f"GeoJSON {geom_type} coordinates cannot be empty")

    if geom_type == "Point":
        _validate_coord(coords)

    elif geom_type == "MultiPoint":
        for pt in coords:
            _validate_coord(pt)

    elif geom_type == "LineString":
        if len(coords) < 2:
            raise ValueError(f"LineString must contain at least 2 points, got {len(coords)}")
        for pt in coords:
            _validate_coord(pt)

    elif geom_type == "MultiLineString":
        for line in coords:
            if not isinstance(line, list) or len(line) < 2:
                raise ValueError("each line in MultiLineString must contain at least 2 points")
            for pt in line:
                _validate_coord(pt)

    elif geom_type == "Polygon":
        for ring_idx, ring in enumerate(coords):
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError(
                    f"Polygon ring {ring_idx} must contain at least 4 coordinates, got {len(ring) if isinstance(ring, list) else 0}"
                )
            for pt in ring:
                _validate_coord(pt)
            if ring[0][0] != ring[-1][0] or ring[0][1] != ring[-1][1]:
                raise ValueError(
                    f"Polygon ring {ring_idx} is not closed: first coordinate {ring[0]} != last coordinate {ring[-1]}"
                )

    elif geom_type == "MultiPolygon":
        for poly_idx, poly in enumerate(coords):
            if not isinstance(poly, list) or len(poly) == 0:
                raise ValueError(f"MultiPolygon polygon {poly_idx} must be a non-empty list of rings")
            for ring_idx, ring in enumerate(poly):
                if not isinstance(ring, list) or len(ring) < 4:
                    raise ValueError(
                        f"MultiPolygon polygon {poly_idx} ring {ring_idx} must contain at least 4 coordinates, got {len(ring) if isinstance(ring, list) else 0}"
                    )
                for pt in ring:
                    _validate_coord(pt)
                if ring[0][0] != ring[-1][0] or ring[0][1] != ring[-1][1]:
                    raise ValueError(
                        f"MultiPolygon polygon {poly_idx} ring {ring_idx} is not closed: first coordinate {ring[0]} != last coordinate {ring[-1]}"
                    )


class SpatialService:
    """空间分析服务"""

    def __init__(self):
        pass

    @staticmethod
    def _operand_sql(prefix: str, operand: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        geometry = operand.get("geometry")
        region = operand.get("region")
        if geometry is not None:
            validate_geojson_geometry(geometry)
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
                CASE WHEN result_geom IS NULL THEN NULL ELSE ST_GeometryType(result_geom) END AS geom_type,
                CASE WHEN result_geom IS NULL OR ST_IsEmpty(result_geom) THEN 0
                    ELSE ST_NPoints(result_geom) END AS n_points,
                CASE WHEN result_geom IS NULL OR ST_IsEmpty(result_geom) THEN 0
                    ELSE ST_Area(result_geom::geography) END AS area_m2,
                CASE WHEN result_geom IS NULL THEN NULL
                    ELSE json_build_array(ST_XMin(result_geom), ST_YMin(result_geom), ST_XMax(result_geom), ST_YMax(result_geom))
                END AS bbox,
                CASE
                    WHEN result_geom IS NULL THEN NULL
                    WHEN ST_NPoints(result_geom) > 100 THEN ST_AsGeoJSON(ST_SimplifyPreserveTopology(result_geom, 0.001))::json
                    ELSE ST_AsGeoJSON(result_geom)::json
                END AS geometry
            FROM result
            """
        )
        async with db_manager.get_postgres_session() as session:
            row = (await session.execute(sql, {**left_params, **right_params})).mappings().one()
        if not row["left_found"] or not row["right_found"]:
            raise ValueError("spatial operand was not found")

        n_points = int(row.get("n_points") or 0)
        geom = row.get("geometry")
        geom_type = row.get("geom_type")
        bbox = row.get("bbox")
        area_m2 = float(row.get("area_m2") or 0)

        geometry_truncated = False
        if geom is not None:
            geom_str = json.dumps(geom) if not isinstance(geom, str) else geom
            if len(geom_str) > 8192:
                geom = None
                geometry_truncated = True

        return {
            "operation": operation,
            "geometry_type": geom_type,
            "area_m2": area_m2,
            "bbox": bbox,
            "point_count": n_points,
            "is_simplified": n_points > 100,
            "geometry_truncated": geometry_truncated,
            "geometry": geom,
        }

    async def geocode(self, request: GeocodeRequest) -> GeocodeResponse:
        """地理编码（地址转坐标）"""
        raise NotImplementedError("Authoritative geocoding provider is not configured")

    async def reverse_geocode(self, request: ReverseGeocodeRequest) -> ReverseGeocodeResponse:
        """逆地理编码（坐标转地址）"""
        raise NotImplementedError("Authoritative reverse geocoding provider is not configured")

    async def spatial_query(self, query: SpatialQuery) -> List[Dict[str, Any]]:
        """空间查询"""
        raise NotImplementedError("Authoritative spatial query provider is not implemented; use query_relation or overlay")

    async def calculate_distance(
        self,
        point1: List[float],
        point2: List[float],
    ) -> float:
        """
        计算两点间球面距离（米）

        Args:
            point1: 第一个点 [经度, 纬度]
            point2: 第二个点 [经度, 纬度]

        Returns:
            距离（米）
        """
        try:
            from math import atan2, cos, radians, sin, sqrt

            R = 6371000  # 地球半径（米）

            lat1_rad = radians(point1[1])
            lon1_rad = radians(point1[0])
            lat2_rad = radians(point2[1])
            lon2_rad = radians(point2[0])

            dlon = lon2_rad - lon1_rad
            dlat = lat2_rad - lat1_rad

            a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))

            distance = R * c
            return distance

        except Exception as e:
            logger.error(f"计算距离失败: {e}")
            raise

    async def create_buffer(
        self,
        center: List[float],
        distance: float,
    ) -> Dict[str, Any]:
        """基于 PostGIS 真实地理坐标系 (geography) 计算米级缓冲区。"""
        if len(center) < 2:
            raise ValueError("center must contain [lon, lat]")
        lon, lat = float(center[0]), float(center[1])
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError(f"center coordinates out of bounds: [{lon}, {lat}]")
        if distance <= 0:
            raise ValueError("buffer distance must be positive")
        from sqlalchemy import text

        sql = text(
            """
            SELECT ST_AsGeoJSON(
                ST_Buffer(ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography, :distance)::geometry
            )::json AS geometry
            """
        )
        async with db_manager.get_postgres_session() as session:
            row = (await session.execute(sql, {"lon": lon, "lat": lat, "distance": distance})).mappings().one()
        geom = row.get("geometry")
        if geom is None:
            raise RuntimeError("failed to generate buffer geometry")
        return geom

    async def spatial_analysis(
        self,
        geometry1: Dict[str, Any],
        geometry2: Dict[str, Any],
        analysis_type: str = "intersection",
    ) -> Dict[str, Any]:
        """空间分析（已收敛至 query_relation 与 overlay）"""
        raise NotImplementedError("Authoritative spatial_analysis is not implemented; use query_relation or overlay")

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
                if "features" not in feature_collection:
                    feature_collection["features"] = []

                logger.info(f"成功获取 {len(feature_collection.get('features', []))} 个行政区划要素")
                return feature_collection

        except Exception as e:
            logger.error(f"获取行政区划数据失败: {e}")
            raise RuntimeError(f"获取行政区划数据失败: {e}") from e
