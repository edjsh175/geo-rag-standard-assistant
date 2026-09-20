"""Run uploaded-document indexing jobs."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Protocol

from minio import Minio

from app.core.config import settings
from app.core.llm_config import llm_config
from app.services.document_chunker import DocumentChunker
from app.services.document_parser import DocumentParser
from app.services.document_repository import DocumentRepository
from app.services.document_text_extractor import UnsupportedDocumentParser


class IndexingRepository(Protocol):
    async def get_indexing_payload(self, job_id: str) -> dict[str, Any] | None: ...

    async def mark_job_running(self, job_id: str, stage: str) -> None: ...

    async def update_job_stage(self, job_id: str, stage: str) -> None: ...

    async def replace_chunks(self, **payload: Any) -> None: ...

    async def mark_job_succeeded(self, job_id: str) -> None: ...

    async def mark_job_failed(self, job_id: str, error: str, retrying: bool = False) -> None: ...


class MinioDocumentVersionStorage:
    """Download document versions from the private MinIO bucket."""

    def __init__(self) -> None:
        self.client = Minio(
            settings.MINIO_URL,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

    async def download_version_to_temp(self, payload: dict[str, Any]) -> Path:
        suffix = Path(str(payload.get("filename") or payload.get("storage_key") or "")).suffix
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        target = Path(handle.name)
        bucket = payload.get("storage_bucket") or settings.MINIO_BUCKET
        self.client.fget_object(bucket, payload["storage_key"], str(target))
        return target


class LLMEmbeddingProvider:
    """Batch embedding adapter around the configured LLM embedding provider."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        batch_size = max(1, settings.DOCUMENT_EMBED_BATCH_SIZE)
        for offset in range(0, len(texts), batch_size):
            embeddings.extend(await llm_config.get_embeddings(texts[offset : offset + batch_size]))
        return embeddings


class DocumentIndexingService:
    """Index one document version into `document_chunks`."""

    def __init__(
        self,
        repository: IndexingRepository | None = None,
        storage: Any | None = None,
        parser: DocumentParser | None = None,
        chunker: DocumentChunker | None = None,
        embedding_provider: Any | None = None,
    ) -> None:
        self.repository = repository or DocumentRepository()
        self.storage = storage or MinioDocumentVersionStorage()
        self.parser = parser or DocumentParser()
        self.chunker = chunker or DocumentChunker(
            chunk_size=settings.DOCUMENT_CHUNK_SIZE,
            chunk_overlap=settings.DOCUMENT_CHUNK_OVERLAP,
        )
        self.embedding_provider = embedding_provider or LLMEmbeddingProvider()

    async def run_job(self, job_id: str, *, retrying_on_error: bool = False) -> None:
        payload = await self.repository.get_indexing_payload(job_id)
        if not payload:
            return
        if payload.get("deleted_at") is not None:
            await self.repository.mark_job_failed(job_id, "Document was deleted before indexing.")
            return

        local_path: Path | None = None
        try:
            await self.repository.mark_job_running(job_id, "parsing")
            local_path = await self.storage.download_version_to_temp(payload)
            parsed = self.parser.parse(local_path, payload.get("mime_type"))
            if not parsed.markdown.strip():
                raise UnsupportedDocumentParser("No indexable text was extracted from the document.")

            await self.repository.update_job_stage(job_id, "chunking")
            document_chunks = self.chunker.chunk(parsed)
            if not document_chunks:
                raise UnsupportedDocumentParser("No indexable chunks were produced from the document.")

            await self.repository.update_job_stage(job_id, "embedding")
            embedding_inputs = [
                self._build_embedding_input(payload, chunk.content)
                for chunk in document_chunks
            ]
            embeddings = await self.embedding_provider.embed_texts(embedding_inputs)
            if len(embeddings) != len(document_chunks):
                raise RuntimeError("Embedding provider returned a mismatched number of vectors.")

            base_metadata = dict(payload.get("metadata") or {})
            chunks = [
                {
                    "chunk_index": index,
                    "header_path": chunk.header_path,
                    "page_number": chunk.page_number,
                    "content": chunk.content,
                    "metadata": {
                        **base_metadata,
                        **dict(parsed.metadata or {}),
                        "title": payload.get("title") or base_metadata.get("title"),
                        "filename": payload.get("filename"),
                    },
                    "embedding": embeddings[index],
                }
                for index, chunk in enumerate(document_chunks)
            ]
            await self.repository.replace_chunks(
                document_id=payload["document_id"],
                version_id=payload["version_id"],
                chunks=chunks,
            )
            await self.repository.mark_job_succeeded(job_id)
        except Exception as exc:
            should_retry = retrying_on_error and not isinstance(exc, UnsupportedDocumentParser)
            await self.repository.mark_job_failed(job_id, str(exc), retrying=should_retry)
            raise
        finally:
            if local_path is not None:
                local_path.unlink(missing_ok=True)

    @staticmethod
    def _build_embedding_input(payload: dict[str, Any], chunk: str) -> str:
        title = payload.get("title") or payload.get("filename") or ""
        return f"[Title: {title}]\n\n{chunk}" if title else chunk
