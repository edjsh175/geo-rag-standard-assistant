from __future__ import annotations

import json
import re
from pathlib import Path

import psycopg2
import pymysql


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ENV = ROOT / "Backend" / ".env"
DEPLOY_DOC = ROOT / "docs" / "DEPLOY.md"
OUTPUT_DIR = ROOT.parent / "服务器" / "建表"
MYSQL_DATA_SQL = OUTPUT_DIR / "geoai_metadata.sql"
MYSQL_FULL_SQL = OUTPUT_DIR / "geoai_metadata.full.sql"
POSTGRES_SQL = OUTPUT_DIR / "policy_chunks.pg.sql"
IMPORT_README = OUTPUT_DIR / "README-导入说明.md"
SUMMARY_JSON = OUTPUT_DIR / "export_summary.json"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def postgres_dsn_from_asyncpg(url: str) -> str:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    dsn = dsn.replace("?ssl=disable", "")
    dsn = dsn.replace("?sslmode=disable", "")
    if "?" in dsn:
        dsn = dsn.split("?", 1)[0]
    return dsn


def mysql_connect_args(mysql_url: str) -> dict[str, object]:
    match = re.match(
        r"^mysql\+aiomysql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<db>[^?]+)",
        mysql_url,
    )
    if not match:
        raise ValueError(f"Unsupported MYSQL_URL: {mysql_url}")
    groups = match.groupdict()
    return {
        "host": groups["host"],
        "port": int(groups["port"]),
        "user": groups["user"],
        "password": groups["password"],
        "database": groups["db"],
        "charset": "utf8mb4",
    }


def fetch_postgres_table_spec(conn) -> dict[str, object]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                a.attnum,
                a.attname,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS type_name,
                a.attnotnull,
                pg_get_expr(d.adbin, d.adrelid) AS default_expr
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE n.nspname = 'public'
              AND c.relname = 'policy_chunks'
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
        columns = cur.fetchall()

        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'public.policy_chunks'::regclass
            ORDER BY contype DESC, conname
            """
        )
        constraints = cur.fetchall()

        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'policy_chunks'
            ORDER BY indexname
            """
        )
        indexes = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM public.policy_chunks")
        row_count = cur.fetchone()[0]

    return {
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "row_count": row_count,
    }


def render_postgres_create_table(spec: dict[str, object]) -> str:
    lines: list[str] = []
    for _, name, type_name, attnotnull, default_expr in spec["columns"]:
        rendered_type = type_name
        if (
            name == "id"
            and type_name == "bigint"
            and isinstance(default_expr, str)
            and default_expr.startswith("nextval(")
        ):
            rendered_type = "bigserial"
            default_expr = None

        col = f"    {name} {rendered_type}"
        if default_expr:
            col += f" DEFAULT {default_expr}"
        if attnotnull:
            col += " NOT NULL"
        lines.append(col)

    for conname, condef in spec["constraints"]:
        lines.append(f"    CONSTRAINT {conname} {condef}")

    return "CREATE TABLE public.policy_chunks (\n" + ",\n".join(lines) + "\n);\n"


def export_postgres_sql(conn, spec: dict[str, object], output_path: Path) -> None:
    columns = [row[1] for row in spec["columns"]]
    col_list = ", ".join(columns)

    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("-- Exported from local PostgreSQL table public.policy_chunks\n")
        f.write("-- Restore with: psql -U postgres -d geoai_db -f policy_chunks.pg.sql\n\n")
        f.write("BEGIN;\n")
        f.write("DROP TABLE IF EXISTS public.policy_chunks;\n")
        f.write(render_postgres_create_table(spec))
        f.write("COMMIT;\n\n")
        f.write(f"COPY public.policy_chunks ({col_list}) FROM stdin;\n")

        with conn.cursor() as cur:
            copy_sql = (
                f"COPY (SELECT {col_list} FROM public.policy_chunks ORDER BY id) "
                "TO STDOUT WITH (FORMAT text)"
            )
            cur.copy_expert(copy_sql, f)

        f.write("\\.\n\n")

        # Skip primary key index because it is covered by the table constraint.
        for indexname, indexdef in spec["indexes"]:
            if indexname == "policy_chunks_pkey":
                continue
            f.write(indexdef + ";\n")

        if any(row[1] == "id" for row in spec["columns"]):
            f.write(
                "\nSELECT pg_catalog.setval('public.policy_chunks_id_seq', "
                "(SELECT COALESCE(MAX(id), 1) FROM public.policy_chunks), true);\n"
            )


def build_mysql_full_sql(create_table_sql: str, insert_sql: str, output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("-- Full MySQL import for disaster_knowledge.geoai_metadata\n")
        f.write("-- Restore with: mysql -uroot -p disaster_knowledge < geoai_metadata.full.sql\n\n")
        f.write("SET NAMES utf8mb4;\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")
        f.write("DROP TABLE IF EXISTS `geoai_metadata`;\n")
        f.write(create_table_sql.rstrip() + ";\n\n")
        f.write(insert_sql.rstrip() + "\n\n")
        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")


def build_import_readme(
    postgres_spec: dict[str, object],
    deploy_doc: str,
    output_path: Path,
) -> None:
    actual_columns = [row[1] for row in postgres_spec["columns"]]
    actual_indexes = [row[0] for row in postgres_spec["indexes"]]
    deploy_has_embedding_index = "idx_policy_chunks_embedding" in deploy_doc
    deploy_has_standard_code_index = "idx_policy_chunks_standard_code" in deploy_doc

    diff_lines = []
    if "document_name" in actual_columns and actual_columns.index("document_name") < actual_columns.index("keyword"):
        diff_lines.append("- Actual local table column order differs from DEPLOY.md. The export preserves local order.")
    if "idx_policy_chunks_standard_code" not in actual_indexes and deploy_has_standard_code_index:
        diff_lines.append("- Local table does not currently have `idx_policy_chunks_standard_code`, although DEPLOY.md recommends it.")
    if "idx_policy_chunks_embedding" not in actual_indexes and deploy_has_embedding_index:
        diff_lines.append("- Local table does not currently have `idx_policy_chunks_embedding`, although DEPLOY.md recommends it.")

    content = [
        "# 服务器导入说明",
        "",
        "本目录包含从本机导出的部署交付物：",
        "",
        "- `policy_chunks.pg.sql`: PostgreSQL `public.policy_chunks` 的建表 + 数据导出",
        "- `geoai_metadata.sql`: 原始 MySQL 数据插入文件",
        "- `geoai_metadata.full.sql`: 可直接导入的 MySQL 完整脚本",
        "",
        "## PostgreSQL 导入顺序",
        "",
        "1. 创建用户、数据库和扩展：",
        "",
        "```bash",
        "sudo -u postgres psql <<'SQL'",
        "CREATE USER geoai WITH PASSWORD 'replace_with_strong_password';",
        "CREATE DATABASE geoai_db OWNER geoai;",
        "\\c geoai_db",
        "CREATE EXTENSION IF NOT EXISTS vector;",
        "CREATE EXTENSION IF NOT EXISTS postgis;",
        "GRANT ALL PRIVILEGES ON DATABASE geoai_db TO geoai;",
        "GRANT USAGE, CREATE ON SCHEMA public TO geoai;",
        "SQL",
        "```",
        "",
        "2. 上传并导入 `policy_chunks.pg.sql`：",
        "",
        "```bash",
        "mkdir -p /srv/geoai/db",
        "psql -U postgres -d geoai_db -f /srv/geoai/db/policy_chunks.pg.sql",
        "```",
        "",
        "## MySQL 导入顺序",
        "",
        "1. 创建数据库和应用用户：",
        "",
        "```bash",
        "mysql -uroot -p <<'SQL'",
        "CREATE DATABASE IF NOT EXISTS disaster_knowledge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "CREATE USER IF NOT EXISTS 'geoai_mysql'@'localhost' IDENTIFIED BY 'replace_with_strong_password';",
        "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON disaster_knowledge.* TO 'geoai_mysql'@'localhost';",
        "FLUSH PRIVILEGES;",
        "SQL",
        "```",
        "",
        "2. 导入完整脚本：",
        "",
        "```bash",
        "mysql -uroot -p disaster_knowledge < /srv/geoai/db/geoai_metadata.full.sql",
        "```",
        "",
        "## 与 DEPLOY.md 的差异",
        "",
    ]

    if diff_lines:
        content.extend(diff_lines)
    else:
        content.append("- No material schema differences were detected during local export.")

    content.extend(
        [
            "",
            "## 上传命令",
            "",
            "拿到 SSH 凭据后，可从本机执行：",
            "",
            "```bash",
            "scp policy_chunks.pg.sql geoai_metadata.full.sql README-导入说明.md user@8.156.85.7:/srv/geoai/db/",
            "```",
            "",
            "如服务器目录不是 `/srv/geoai/db`，按实际目录调整。",
            "",
        ]
    )

    output_path.write_text("\n".join(content), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    env = parse_env_file(BACKEND_ENV)
    postgres_dsn = postgres_dsn_from_asyncpg(env["DATABASE_URL"])
    mysql_args = mysql_connect_args(env["MYSQL_URL"])

    pg_conn = psycopg2.connect(postgres_dsn)
    try:
        postgres_spec = fetch_postgres_table_spec(pg_conn)
        export_postgres_sql(pg_conn, postgres_spec, POSTGRES_SQL)
    finally:
        pg_conn.close()

    mysql_conn = pymysql.connect(**mysql_args)
    try:
        with mysql_conn.cursor() as cur:
            cur.execute("SHOW CREATE TABLE geoai_metadata")
            create_table_sql = cur.fetchone()[1]
    finally:
        mysql_conn.close()

    insert_sql = MYSQL_DATA_SQL.read_text(encoding="utf-8")
    build_mysql_full_sql(create_table_sql, insert_sql, MYSQL_FULL_SQL)

    deploy_doc = DEPLOY_DOC.read_text(encoding="utf-8")
    build_import_readme(postgres_spec, deploy_doc, IMPORT_README)

    summary = {
        "postgres_row_count": postgres_spec["row_count"],
        "postgres_columns": [row[1] for row in postgres_spec["columns"]],
        "postgres_indexes": [row[0] for row in postgres_spec["indexes"]],
        "mysql_full_sql": str(MYSQL_FULL_SQL),
        "postgres_sql": str(POSTGRES_SQL),
        "import_readme": str(IMPORT_README),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
