from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals" / "geoai_agent_36_tasks.json"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _config() -> dict[str, str]:
    values: dict[str, str] = {}
    values.update(_load_env_file(ROOT / ".env"))
    values.update(_load_env_file(ROOT / "Backend" / ".env"))
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_status(url: str, timeout: float = 1.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError):
        return None


def _database_target(database_url: str | None) -> tuple[str, int] | None:
    if not database_url:
        return None
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 5432


def run_preflight(
    *,
    backend_url: str = "http://127.0.0.1:8000",
    frontend_url: str = "http://127.0.0.1:3000",
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail})

    try:
        tasks = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest_ok = (
            isinstance(tasks, list)
            and len(tasks) == 36
            and len({row.get("id") for row in tasks}) == 36
        )
    except Exception:
        manifest_ok = False
    add("36-task manifest", manifest_ok, "expected exactly 36 unique task ids")

    config = _config()
    database_url = config.get("DATABASE_URL") or config.get("GEOAI_DATABASE_URL")
    mysql_url = config.get("MYSQL_URL") or config.get("GEOAI_MYSQL_URL")
    redis_url = config.get("REDIS_URL") or config.get("GEOAI_REDIS_URL")
    add("PostgreSQL configuration", bool(database_url), "DATABASE_URL/GEOAI_DATABASE_URL must be configured")
    add("MySQL configuration", bool(mysql_url), "MYSQL_URL/GEOAI_MYSQL_URL must be configured")

    admin_username = config.get("ADMIN_USERNAME")
    admin_password_ready = bool(config.get("ADMIN_PASSWORD_HASH") or config.get("ADMIN_PASSWORD"))
    secret_key = config.get("SECRET_KEY")
    add(
        "admin auth configuration",
        bool(admin_username and admin_password_ready and secret_key),
        "ADMIN_USERNAME, SECRET_KEY, and ADMIN_PASSWORD_HASH or ADMIN_PASSWORD are required at backend startup",
    )

    provider = (config.get("LLM_PROVIDER") or "deepseek").lower()
    if provider == "deepseek":
        llm_ready = bool(config.get("DEEPSEEK_API_KEY") or config.get("GEOAI_DEEPSEEK_API_KEY"))
        llm_detail = "DeepSeek provider requires DEEPSEEK_API_KEY/GEOAI_DEEPSEEK_API_KEY"
    elif provider == "openai":
        llm_ready = bool(config.get("OPENAI_API_KEY") or config.get("GEOAI_OPENAI_API_KEY"))
        llm_detail = "OpenAI provider requires OPENAI_API_KEY/GEOAI_OPENAI_API_KEY"
    else:
        llm_ready = bool(config.get("ZHIPU_API_KEY"))
        llm_detail = f"provider {provider} requires its configured API credential"
    add("LLM credential", llm_ready, llm_detail)

    target = _database_target(database_url)
    if target is None:
        add("PostgreSQL reachable", False, "database target unavailable because DATABASE_URL is missing")
    else:
        host, port = target
        add("PostgreSQL reachable", _tcp_open(host, port), f"TCP {host}:{port}")

    mysql_target = _database_target(mysql_url)
    if mysql_target is None:
        add("MySQL reachable", False, "database target unavailable because MYSQL_URL is missing")
    else:
        host, port = mysql_target
        add("MySQL reachable", _tcp_open(host, port), f"TCP {host}:{port}")

    redis_target = _database_target(redis_url)
    if redis_target is None:
        add("Redis reachable", False, "REDIS_URL/GEOAI_REDIS_URL is not configured", required=False)
    else:
        host, port = redis_target
        add("Redis reachable", _tcp_open(host, port), f"TCP {host}:{port}", required=False)

    backend_status = _http_status(f"{backend_url.rstrip('/')}/health")
    add("backend health", backend_status == 200, f"GET /health returned {backend_status!r}")

    frontend_status = _http_status(frontend_url)
    add("frontend reachable", frontend_status is not None and frontend_status < 500, f"GET frontend returned {frontend_status!r}")

    chrome_candidates = [
        shutil.which("chrome"),
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    browser_ready = any(candidate and Path(candidate).exists() for candidate in chrome_candidates)
    add("browser executable", browser_ready, "Chrome or Edge required for browser GIS E2E")

    add("npm", shutil.which("npm") is not None, "npm is required to launch/build the frontend")
    add("docker", shutil.which("docker") is not None, "optional when dependencies are already running", required=False)

    blockers = [check["name"] for check in checks if check["required"] and not check["ok"]]
    return {"ready": not blockers, "blockers": blockers, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight the real GeoAI 36-task E2E environment without exposing secrets.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    result = run_preflight(backend_url=args.backend_url, frontend_url=args.frontend_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()
