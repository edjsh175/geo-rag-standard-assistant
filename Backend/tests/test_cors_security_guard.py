from __future__ import annotations

import pytest

from app.core.config import Settings, validate_cors_configuration


def test_cors_validation_passes_in_debug_with_dev_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        DEBUG=True,
        CORS_ORIGINS=["http://localhost:5173", "http://127.0.0.1:3000"],
    )
    # In debug mode, local development origins must be allowed
    validate_cors_configuration(settings)


def test_cors_validation_fails_in_production_with_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        DEBUG=False,
        CORS_ORIGINS=["*"],
    )
    with pytest.raises(RuntimeError, match="cannot contain wildcard"):
        validate_cors_configuration(settings)


def test_cors_validation_fails_in_production_with_dev_loopback_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        DEBUG=False,
        CORS_ORIGINS=["http://localhost:5173"],
    )
    with pytest.raises(RuntimeError, match="contains insecure development loopback origin"):
        validate_cors_configuration(settings)

    settings_ip = Settings(
        DEBUG=False,
        CORS_ORIGINS=["http://127.0.0.1:8080"],
    )
    with pytest.raises(RuntimeError, match="contains insecure development loopback origin"):
        validate_cors_configuration(settings_ip)


def test_cors_validation_passes_in_production_with_explicit_production_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        DEBUG=False,
        CORS_ORIGINS=["https://geoai.mycompany.org", "https://gis.mycompany.org:8443"],
    )
    validate_cors_configuration(settings)
