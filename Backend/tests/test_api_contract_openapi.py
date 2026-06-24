from __future__ import annotations

import main


def test_openapi_contains_contract_governance_endpoints() -> None:
    paths = main.app.openapi()["paths"]

    assert "post" in paths["/api/search/feedback"]
    assert "patch" in paths["/api/documents/{doc_id}"]
    assert "post" in paths["/api/documents/batch"]
    assert "get" in paths["/api/documents/jobs/{job_id}"]
    assert "post" in paths["/api/search/query/stream"]


def test_search_query_and_stream_have_separate_response_contracts() -> None:
    paths = main.app.openapi()["paths"]

    query_response_content = paths["/api/search/query"]["post"]["responses"]["200"]["content"]
    stream_response_content = paths["/api/search/query/stream"]["post"]["responses"]["200"]["content"]

    assert "application/json" in query_response_content
    assert "text/event-stream" not in query_response_content
    assert "text/event-stream" in stream_response_content


def test_document_upload_response_contains_lifecycle_fields() -> None:
    schema = main.app.openapi()
    upload_schema_ref = schema["paths"]["/api/documents/upload"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    schema_name = upload_schema_ref.rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][schema_name]["properties"]

    assert "version_id" in properties
    assert "job_id" in properties
    assert "index_status" in properties
