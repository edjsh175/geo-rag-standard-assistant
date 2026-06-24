"""Metadata and spatial filters for RAG search results."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text

from app.core.database import db_manager
from app.models.search_models import DocumentResult, MetadataFilter, SpatialFilter

logger = logging.getLogger(__name__)

REGION_STANDARD_PREFIXES = {
    "北京市": "DB11",
    "天津市": "DB12",
    "河北省": "DB13",
    "山西省": "DB14",
    "内蒙古自治区": "DB15",
    "辽宁省": "DB21",
    "吉林省": "DB22",
    "黑龙江省": "DB23",
    "上海市": "DB31",
    "江苏省": "DB32",
    "浙江省": "DB33",
    "安徽省": "DB34",
    "福建省": "DB35",
    "江西省": "DB36",
    "山东省": "DB37",
    "河南省": "DB41",
    "湖北省": "DB42",
    "湖南省": "DB43",
    "广东省": "DB44",
    "广西壮族自治区": "DB45",
    "海南省": "DB46",
    "重庆市": "DB50",
    "四川省": "DB51",
    "贵州省": "DB52",
    "云南省": "DB53",
    "西藏自治区": "DB54",
    "陕西省": "DB61",
    "甘肃省": "DB62",
    "青海省": "DB63",
    "宁夏回族自治区": "DB64",
    "新疆维吾尔自治区": "DB65",
}

ADCODE_PREFIXES = {prefix.removeprefix("DB"): prefix for prefix in REGION_STANDARD_PREFIXES.values()}

ALLOWED_CUSTOM_FILTER_KEYS = {
    "category",
    "charge_unit",
    "chinese_name",
    "city",
    "document_name",
    "document_type",
    "draft_unit",
    "english_name",
    "file_type",
    "implement_date",
    "keyword",
    "keywords",
    "province",
    "region",
    "release_date",
    "release_unit",
    "source",
    "standard_code",
    "standard_status",
    "type",
    "year",
}


class RagFilterEngine:
    """Apply metadata and spatial constraints without exposing arbitrary SQL."""

    def apply_metadata_filter(
        self,
        results: list[DocumentResult],
        metadata_filter: MetadataFilter,
    ) -> list[DocumentResult]:
        filtered_results: list[DocumentResult] = []
        for result in results:
            metadata = {
                **result.metadata,
                "file_type": result.file_type,
                "_content": result.content,
                "_title": result.title,
            }
            if self.matches_metadata_filter(metadata, metadata_filter):
                result.metadata["metadata_filter_match"] = True
                filtered_results.append(result)
        return filtered_results

    def matches_metadata_filter(
        self,
        metadata: dict[str, Any],
        filter_: MetadataFilter,
    ) -> bool:
        if filter_.document_type and not self._field_matches(
            metadata,
            ("document_type", "file_type", "category", "type"),
            filter_.document_type,
        ):
            return False

        if filter_.source and not self._field_matches(
            metadata,
            ("source", "release_unit", "charge_unit", "draft_unit"),
            filter_.source,
        ):
            return False

        if filter_.year is not None and not self._year_matches(metadata, filter_.year):
            return False

        if filter_.region and not self._region_matches(metadata, filter_.region):
            return False

        if filter_.keywords and not self._keywords_match(metadata, filter_.keywords):
            return False

        for key, expected in (filter_.custom_filters or {}).items():
            if key not in ALLOWED_CUSTOM_FILTER_KEYS:
                logger.warning("Ignoring unsafe custom metadata filter key: %s", key)
                return False
            if not self._field_matches(metadata, (key,), expected):
                return False

        return True

    async def apply_spatial_filter(
        self,
        results: list[DocumentResult],
        spatial_filter: SpatialFilter,
    ) -> list[DocumentResult]:
        query_geometry = self._coerce_geometry(spatial_filter.geometry)
        if query_geometry is None:
            logger.warning("Invalid spatial filter geometry; returning no results")
            return []

        geometry_candidates: list[DocumentResult] = []
        geometry_matches: list[DocumentResult] = []
        for result in results:
            result_geometry = self._result_geometry(result)
            if result_geometry is None:
                continue
            geometry_candidates.append(result)
            if self._matches_spatial_relation(result_geometry, query_geometry, spatial_filter):
                result.metadata["spatial_filter_match"] = True
                result.metadata["spatial_filter_source"] = "document_geometry"
                geometry_matches.append(result)

        if geometry_candidates:
            return geometry_matches

        region_prefixes = await self.get_region_prefixes_for_geometry(spatial_filter)
        if not region_prefixes:
            return []

        prefix_matches: list[DocumentResult] = []
        for result in results:
            standard_code = self._normalize_standard_code(
                str(result.metadata.get("standard_code", ""))
            )
            if any(standard_code.startswith(prefix.lower()) for prefix in region_prefixes):
                result.metadata["spatial_filter_match"] = True
                result.metadata["spatial_filter_source"] = "region_prefix"
                prefix_matches.append(result)
        return prefix_matches

    async def get_region_prefixes_for_geometry(self, spatial_filter: SpatialFilter) -> set[str]:
        if not db_manager.postgres_sessionmaker or not spatial_filter.geometry:
            return set()

        try:
            geometry_json = json.dumps(spatial_filter.geometry, ensure_ascii=False)
            relation = (spatial_filter.spatial_relation or "intersects").lower()
            distance = spatial_filter.distance or 0
            if relation == "near":
                predicate = """
                    ST_DWithin(
                        geometry::geography,
                        ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)::geography,
                        :distance
                    )
                """
            elif relation == "within":
                predicate = "ST_Within(geometry, ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))"
            elif relation == "contains":
                predicate = "ST_Contains(geometry, ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))"
            else:
                predicate = "ST_Intersects(geometry, ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))"

            sql = text(
                f"""
                SELECT adcode, region_name
                FROM spatial_regions
                WHERE geometry IS NOT NULL
                  AND {predicate}
                """
            )
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(
                    sql,
                    {"geometry": geometry_json, "distance": distance},
                )
                rows = result.mappings().all()
        except Exception as exc:
            logger.warning("Spatial region lookup failed: %s", exc)
            return set()

        prefixes: set[str] = set()
        for row in rows:
            prefixes.update(self.get_region_prefixes_for_text(str(row.get("region_name") or "")))
            prefixes.update(self.get_region_prefixes_for_text(str(row.get("adcode") or "")))
        return prefixes

    async def spatial_search(self, spatial_query: str, top_k: int) -> list[DocumentResult]:
        prefixes = self.get_region_prefixes_for_text(spatial_query)
        if not prefixes:
            prefixes = await self._lookup_region_prefixes_by_text(spatial_query)
        if not prefixes or not db_manager.postgres_sessionmaker:
            return []

        conditions = []
        params: dict[str, Any] = {"limit": top_k}
        for index, prefix in enumerate(sorted(prefixes)):
            name = f"prefix_{index}"
            params[name] = f"{prefix}%"
            conditions.append(f"standard_code ILIKE :{name}")

        sql = text(
            f"""
            SELECT id, standard_code, document_name, content
            FROM policy_chunks
            WHERE {" OR ".join(conditions)}
            ORDER BY document_name, id
            LIMIT :limit
            """
        )
        try:
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
        except Exception as exc:
            logger.warning("Spatial search failed: %s", exc)
            return []

        from datetime import datetime

        return [
            DocumentResult(
                id=row.id,
                title=row.document_name,
                content=row.content[:500] if row.content else "",
                similarity=0.7,
                metadata={
                    "standard_code": row.standard_code,
                    "document_name": row.document_name,
                    "match_type": "spatial_region",
                    "spatial_filter_match": True,
                    "spatial_filter_source": "region_prefix",
                },
                spatial_info=None,
                file_type="unknown",
                file_size=0,
                upload_time=datetime.now(),
                source_url=None,
            )
            for row in rows
        ]

    def get_region_prefixes_for_text(self, value: str) -> set[str]:
        compact = self._normalize_text(value)
        if not compact:
            return set()

        prefixes: set[str] = set()
        if compact[:2].isdigit() and compact[:2] in ADCODE_PREFIXES:
            prefixes.add(ADCODE_PREFIXES[compact[:2]])

        for region_name, prefix in REGION_STANDARD_PREFIXES.items():
            aliases = self._region_aliases(region_name)
            if any(alias and alias in compact for alias in aliases):
                prefixes.add(prefix)
        return prefixes

    async def _lookup_region_prefixes_by_text(self, spatial_query: str) -> set[str]:
        if not db_manager.postgres_sessionmaker:
            return set()
        try:
            sql = text(
                """
                SELECT adcode, region_name
                FROM spatial_regions
                WHERE adcode ILIKE :query
                   OR region_name ILIKE :query
                LIMIT 10
                """
            )
            async with db_manager.get_postgres_session() as session:
                result = await session.execute(sql, {"query": f"%{spatial_query}%"})
                rows = result.mappings().all()
        except Exception as exc:
            logger.warning("Spatial text lookup failed: %s", exc)
            return set()

        prefixes: set[str] = set()
        for row in rows:
            prefixes.update(self.get_region_prefixes_for_text(str(row.get("region_name") or "")))
            prefixes.update(self.get_region_prefixes_for_text(str(row.get("adcode") or "")))
        return prefixes

    def _field_matches(
        self,
        metadata: dict[str, Any],
        keys: Iterable[str],
        expected: Any,
    ) -> bool:
        expected_values = self._as_values(expected)
        actual_values: list[str] = []
        for key in keys:
            actual_values.extend(self._as_values(metadata.get(key)))
        if not expected_values:
            return True
        if not actual_values:
            return False
        return any(
            expected_value in actual_value
            for expected_value in expected_values
            for actual_value in actual_values
        )

    def _year_matches(self, metadata: dict[str, Any], expected_year: int) -> bool:
        year_text = str(expected_year)
        for key in ("year", "release_date", "implement_date", "publish_date"):
            value = metadata.get(key)
            if value is None:
                continue
            years = re.findall(r"\d{4}", str(value))
            if year_text in years or self._normalize_text(str(value)) == year_text:
                return True
        return False

    def _region_matches(self, metadata: dict[str, Any], region: str) -> bool:
        prefixes = self.get_region_prefixes_for_text(region)
        standard_code = self._normalize_standard_code(str(metadata.get("standard_code", "")))
        if prefixes and any(standard_code.startswith(prefix.lower()) for prefix in prefixes):
            return True

        region_values = [
            metadata.get("region"),
            metadata.get("province"),
            metadata.get("city"),
            metadata.get("document_name"),
            metadata.get("_title"),
            metadata.get("_content"),
        ]
        expected_aliases = self._region_aliases(region)
        haystack = self._normalize_text(" ".join(str(value or "") for value in region_values))
        return any(alias and alias in haystack for alias in expected_aliases)

    def _keywords_match(self, metadata: dict[str, Any], keywords: list[str]) -> bool:
        haystack = self._normalize_text(" ".join(self._stringify(value) for value in metadata.values()))
        return all(self._normalize_text(keyword) in haystack for keyword in keywords)

    def _result_geometry(self, result: DocumentResult) -> Optional[BaseGeometry]:
        spatial_info = result.spatial_info or {}
        geometry_payload = spatial_info.get("geometry")
        if not geometry_payload:
            nested_spatial = result.metadata.get("spatial_metadata") or result.metadata.get("spatial_info") or {}
            geometry_payload = nested_spatial.get("geometry") if isinstance(nested_spatial, dict) else None
        return self._coerce_geometry(geometry_payload)

    def _coerce_geometry(self, geometry_payload: Any) -> Optional[BaseGeometry]:
        if not geometry_payload:
            return None
        try:
            geometry = shape(geometry_payload)
            if geometry.is_empty or not geometry.is_valid:
                return None
            return geometry
        except Exception:
            return None

    def _matches_spatial_relation(
        self,
        result_geometry: BaseGeometry,
        query_geometry: BaseGeometry,
        spatial_filter: SpatialFilter,
    ) -> bool:
        relation = (spatial_filter.spatial_relation or "intersects").lower()
        if relation == "within":
            return result_geometry.within(query_geometry)
        if relation == "contains":
            return result_geometry.contains(query_geometry)
        if relation == "near":
            max_distance_meters = spatial_filter.distance or 0
            return result_geometry.distance(query_geometry) * 111_320 <= max_distance_meters
        if relation == "overlaps":
            return result_geometry.overlaps(query_geometry)
        if relation == "disjoint":
            return result_geometry.disjoint(query_geometry)
        return result_geometry.intersects(query_geometry)

    def _as_values(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_text(str(item)) for item in value if item is not None]
        return [self._normalize_text(str(value))]

    def _stringify(self, value: Any) -> str:
        if isinstance(value, (dict, list, tuple, set)):
            return json.dumps(value, ensure_ascii=False)
        return str(value or "")

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", "", value or "").lower()

    def _normalize_standard_code(self, value: str) -> str:
        return re.sub(r"[^0-9a-z]+", "", value.lower())

    def _region_aliases(self, name: str) -> list[str]:
        if not name:
            return []
        aliases = {
            name,
            name.removesuffix("省"),
            name.removesuffix("市"),
            name.removesuffix("特别行政区"),
            name.removesuffix("壮族自治区"),
            name.removesuffix("回族自治区"),
            name.removesuffix("维吾尔自治区"),
            name.removesuffix("自治区"),
        }
        return [self._normalize_text(alias) for alias in aliases if alias]
