"""Tests for F-01/F-02/F-03 (Security startup guards, production secret safety, and trusted proxy IP resolution)."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from starlette.requests import Request

from app.core import auth
from app.core.config import settings


# ============================================================================
# F-02: Production Secret & Password Safety Startup Guards
# ============================================================================

def test_f02_validate_admin_auth_passes_in_debug_with_dev_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "SECRET_KEY", "dev-only-secret-key-set-SECRET_KEY-in-env")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "devpass123")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", None)

    # In debug mode, dev key and plaintext password are permissible
    auth.validate_admin_auth_configuration()


def test_f02_validate_admin_auth_fails_in_production_with_dev_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "SECRET_KEY", "dev-only-secret-key-set-SECRET_KEY-in-env")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW")

    with pytest.raises(RuntimeError, match="insecure default/placeholder value while DEBUG=False"):
        auth.validate_admin_auth_configuration()


def test_f02_validate_admin_auth_fails_in_production_with_other_insecure_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW")

    for weak_key in ["secret", "changeme", "default", "password"]:
        monkeypatch.setattr(settings, "SECRET_KEY", weak_key)
        with pytest.raises(RuntimeError, match="insecure default/placeholder value while DEBUG=False"):
            auth.validate_admin_auth_configuration()


def test_f02_validate_admin_auth_passes_in_production_with_strong_secret_and_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "SECRET_KEY", "a-very-strong-production-secret-key-32chars-minimum!")
    # Valid bcrypt hash for testing
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)

    auth.validate_admin_auth_configuration()


# ============================================================================
# F-03: Trusted Proxy & Client IP Safety Guards
# ============================================================================

def _build_request(peer_host: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "client": (peer_host, 12345),
        "headers": raw_headers,
    }
    return Request(scope)


def test_f03_client_ip_rejects_spoofed_x_forwarded_for_from_untrusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])

    # Direct client from internet with spoofed header
    request = _build_request(
        peer_host="203.0.113.50",
        headers={"x-forwarded-for": "8.8.8.8, 10.0.0.1"},
    )

    resolved_ip = auth.get_client_ip(request)
    # Must reject spoofed header and use actual peer IP
    assert resolved_ip == "203.0.113.50"


def test_f03_client_ip_accepts_x_forwarded_for_from_trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "10.0.0.0/8"])

    # Request from internal reverse proxy (127.0.0.1) forwarding legitimate client IP
    request = _build_request(
        peer_host="127.0.0.1",
        headers={"x-forwarded-for": "198.51.100.22, 127.0.0.1"},
    )

    resolved_ip = auth.get_client_ip(request)
    assert resolved_ip == "198.51.100.22"
