from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from app.models.problem_details import ProblemDetails


def test_problem_details_structure():
    problem = ProblemDetails.from_status(
        status_code=400,
        detail="visitor_id is required",
        instance="/api/agent/sessions",
    )
    d = problem.to_response_dict()
    assert d["type"] == "urn:geoai:error:400"
    assert d["title"] == "Bad Request"
    assert d["status"] == 400
    assert d["detail"] == "visitor_id is required"
    assert d["instance"] == "/api/agent/sessions"
    assert "error" in d
    assert d["error"]["status"] == 400
    assert d["error"]["detail"] == "visitor_id is required"


def test_http_exception_returns_problem_details():
    client = TestClient(main.app)
    # Trigger an intentional 404 or invalid route
    response = client.get("/api/non_existent_route_404")
    assert response.status_code == 404
    data = response.json()
    assert data["status"] == 404
    assert "detail" in data
    assert "type" in data
    assert "title" in data
    assert "error" in data
    assert data["error"]["status"] == 404
