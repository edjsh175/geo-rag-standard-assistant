from __future__ import annotations

from datetime import datetime

from app.models.search_models import DocumentResult, MetadataFilter
from app.services.rag.filters import RagFilterEngine


def make_result(doc_id: str, metadata: dict, content: str = "") -> DocumentResult:
    return DocumentResult(
        id=doc_id,
        title=str(metadata.get("document_name", doc_id)),
        content=content,
        similarity=0.8,
        metadata=metadata,
        spatial_info=None,
        file_type=str(metadata.get("file_type", "pdf")),
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


def test_metadata_filter_matches_whitelisted_fields_and_region_prefix() -> None:
    engine = RagFilterEngine()
    metadata = {
        "document_type": "标准规范",
        "source": "自然资源部",
        "release_date": "2024-05-01",
        "standard_code": "DB50/T 1846-2025",
        "keyword": "滑坡 防治 国土空间规划",
        "standard_status": "现行",
    }

    filter_ = MetadataFilter(
        document_type="标准",
        source="自然资源",
        year=2024,
        region="重庆市",
        keywords=["滑坡", "规划"],
        custom_filters={"standard_status": "现行"},
    )

    assert engine.matches_metadata_filter(metadata, filter_)


def test_metadata_filter_rejects_unknown_custom_filter_keys() -> None:
    engine = RagFilterEngine()
    metadata = {"document_name": "重庆市滑坡防治规范", "standard_code": "DB50/T 1846-2025"}

    filter_ = MetadataFilter(custom_filters={"DROP TABLE policy_chunks": "x"})

    assert not engine.matches_metadata_filter(metadata, filter_)


def test_apply_metadata_filter_returns_only_matching_results() -> None:
    engine = RagFilterEngine()
    results = [
        make_result(
            "match",
            {
                "document_name": "重庆市滑坡防治规范",
                "standard_code": "DB50/T 1846-2025",
                "keyword": "滑坡 防治",
            },
        ),
        make_result(
            "miss",
            {
                "document_name": "四川省测绘规范",
                "standard_code": "DB51/T 1000-2024",
                "keyword": "测绘",
            },
        ),
    ]

    filtered = engine.apply_metadata_filter(
        results,
        MetadataFilter(region="重庆市", keywords=["滑坡"]),
    )

    assert [result.id for result in filtered] == ["match"]
    assert filtered[0].metadata["metadata_filter_match"] is True
