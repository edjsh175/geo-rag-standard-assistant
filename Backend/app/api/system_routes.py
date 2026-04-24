"""
System management API routes.
"""

from datetime import datetime
import os
import platform
import subprocess
import sys

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import db_manager
from app.core.security import (
    require_clear_cache_confirmation,
    require_system_api_key,
)

router = APIRouter(dependencies=[Depends(require_system_api_key)])


class SystemInfo(BaseModel):
    app_name: str
    app_version: str
    python_version: str
    platform: str
    hostname: str
    cpu_count: int
    memory_total: str
    memory_used: str


class DatabaseStatus(BaseModel):
    postgresql: str
    mysql: str
    redis: str


class HealthStatus(BaseModel):
    status: str
    timestamp: str
    system: SystemInfo
    database: DatabaseStatus


@router.get("/info", response_model=SystemInfo)
async def get_system_info() -> SystemInfo:
    try:
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024 ** 3)
        memory_used_gb = memory.used / (1024 ** 3)

        return SystemInfo(
            app_name=settings.APP_NAME,
            app_version=settings.APP_VERSION,
            python_version=platform.python_version(),
            platform=platform.platform(),
            hostname=platform.node(),
            cpu_count=psutil.cpu_count() or 0,
            memory_total=f"{memory_total_gb:.2f} GB",
            memory_used=f"{memory_used_gb:.2f} GB",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch system info: {exc}",
        ) from exc


@router.get("/health", response_model=HealthStatus)
async def get_health_status() -> HealthStatus:
    try:
        db_status = {
            "postgresql": "unknown",
            "mysql": "unknown",
            "redis": "unknown",
        }

        try:
            if db_manager.postgres_engine:
                async with db_manager.postgres_engine.begin() as _:
                    db_status["postgresql"] = "healthy"
        except Exception:
            db_status["postgresql"] = "unhealthy"

        try:
            if db_manager.mysql_engine:
                async with db_manager.mysql_engine.begin() as _:
                    db_status["mysql"] = "healthy"
        except Exception:
            db_status["mysql"] = "unhealthy"

        try:
            if db_manager.redis_client:
                await db_manager.redis_client.ping()
                db_status["redis"] = "healthy"
        except Exception:
            db_status["redis"] = "unhealthy"

        overall_status = "healthy" if all(value == "healthy" for value in db_status.values()) else "degraded"

        return HealthStatus(
            status=overall_status,
            timestamp=datetime.now().isoformat(),
            system=await get_system_info(),
            database=DatabaseStatus(**db_status),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch health status: {exc}",
        ) from exc


@router.get("/config")
async def get_configuration():
    try:
        config_dict = settings.model_dump()
        sensitive_fields = {"api_key", "secret", "password", "token"}

        filtered_config = {}
        for key, value in config_dict.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields):
                filtered_config[key] = "***HIDDEN***"
            else:
                filtered_config[key] = value

        return filtered_config
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch configuration: {exc}",
        ) from exc


@router.get("/logs")
async def get_logs(
    lines: int = Query(default=100, ge=1, le=1000),
    level: str = Query(default="INFO"),
):
    try:
        log_file = settings.LOG_FILE
        if not log_file or not log_file.exists():
            return {"logs": [], "message": "Log file does not exist."}

        with open(log_file, "r", encoding="utf-8") as log_handle:
            all_lines = log_handle.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        filtered_lines = [
            line for line in recent_lines if level == "ALL" or level in line
        ]

        return {
            "total_lines": len(all_lines),
            "filtered_lines": len(filtered_lines),
            "logs": filtered_lines,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch logs: {exc}",
        ) from exc


@router.post("/clear-cache", dependencies=[Depends(require_clear_cache_confirmation)])
async def clear_cache():
    try:
        if db_manager.redis_client:
            await db_manager.redis_client.flushdb()

        return {
            "message": "Cache cleared successfully.",
            "redis": "flushed" if db_manager.redis_client else "not-configured",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {exc}",
        ) from exc


@router.get("/metrics")
async def get_metrics():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net_io = psutil.net_io_counters()

        return {
            "cpu": {
                "percent": cpu_percent,
                "cores": psutil.cpu_count(),
                "frequency": psutil.cpu_freq().current if psutil.cpu_freq() else None,
            },
            "memory": {
                "percent": memory.percent,
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
            },
            "disk": {
                "percent": disk.percent,
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
            },
            "network": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch metrics: {exc}",
        ) from exc


@router.post("/restart")
async def restart_service():
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restart is disabled outside DEBUG mode.",
        )

    try:
        python = sys.executable
        script = sys.argv[0]

        subprocess.Popen([python, script])
        os._exit(0)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restart service: {exc}",
        ) from exc
