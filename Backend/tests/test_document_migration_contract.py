from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_document_lifecycle_migration_indexes_2048_vectors_with_halfvec_expression() -> None:
    migration = (ROOT / "migrations" / "20260618_document_lifecycle.sql").read_text(encoding="utf-8")

    assert "embedding vector(2048)" in migration
    assert "CAST(embedding AS halfvec(2048))" in migration
    assert "embedding vector_cosine_ops" not in migration


def test_uploaded_document_vector_search_matches_halfvec_index_expression() -> None:
    source = (ROOT / "app" / "services" / "search_service.py").read_text(encoding="utf-8")

    assert "CAST(c.embedding AS halfvec(2048)) <=> CAST(:embedding_str AS halfvec(2048))" in source


def test_non_docker_docs_are_the_primary_runtime_contract() -> None:
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    deploy = (ROOT.parent / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    root_env_example = (ROOT.parent / ".env.example").read_text(encoding="utf-8")

    assert "### Non-Docker local development" in readme
    assert "### Optional Docker Compose" in readme
    assert readme.index("### Non-Docker local development") < readme.index("### Optional Docker Compose")
    assert "Docker Compose is optional" in root_env_example.splitlines()[0]
    assert "docker-compose.yml 中的 PostgreSQL 服务会从" not in deploy
    assert "Docker 对当前项目是可选项" in deploy
