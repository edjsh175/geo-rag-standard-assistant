"""Verify API contract/RAG migration on a clean temporary PostgreSQL database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import parse_qsl, unquote, urlparse
from uuid import uuid4

import psycopg2
from psycopg2 import sql


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "Backend" / "migrations" / "20260617_api_contract_tables.sql"
BACKEND_ENV_PATH = REPO_ROOT / "Backend" / ".env"

EXPECTED_SEARCH_LOG_COLUMNS = {
    "id",
    "query",
    "mode",
    "top_k",
    "threshold",
    "filters",
    "results_count",
    "duration_seconds",
    "used_rerank",
    "embedding_available",
    "created_at",
}


def load_database_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url

    if BACKEND_ENV_PATH.exists():
        for line in BACKEND_ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"')

    raise RuntimeError("DATABASE_URL not provided and Backend/.env has no DATABASE_URL")


def parse_postgres_url(database_url: str) -> dict[str, object]:
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    query = dict(parse_qsl(parsed.query))

    conninfo: dict[str, object] = {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "dbname": (parsed.path or "/postgres").lstrip("/") or "postgres",
    }
    if query.get("ssl") and query["ssl"].lower() not in {"disable", "false", "0"}:
        conninfo["sslmode"] = query["ssl"]
    return conninfo


def connect(conninfo: dict[str, object], dbname: str | None = None):
    params = dict(conninfo)
    if dbname is not None:
        params["dbname"] = dbname
    return psycopg2.connect(**params)


def create_clean_database(admin_conn, database_name: str) -> None:
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))


def drop_database(admin_conn, database_name: str) -> None:
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (database_name,),
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def apply_migration(target_conn) -> None:
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    with target_conn.cursor() as cur:
        cur.execute(migration_sql)
    target_conn.commit()


def verify_search_logs(target_conn) -> None:
    with target_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'search_logs'
            """
        )
        columns = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_SEARCH_LOG_COLUMNS - columns
        if missing:
            raise AssertionError(f"search_logs missing columns: {sorted(missing)}")

        cur.execute(
            """
            INSERT INTO search_logs (
                query, mode, top_k, threshold, filters, results_count,
                duration_seconds, used_rerank, embedding_available
            )
            VALUES (
                %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                "DB50/T 1846-2025",
                "hybrid",
                10,
                0.7,
                '{"metadata":{"region":"重庆市"},"spatial":null}',
                2,
                0.123,
                True,
                False,
            ),
        )
        inserted_id = cur.fetchone()[0]
        cur.execute(
            """
            SELECT query, mode, filters->'metadata'->>'region', results_count
            FROM search_logs
            WHERE id = %s
            """,
            (inserted_id,),
        )
        row = cur.fetchone()
        if row != ("DB50/T 1846-2025", "hybrid", "重庆市", 2):
            raise AssertionError(f"Unexpected search_logs row: {row!r}")
    target_conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=load_database_url())
    parser.add_argument("--keep-database", action="store_true")
    args = parser.parse_args()

    conninfo = parse_postgres_url(args.database_url)
    admin_db = "postgres"
    temp_db = f"geoai_migration_verify_{uuid4().hex[:12]}"

    admin_conn = None
    target_conn = None
    try:
        admin_conn = connect(conninfo, dbname=admin_db)
        create_clean_database(admin_conn, temp_db)
        target_conn = connect(conninfo, dbname=temp_db)
        apply_migration(target_conn)
        verify_search_logs(target_conn)
        print(f"migration_ok database={temp_db} migration={MIGRATION_PATH}")
        return 0
    finally:
        if target_conn is not None:
            target_conn.close()
        if admin_conn is not None:
            if args.keep_database:
                print(f"kept_database={temp_db}")
            else:
                drop_database(admin_conn, temp_db)
            admin_conn.close()


if __name__ == "__main__":
    sys.exit(main())
