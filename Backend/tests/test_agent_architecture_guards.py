from __future__ import annotations

from pathlib import Path


AGENT_ROOT = Path(__file__).parents[1] / "app" / "services" / "agent"
SERVICES_ROOT = Path(__file__).parents[1] / "app" / "services"
FRONTEND_ROOT = Path(__file__).parents[2] / "frontend" / "src"


def test_agent_core_has_no_graph_or_chroma_subsystem() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in AGENT_ROOT.glob("*.py")
    ).lower()

    forbidden = (
        "chromadb",
        "graphworkingset",
        "graphbudget",
        "expand_graph_scope",
        "graph_state",
    )
    for symbol in forbidden:
        assert symbol not in source


def test_agent_runtime_does_not_define_semantic_retrieval_budgets() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in AGENT_ROOT.glob("*.py")
    ).lower()

    forbidden = (
        "max_retrievals",
        "retrieve_attempts",
        "single_entity",
        "multi_entity_relation",
    )
    for symbol in forbidden:
        assert symbol not in source


def test_legacy_search_generation_core_is_removed() -> None:
    search_service_source = (SERVICES_ROOT / "search_service.py").read_text(encoding="utf-8")
    application_source = (SERVICES_ROOT / "search_application_service.py").read_text(encoding="utf-8")
    route_source = (Path(__file__).parents[1] / "app" / "api" / "search_routes.py").read_text(encoding="utf-8")
    frontend_source = (FRONTEND_ROOT / "App.tsx").read_text(encoding="utf-8")

    forbidden = (
        "def detect_intent",
        "def handle_dialog_management",
        "def generate_chitchat_response",
        "def generate_answer",
        "def generate_stream_answer",
        "def _truncate_history",
        "NON_SEARCH_INTENTS",
    )
    combined_backend = "\n".join((search_service_source, application_source, route_source))
    for symbol in forbidden:
        assert symbol not in combined_backend

    assert "extractAdcodeAndPurify" not in frontend_source
