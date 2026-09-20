from __future__ import annotations

from datetime import datetime

import pytest

from app.models.search_models import DocumentResult
from app.services.rag.contracts import (
    RetrievalCandidate,
    RetrievalDiagnostics,
    RetrievalQuery,
    RetrievalResult,
)
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter
from app.services.search_service import SearchService


def make_result(
    result_id: str,
    similarity: float,
    *,
    document_name: str,
    chunk_id: str | None = None,
    document_id: str | None = None,
) -> DocumentResult:
    metadata = {
        "document_name": document_name,
        "match_type": "keyword",
    }
    if chunk_id is not None:
        metadata["chunk_id"] = chunk_id
    if document_id is not None:
        metadata["document_id"] = document_id
    return DocumentResult(
        id=result_id,
        title=document_name,
        content=f"content:{document_name}",
        similarity=similarity,
        metadata=metadata,
        spatial_info=None,
        file_type="pdf",
        file_size=0,
        upload_time=datetime.now(),
        source_url=None,
    )


def test_retrieval_candidate_preserves_real_chunk_and_document_identity() -> None:
    candidate = RetrievalCandidate.from_document_result(
        make_result(
            "doc-7",
            0.91,
            document_name="uploaded.pdf",
            chunk_id="chunk-3",
            document_id="doc-7",
        )
    )

    assert candidate.chunk_id == "chunk-3"
    assert candidate.document_id == "doc-7"
    assert candidate.provenance.source == "postgres"
    assert candidate.provenance.match_type == "keyword"


def test_policy_chunk_candidate_does_not_invent_document_id() -> None:
    candidate = RetrievalCandidate.from_document_result(
        make_result("policy-chunk-9", 1.0, document_name="GB 50016")
    )

    assert candidate.chunk_id == "policy-chunk-9"
    assert candidate.document_id is None


@pytest.mark.asyncio
async def test_postgres_adapter_keeps_exact_and_keyword_when_embedding_fails() -> None:
    adapter = PostgresRetrievalAdapter()

    async def exact_search(query: str, top_k: int) -> list[DocumentResult]:
        return [make_result("exact", 1.0, document_name="exact")]

    async def keyword_search(query: str, top_k: int) -> list[DocumentResult]:
        return [make_result("keyword", 0.8, document_name="keyword")]

    async def unavailable_embedding(query: str) -> list[float]:
        raise RuntimeError("embedding provider unavailable")

    async def forbidden_vector_search(*args, **kwargs) -> list[DocumentResult]:
        raise AssertionError("vector search must not run without an embedding")

    adapter._exact_standard_code_search = exact_search  # type: ignore[method-assign]
    adapter._keyword_search = keyword_search  # type: ignore[method-assign]
    adapter._get_query_embedding = unavailable_embedding  # type: ignore[method-assign]
    adapter._vector_search = forbidden_vector_search  # type: ignore[method-assign]

    result = await adapter.retrieve(
        RetrievalQuery(
            query_text="DB50/T 1846-2025",
            top_k=10,
            threshold=0.7,
            search_mode="hybrid",
        )
    )

    assert [candidate.chunk_id for candidate in result.candidates] == ["exact", "keyword"]
    assert result.embedding_available is False
    assert result.diagnostics.exact_count == 1
    assert result.diagnostics.keyword_count == 1
    assert result.diagnostics.vector_count == 0


@pytest.mark.asyncio
async def test_search_service_is_thin_facade_over_retrieval_port() -> None:
    source_result = make_result("chunk-1", 0.88, document_name="standard-a")
    candidate = RetrievalCandidate.from_document_result(source_result)

    class FakeRetrievalPort:
        def __init__(self) -> None:
            self.query: RetrievalQuery | None = None

        async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            self.query = query
            return RetrievalResult(
                candidates=(candidate,),
                embedding_available=True,
                diagnostics=RetrievalDiagnostics(keyword_count=1),
            )

    fake_port = FakeRetrievalPort()
    service = SearchService.__new__(SearchService)
    service.retrieval_adapter = fake_port
    service._log_search = lambda *args, **kwargs: None

    results = await service.search(
        "standard-a",
        top_k=5,
        threshold=0.6,
        search_mode="keyword",
        use_rerank=False,
    )

    assert results == [source_result]
    assert fake_port.query == RetrievalQuery(
        query_text="standard-a",
        top_k=5,
        threshold=0.6,
        search_mode="keyword",
        use_rerank=False,
    )


@pytest.mark.asyncio
async def test_deterministic_search_does_not_semantically_block_greeting_text() -> None:
    source_result = make_result("chunk-hi", 0.75, document_name="greeting-doc")
    candidate = RetrievalCandidate.from_document_result(source_result)

    class FakeRetrievalPort:
        called = False

        async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            self.called = True
            return RetrievalResult(
                candidates=(candidate,),
                embedding_available=False,
            )

    fake_port = FakeRetrievalPort()
    service = SearchService.__new__(SearchService)
    service.retrieval_adapter = fake_port
    service._log_search = lambda *args, **kwargs: None

    results = await service.search("你好", search_mode="keyword", use_rerank=False)

    assert fake_port.called is True
    assert results == [source_result]


@pytest.mark.asyncio
async def test_find_similar_documents_delegates_to_postgres_adapter() -> None:
    similar = make_result("similar-1", 0.81, document_name="similar")

    class FakeRetrievalAdapter:
        async def find_similar_documents(
            self,
            doc_id: str,
            top_k: int,
        ) -> list[DocumentResult]:
            assert doc_id == "doc-1"
            assert top_k == 3
            return [similar]

    service = SearchService.__new__(SearchService)
    service.retrieval_adapter = FakeRetrievalAdapter()

    results = await service.find_similar_documents("doc-1", top_k=3)

    assert results == [similar]


@pytest.mark.asyncio
async def test_hybrid_search_delegates_spatial_lookup_to_adapter() -> None:
    text_result = make_result("text-1", 0.9, document_name="text")
    spatial_result = make_result("spatial-1", 0.7, document_name="spatial")

    class FakeRetrievalAdapter:
        spatial_query: str | None = None

        async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            return RetrievalResult(
                candidates=(RetrievalCandidate.from_document_result(text_result),),
                embedding_available=False,
            )

        async def spatial_search(
            self,
            spatial_query: str,
            top_k: int,
        ) -> list[DocumentResult]:
            self.spatial_query = spatial_query
            assert top_k == 5
            return [spatial_result]

    adapter = FakeRetrievalAdapter()
    service = SearchService.__new__(SearchService)
    service.retrieval_adapter = adapter
    service._log_search = lambda *args, **kwargs: None

    results = await service.hybrid_search("滑坡", spatial_query="重庆", top_k=5)

    assert adapter.spatial_query == "重庆"
    assert [item.id for item in results] == ["text-1", "spatial-1"]
