"""
GeoAI FastAPI backend entrypoint.
"""

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.api import router as api_router
from app.core.config import settings
from app.core.database import db_manager
from app.core.llm_config import llm_config  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    postgres_status = _connection_status("postgres_initialized")
    mysql_status = _connection_status("mysql_initialized")
    redis_status = _connection_status("redis_initialized")

    return {
        "status": "healthy" if postgres_status == "connected" else "degraded",
        "databases": {
            "postgres": postgres_status,
            "mysql": mysql_status,
            "redis": redis_status,
        },
        "timestamp": datetime.now().isoformat(),
        "message": (
            "PostgreSQL is required for vector search functionality"
            if postgres_status == "disconnected"
            else "All core systems operational"
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
