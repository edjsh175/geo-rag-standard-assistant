from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import (
    SCHEMA_VECTOR_DIMENSION,
    Settings,
    settings,
    validate_embedding_dimension_invariants,
)
from app.core.migration_guard import verify_required_database_tables


def test_schema_vector_dimension_constant_is_2048() -> None:
    assert SCHEMA_VECTOR_DIMENSION == 2048
    assert settings.PG_VECTOR_DIMENSION == 2048
    assert settings.OLLAMA_EMBEDDING_DIMENSIONS == 2048


def test_validate_embedding_dimension_invariants_passes_for_current_settings() -> None:
    # Should not raise any error
    validate_embedding_dimension_invariants()


def test_settings_rejects_invalid_pg_vector_dimension() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(PG_VECTOR_DIMENSION=1536)
    assert "PG_VECTOR_DIMENSION must be 2048" in str(exc_info.value)


def test_settings_rejects_invalid_ollama_embedding_dimensions() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(OLLAMA_EMBEDDING_DIMENSIONS=1024)
    assert "OLLAMA_EMBEDDING_DIMENSIONS must be 2048" in str(exc_info.value)


def test_validate_embedding_dimension_invariants_raises_on_mismatch() -> None:
    class DummySettings:
        PG_VECTOR_DIMENSION = 1536
        OLLAMA_EMBEDDING_DIMENSIONS = 2048

    with pytest.raises(ValueError) as exc:
        validate_embedding_dimension_invariants(DummySettings())  # type: ignore[arg-type]
    assert "PG_VECTOR_DIMENSION must be 2048" in str(exc.value)

    class DummySettings2:
        PG_VECTOR_DIMENSION = 2048
        OLLAMA_EMBEDDING_DIMENSIONS = 768

    with pytest.raises(ValueError) as exc:
        validate_embedding_dimension_invariants(DummySettings2())  # type: ignore[arg-type]
    assert "OLLAMA_EMBEDDING_DIMENSIONS must be 2048" in str(exc.value)


@pytest.mark.asyncio
async def test_migration_guard_enforces_dimension_invariants() -> None:
    class DummyInvalidSettings:
        PG_VECTOR_DIMENSION = 1024
        OLLAMA_EMBEDDING_DIMENSIONS = 2048

    import app.core.config as config_module
    original_settings = config_module.settings
    try:
        config_module.settings = DummyInvalidSettings()  # type: ignore[assignment]
        with pytest.raises(ValueError) as exc:
            await verify_required_database_tables(engine=None)
        assert "PG_VECTOR_DIMENSION must be 2048" in str(exc.value)
    finally:
        config_module.settings = original_settings
