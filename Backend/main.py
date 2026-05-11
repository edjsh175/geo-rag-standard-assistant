"""
GeoAI FastAPI backend entrypoint.
"""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.api import router as api_router
from app.core.auth import validate_admin_auth_configuration
from app.core.config import settings
from app.core.database import db_manager
from app.core.llm_config import llm_config  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_admin_auth_configuration()
    logger.info("Admin authentication configuration loaded.")

    logger.info("Initializing database connections...")
    await db_manager.initialize()

    app.state.postgres_initialized = db_manager.postgres_engine is not None
    app.state.mysql_initialized = db_manager.mysql_engine is not None
    app.state.redis_initialized = db_manager.redis_client is not None

    if not app.state.postgres_initialized:
        logger.error("PostgreSQL initialization failed. Vector search will be unavailable.")

    logger.info("LLM configuration loaded.")

    yield

    logger.info("Closing database connections...")
    await db_manager.close()
    logger.info("Database connections closed.")


app = FastAPI(
    title="GeoAI API",
    description="Backend API for GeoAI spatial search and visualization.",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


def _connection_status(flag_name: str) -> str:
    return "connected" if getattr(app.state, flag_name, False) else "disconnected"


async def _check_database_dependencies() -> dict[str, str]:
    database_status = {
        "postgres": "disconnected",
        "mysql": "disconnected",
        "redis": "disconnected",
    }

    try:
        await db_manager._test_engine("PostgreSQL", db_manager.postgres_engine)
        database_status["postgres"] = "connected"
    except Exception:
        database_status["postgres"] = "disconnected"

    try:
        await db_manager._test_engine("MySQL", db_manager.mysql_engine)
        database_status["mysql"] = "connected"
    except Exception:
        database_status["mysql"] = "disconnected"

    try:
        if db_manager.redis_client:
            await db_manager.redis_client.ping()
            database_status["redis"] = "connected"
    except Exception:
        database_status["redis"] = "disconnected"

    return database_status


@app.get("/")
async def root():
    postgres_status = _connection_status("postgres_initialized")
    mysql_status = _connection_status("mysql_initialized")
    redis_status = _connection_status("redis_initialized")

    return {
        "service": "GeoAI API",
        "version": settings.APP_VERSION,
        "status": "running",
        "database": "connected" if postgres_status == "connected" else "disconnected",
        "databases": {
            "postgres": postgres_status,
            "mysql": mysql_status,
            "redis": redis_status,
        },
        "docs": "/api/docs" if settings.DEBUG else None,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health")
async def health_check():
    database_status = await _check_database_dependencies()
    required_healthy = (
        database_status["postgres"] == "connected"
        and database_status["mysql"] == "connected"
    )

    payload = {
        "status": "healthy" if required_healthy else "degraded",
        "databases": database_status,
        "timestamp": datetime.now().isoformat(),
        "message": (
            "All required systems operational"
            if required_healthy
            else "PostgreSQL and MySQL are required for search and metadata functionality"
        ),
    }

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if required_healthy
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=payload,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
