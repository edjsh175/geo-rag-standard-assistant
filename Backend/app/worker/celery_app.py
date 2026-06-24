"""Celery application for document indexing jobs."""

from __future__ import annotations

from celery import Celery

from app.core.config import settings


def _broker_url() -> str:
    return settings.CELERY_BROKER_URL or settings.REDIS_URL


def _result_backend() -> str:
    return settings.CELERY_RESULT_BACKEND or settings.REDIS_URL


celery_app = Celery(
    "geoai_document_worker",
    broker=_broker_url(),
    backend=_result_backend(),
    include=["app.worker.document_tasks"],
)

celery_app.conf.update(
    task_default_queue="documents",
    task_routes={
        "app.worker.document_tasks.index_document_job": {"queue": "documents"},
    },
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
