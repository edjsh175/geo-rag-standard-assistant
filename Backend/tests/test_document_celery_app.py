from __future__ import annotations

from app.core.config import settings
from app.worker.celery_app import celery_app
from app.worker.document_tasks import index_document_job


def test_document_celery_app_routes_index_jobs_to_documents_queue() -> None:
    routes = celery_app.conf.task_routes

    assert routes["app.worker.document_tasks.index_document_job"]["queue"] == "documents"
    assert celery_app.conf.task_default_queue == "documents"
    assert index_document_job.max_retries == settings.DOCUMENT_INDEX_MAX_RETRIES
