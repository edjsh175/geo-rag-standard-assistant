"""Run acceptance scenarios for RAG search filters, rerank, degradation, and logs."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_PATH = REPO_ROOT / "Backend"
sys.path.insert(0, str(BACKEND_PATH))

from app.models.search_models import DocumentResult, MetadataFilter, SpatialFilter  # noqa: E402
from app.services.search_service import SearchService  # noqa: E402


def normalize_standard_code(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", value.lower())


def make_result(
    doc_id: str,
    title: str,
    content: str,
    standard_code: str,
    similarity: float,
    metadata: dict[str, Any] | None = None,
    geometry: dict[str, Any] | None = None,
) -> DocumentResult:
    payload = {
        "document_name": title,
        "standard_code": standard_code,
        **(metadata or {}),
    }
    return DocumentResult(
        id=doc_id,
        title=title,
        content=content,
        similarity=similarity,
        metadata=payload,
        spatial_info={"geometry": geometry} if geometry else None,
        file_type=str(payload.get("document_type", "pdf")),
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


INSIDE_CHONGQING_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [105.0, 29.0],
        [106.0, 29.0],
        [106.0, 30.0],
        [105.0, 30.0],
        [105.0, 29.0],
    ]],
}

OUTSIDE_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [100.0, 30.0],
        [101.0, 30.0],
        [101.0, 31.0],
        [100.0, 31.0],
        [100.0, 30.0],
    ]],
}

DOCUMENTS = [
    make_result(
        "target-db50",
        "重庆市滑坡防治监测技术规范",
        "滑坡防治、变形监测、国土空间规划风险管控要求。",
        "DB50/T 1846-2025",
        0.72,
        {
            "document_type": "标准规范",
            "source": "重庆市规划和自然资源局",
            "release_date": "2025-03-01",
            "keyword": "滑坡 防治 监测",
            "standard_status": "现行",
        },
        INSIDE_CHONGQING_GEOMETRY,
    ),
    make_result(
        "chongqing-noise",
        "重庆市建设工程资料规范",
        "建设工程资料归档要求。",
        "DB50/T 1900-2025",
        0.96,
        {
            "document_type": "标准规范",
            "source": "重庆市住房城乡建设主管部门",
            "release_date": "2025-01-01",
            "keyword": "建设 工程",
            "standard_status": "现行",
        },
        INSIDE_CHONGQING_GEOMETRY,
    ),
    make_result(
        "sichuan-landslide",
        "四川省滑坡防治测绘规范",
        "滑坡防治、监测和测绘技术要求。",
        "DB51/T 1000-2024",
        0.84,
        {
            "document_type": "标准规范",
            "source": "四川省自然资源厅",
            "release_date": "2024-05-01",
            "keyword": "滑坡 防治 监测 测绘",
            "standard_status": "现行",
        },
        OUTSIDE_GEOMETRY,
    ),
]


class ScenarioHarness:
    def __init__(self, embedding_available: bool = True) -> None:
        self.embedding_available = embedding_available
        self.logs: list[dict[str, Any]] = []
        self.service = SearchService.__new__(SearchService)
        self.service._exact_standard_code_search = self.exact_search
        self.service._keyword_search = self.keyword_search
        self.service._vector_search = self.vector_search
        self.service._get_query_embedding = self.get_query_embedding
        self.service._log_search = self.log_search

    async def get_query_embedding(self, query: str) -> list[float]:
        if not self.embedding_available:
            raise RuntimeError("forced embedding outage")
        return [0.1, 0.2, 0.3]

    async def exact_search(self, query: str, top_k: int) -> list[DocumentResult]:
        normalized_query = normalize_standard_code(query)
        return [
            doc.model_copy(deep=True)
            for doc in DOCUMENTS
            if normalize_standard_code(str(doc.metadata["standard_code"])) == normalized_query
        ][:top_k]

    async def keyword_search(self, query: str, top_k: int) -> list[DocumentResult]:
        terms = [term for term in re.split(r"\s+", query.strip()) if term]
        matches = []
        for doc in DOCUMENTS:
            haystack = f"{doc.title} {doc.content} {' '.join(str(v) for v in doc.metadata.values())}"
            if terms and all(term in haystack for term in terms):
                matches.append(doc.model_copy(deep=True))
        return matches[:top_k]

    async def vector_search(self, *args, **kwargs) -> list[DocumentResult]:
        return [
            doc.model_copy(deep=True)
            for doc in sorted(DOCUMENTS, key=lambda item: item.similarity, reverse=True)
        ][: kwargs.get("top_k", 10)]

    async def log_search(self, **kwargs) -> None:
        self.logs.append(kwargs)


def assert_ids(label: str, actual: list[DocumentResult], expected: list[str]) -> None:
    actual_ids = [result.id for result in actual]
    if actual_ids != expected:
        raise AssertionError(f"{label}: expected {expected}, got {actual_ids}")
    print(f"{label}: {actual_ids}")


def assert_id_set(label: str, actual: list[DocumentResult], expected: set[str]) -> None:
    actual_ids = {result.id for result in actual}
    if actual_ids != expected:
        raise AssertionError(f"{label}: expected set {sorted(expected)}, got {sorted(actual_ids)}")
    print(f"{label}: {sorted(actual_ids)}")


def assert_logged_filter(label: str, log_payload: dict[str, Any], key: str) -> None:
    if log_payload.get(key) is None:
        raise AssertionError(f"{label}: expected {key} in search log payload")
    if log_payload.get("results_count") != 1:
        raise AssertionError(f"{label}: expected logged results_count=1, got {log_payload.get('results_count')}")
    if "search_time" not in log_payload:
        raise AssertionError(f"{label}: expected search_time in search log payload")
    print(
        f"{label}:",
        {
            "search_mode": log_payload.get("search_mode"),
            key: "present",
            "results_count": log_payload.get("results_count"),
            "search_time_recorded": True,
        },
    )


async def main() -> int:
    standard_harness = ScenarioHarness()
    exact_results = await standard_harness.service.search(
        "DB50/T 1846-2025",
        search_mode="hybrid",
        top_k=5,
    )
    assert_ids("standard_code_exact", exact_results[:1], ["target-db50"])

    keyword_harness = ScenarioHarness()
    keyword_results = await keyword_harness.service.search(
        "滑坡防治 监测",
        search_mode="keyword",
        top_k=5,
    )
    assert_id_set("keyword_query", keyword_results, {"target-db50", "sichuan-landslide"})

    metadata_harness = ScenarioHarness()
    metadata_results = await metadata_harness.service.search(
        "滑坡防治 监测",
        search_mode="keyword",
        metadata_filter=MetadataFilter(
            region="重庆市",
            year=2025,
            document_type="标准",
        ),
        top_k=5,
    )
    assert_ids("metadata_filter", metadata_results, ["target-db50"])
    assert_logged_filter("metadata_filter_log", metadata_harness.logs[-1], "metadata_filter")

    spatial_harness = ScenarioHarness()
    unfiltered_spatial_candidates = await spatial_harness.service.search(
        "滑坡防治 监测",
        search_mode="keyword",
        top_k=5,
    )
    filtered_spatial_results = await spatial_harness.service.search(
        "滑坡防治 监测",
        search_mode="keyword",
        spatial_filter=SpatialFilter(
            geometry={"type": "Point", "coordinates": [105.5, 29.5]},
            spatial_relation="intersects",
        ),
        top_k=5,
    )
    if len(filtered_spatial_results) >= len(unfiltered_spatial_candidates):
        raise AssertionError("spatial_filter did not reduce/change result set")
    assert_ids("spatial_filter", filtered_spatial_results, ["target-db50"])
    assert_logged_filter("spatial_filter_log", spatial_harness.logs[-1], "spatial_filter")

    rerank_harness = ScenarioHarness()
    rerank_off = await rerank_harness.service.search(
        "DB50/T 1846-2025",
        search_mode="semantic",
        use_rerank=False,
        top_k=3,
    )
    rerank_on = await rerank_harness.service.search(
        "DB50/T 1846-2025",
        search_mode="semantic",
        use_rerank=True,
        top_k=3,
    )
    assert_ids("rerank_false_order", rerank_off[:2], ["chongqing-noise", "sichuan-landslide"])
    assert_ids("rerank_true_order", rerank_on[:1], ["target-db50"])

    outage_harness = ScenarioHarness(embedding_available=False)
    outage_results = await outage_harness.service.search(
        "DB50/T 1846-2025",
        search_mode="hybrid",
        top_k=5,
    )
    assert_ids("embedding_outage_exact_keyword", outage_results[:1], ["target-db50"])

    if not standard_harness.logs:
        raise AssertionError("search log was not captured")
    log_payload = standard_harness.logs[-1]
    required_log_keys = {
        "query",
        "results_count",
        "search_time",
        "search_mode",
        "top_k",
        "threshold",
        "used_rerank",
        "embedding_available",
    }
    missing_log_keys = required_log_keys - set(log_payload)
    if missing_log_keys:
        raise AssertionError(f"search log missing keys: {sorted(missing_log_keys)}")
    print(
        "search_log_payload:",
        {
            "query": log_payload["query"],
            "search_mode": log_payload["search_mode"],
            "results_count": log_payload["results_count"],
            "used_rerank": log_payload["used_rerank"],
            "embedding_available": log_payload["embedding_available"],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
