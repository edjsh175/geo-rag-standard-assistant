from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import document_routes


def test_document_upload_disabled_does_not_initialize_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes.settings, "DOCUMENT_UPLOAD_ENABLED", False)

    def fail_if_constructed(*_args, **_kwargs):
        raise AssertionError("DocumentService should not be constructed when uploads are disabled")

    monkeypatch.setattr(document_routes, "DocumentService", fail_if_constructed)

    with pytest.raises(HTTPException) as exc_info:
        document_routes.get_document_service()

    assert exc_info.value.status_code == 503
    assert "DOCUMENT_UPLOAD_ENABLED=True" in str(exc_info.value.detail)


def test_document_upload_enabled_constructs_service(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(document_routes.settings, "DOCUMENT_UPLOAD_ENABLED", True)
    monkeypatch.setattr(document_routes, "DocumentService", lambda: sentinel)

    assert document_routes.get_document_service() is sentinel
