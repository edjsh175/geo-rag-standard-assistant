from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "preflight_geoai_agent_e2e.py"
SPEC = importlib.util.spec_from_file_location("geoai_e2e_preflight", SCRIPT)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_database_target_accepts_asyncpg_url() -> None:
    assert preflight._database_target("postgresql+asyncpg://user:pass@db.local:6543/geoai") == ("db.local", 6543)


def test_database_target_defaults_to_postgres_port() -> None:
    assert preflight._database_target("postgresql://user:pass@127.0.0.1/geoai") == ("127.0.0.1", 5432)


def test_database_target_rejects_missing_url() -> None:
    assert preflight._database_target(None) is None
