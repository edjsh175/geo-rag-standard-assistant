"""Celery tasks for uploaded document indexing."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import db_manager
from app.services.document_indexing_service import DocumentIndexingService
from app.services.document_text_extractor import UnsupportedDocumentParser
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run_index_job(job_id: str, *, retrying_on_error: bool = False) -> None:
    await db_manager.initialize()
    try:
        await DocumentIndexingService().run_job(job_id, retrying_on_error=retrying_on_error)
    finally:
        await db_manager.close()


@celery_app.task(
    name="app.worker.document_tasks.index_document_job",
    bind=True,
    max_retries=settings.DOCUMENT_INDEX_MAX_RETRIES,
)
def index_document_job(self, job_id: str) -> None:
    logger.info("Starting document index job %s", job_id)
    retrying_on_error = self.request.retries < settings.DOCUMENT_INDEX_MAX_RETRIES
    try:
        asyncio.run(_run_index_job(job_id, retrying_on_error=retrying_on_error))
    except Exception as exc:
        logger.exception("Document index job %s failed: %s", job_id, exc)
        if retrying_on_error and not isinstance(exc, UnsupportedDocumentParser):
            countdown = min(60, 2 ** self.request.retries)
            logger.info("Retrying document index job %s in %s seconds", job_id, countdown)
            raise self.retry(exc=exc, countdown=countdown)
        raise
