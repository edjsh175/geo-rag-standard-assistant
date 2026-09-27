"""Run uploaded-document indexing jobs."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
import tempfile
from typing import Any, Protocol
from uuid import uuid4

from minio import Minio

from app.core.config import settings
from app.core.llm_config import llm_config
from app.services.document_chunker import (
    DocumentChunker,
    compute_chunk_uid,
    compute_content_hash,
)
from app.services.document_parser import DocumentParser
from app.services.document_repository import (
    DocumentDeletedConflictError,
    DocumentRepository,
    DocumentVersionConflictError,
)
from app.services.document_text_extractor import UnsupportedDocumentParser

logger = logging.getLogger(__name__)


class IndexingRepository(Protocol):
    async def get_indexing_payload(self, job_id: str) -> dict[str, Any] | None: ...

    async def claim_job(self, job_id: str, execution_token: str) -> bool: ...

    async def mark_job_running(self, job_id: str, stage: str, execution_token: str | None = None) -> None: ...

    async def update_job_stage(self, job_id: str, stage: str, execution_token: str | None = None) -> None: ...

    async def replace_chunks(self, **payload: Any) -> None: ...

    async def mark_job_succeeded(self, job_id: str, execution_token: str | None = None) -> None: ...

    async def mark_job_failed(self, job_id: str, error: str, retrying: bool = False, execution_token: str | None = None) -> None: ...

    async def mark_job_cancelled(self, job_id: str, error: str, execution_token: str | None = None) -> None: ...


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

    async def run_job(
        self,
        job_id: str,
        *,
        retrying_on_error: bool = False,
        execution_token: str | None = None,
    ) -> None:
        token = execution_token or str(uuid4())

        async def _call_repo(method_name: str, *args, **kwargs) -> Any:
            if not hasattr(self.repository, method_name):
                return None
            fn = getattr(self.repository, method_name)
            try:
                res = fn(*args, **kwargs)
            except TypeError:
                kwargs.pop("execution_token", None)
                res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res

        # O-02: Atomic claim before attempting work
        if hasattr(self.repository, "claim_job"):
            claim_res = self.repository.claim_job(job_id, token)
            if inspect.isawaitable(claim_res):
                claimed = await claim_res
            elif isinstance(claim_res, bool):
                claimed = claim_res
            else:
                claimed = True
            if not claimed:
                logger.info("Index job %s already claimed or not queued/retrying; skipping.", job_id)
                return

        payload = await _call_repo("get_indexing_payload", job_id)
        if not payload:
            return

        async def _cancel_or_fail(reason: str) -> None:
            if hasattr(self.repository, "mark_job_cancelled"):
                await _call_repo("mark_job_cancelled", job_id, reason, execution_token=token)
            else:
                await _call_repo("mark_job_failed", job_id, reason, retrying=False, execution_token=token)

        if payload.get("deleted_at") is not None:
            await _cancel_or_fail("Document was deleted before indexing.")
            return

        local_path: Path | None = None
        try:
            await _call_repo("mark_job_running", job_id, "parsing", execution_token=token)

            local_path = await self.storage.download_version_to_temp(payload)
            parsed = self.parser.parse(local_path, payload.get("mime_type"))
            if not parsed.markdown.strip():
                raise UnsupportedDocumentParser("No indexable text was extracted from the document.")

            # G-03: verify active status before chunking/embedding
            fresh_payload = await _call_repo("get_indexing_payload", job_id)
            if not fresh_payload or fresh_payload.get("deleted_at") is not None:
                await _cancel_or_fail("Document was deleted during parsing.")
                return

            await _call_repo("update_job_stage", job_id, "chunking", execution_token=token)

            document_chunks = self.chunker.chunk(parsed)
            if not document_chunks:
                raise UnsupportedDocumentParser("No indexable chunks were produced from the document.")

            # G-03: verify active status before expensive embedding
            fresh_payload = await _call_repo("get_indexing_payload", job_id)
            if not fresh_payload or fresh_payload.get("deleted_at") is not None:
                await _cancel_or_fail("Document was deleted before embedding.")
                return

            await _call_repo("update_job_stage", job_id, "embedding", execution_token=token)

            embedding_inputs = [
                self._build_embedding_input(payload, chunk.content)
                for chunk in document_chunks
            ]
            embeddings = await self.embedding_provider.embed_texts(embedding_inputs)
            if len(embeddings) != len(document_chunks):
                raise RuntimeError("Embedding provider returned a mismatched number of vectors.")

            # G-03: verify active status before chunk replacement
            fresh_payload = await _call_repo("get_indexing_payload", job_id)
            if not fresh_payload or fresh_payload.get("deleted_at") is not None:
                await _cancel_or_fail("Document was deleted during embedding.")
                return

            base_metadata = dict(payload.get("metadata") or {})
            chunks = []
            total_chunks = len(document_chunks)
            uids: list[tuple[str, str]] = []
            for index, chunk in enumerate(document_chunks):
                c_hash = chunk.content_hash or compute_content_hash(chunk.content)
                c_uid = compute_chunk_uid(
                    document_id=payload["document_id"],
                    section_path=chunk.header_path,
                    chunk_index=index,
                    content_hash=c_hash,
                )
                uids.append((c_uid, c_hash))

            for index, chunk in enumerate(document_chunks):
                chunk_uid, content_hash = uids[index]
                prev_uid = uids[index - 1][0] if index > 0 else None
                next_uid = uids[index + 1][0] if index < total_chunks - 1 else None

                chunk_metadata = {
                    **base_metadata,
                    **dict(parsed.metadata or {}),
                    "title": payload.get("title") or base_metadata.get("title"),
                    "filename": payload.get("filename"),
                    "chunk_uid": chunk_uid,
                    "content_hash": content_hash,
                    "section_path": chunk.header_path,
                    "page_number": chunk.page_number,
                    "chunk_policy_id": getattr(chunk, "chunk_policy_id", "section_based_v1"),
                    "content_role": getattr(chunk, "content_role", "prose"),
                    "prev_chunk_uid": prev_uid,
                    "next_chunk_uid": next_uid,
                    "source_element_orders": getattr(chunk, "source_element_orders", []),
                }
                chunks.append(
                    {
                        "id": chunk_uid,
                        "chunk_uid": chunk_uid,
                        "content_hash": content_hash,
                        "chunk_index": index,
                        "header_path": chunk.header_path,
                        "page_number": chunk.page_number,
                        "content": chunk.content,
                        "metadata": chunk_metadata,
                        "embedding": embeddings[index],
                    }
                )

            try:
                try:
                    rep_res = self.repository.replace_chunks(
                        document_id=payload["document_id"],
                        version_id=payload["version_id"],
                        chunks=chunks,
                        execution_token=token,
                    )
                except TypeError:
                    rep_res = self.repository.replace_chunks(
                        document_id=payload["document_id"],
                        version_id=payload["version_id"],
                        chunks=chunks,
                    )
                if inspect.isawaitable(rep_res):
                    await rep_res
            except DocumentDeletedConflictError as exc:
                await _cancel_or_fail(str(exc))
                return

            await _call_repo("mark_job_succeeded", job_id, execution_token=token)
        except Exception as exc:
            should_retry = retrying_on_error and not isinstance(
                exc, (UnsupportedDocumentParser, DocumentDeletedConflictError, DocumentVersionConflictError)
            )
            await _call_repo("mark_job_failed", job_id, str(exc), retrying=should_retry, execution_token=token)
            raise
        finally:
            if local_path is not None:
                local_path.unlink(missing_ok=True)

    @staticmethod
    def _build_embedding_input(payload: dict[str, Any], chunk: str) -> str:
        title = payload.get("title") or payload.get("filename") or ""
        return f"[Title: {title}]\n\n{chunk}" if title else chunk
