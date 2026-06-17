from __future__ import annotations

import main


def test_openapi_contains_contract_governance_endpoints() -> None:
    paths = main.app.openapi()["paths"]

    assert "post" in paths["/api/search/feedback"]
    assert "patch" in paths["/api/documents/{doc_id}"]
    assert "post" in paths["/api/documents/batch"]
    assert "post" in paths["/api/search/query/stream"]


def test_search_query_and_stream_have_separate_response_contracts() -> None:
    paths = main.app.openapi()["paths"]

    query_response_content = paths["/api/search/query"]["post"]["responses"]["200"]["content"]
    stream_response_content = paths["/api/search/query/stream"]["post"]["responses"]["200"]["content"]

    assert "application/json" in query_response_content
    assert "text/event-stream" not in query_response_content
    assert "text/event-stream" in stream_response_content
