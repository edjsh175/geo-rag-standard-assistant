from __future__ import annotations

import httpx
import pytest

from app.core import llm_config as llm_config_module


@pytest.mark.parametrize("proxy", [None, "http://127.0.0.1:8080"])
def test_deepseek_client_uses_httpx_028_proxy_argument(monkeypatch, proxy: str | None) -> None:
    monkeypatch.setattr(llm_config_module.settings, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(llm_config_module.settings, "DEEPSEEK_PROXY", proxy)

    client = llm_config_module.LLMConfig._create_deepseek_client()
    http_client = client._client

    try:
        assert isinstance(http_client, httpx.AsyncClient)
        assert http_client._trust_env is False
        assert http_client.timeout.connect == 10.0
        assert http_client.timeout.read == 60.0
        if proxy:
            assert len(http_client._mounts) == 1
            transport = next(iter(http_client._mounts.values()))
            assert type(transport._pool).__name__ == "AsyncHTTPProxy"
        else:
            assert http_client._mounts == {}
    finally:
        # The production call sites own and close the per-request client.
        import asyncio

        asyncio.run(client.close())
