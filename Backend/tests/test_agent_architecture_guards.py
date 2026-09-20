from __future__ import annotations

from pathlib import Path


AGENT_ROOT = Path(__file__).parents[1] / "app" / "services" / "agent"


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
