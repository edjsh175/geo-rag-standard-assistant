"""
系统管理 API 路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import platform
import psutil
import os

from app.core.config import settings
from app.core.database import db_manager

router = APIRouter()


class SystemInfo(BaseModel):
    """系统信息响应"""
    app_name: str
    app_version: str
    python_version: str
    platform: str
    hostname: str
    cpu_count: int
    memory_total: str
    memory_used: str


class DatabaseStatus(BaseModel):
    """数据库状态响应"""
    postgresql: str
    mysql: str
    redis: str


class HealthStatus(BaseModel):
    """健康状态响应"""
    status: str
    timestamp: str
    system: SystemInfo
    database: DatabaseStatus


@router.get("/info", response_model=SystemInfo)
async def get_system_info():
    """
    获取系统信息

    Returns:
        系统信息
    """
    try:
        # 获取内存使用情况
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024**3)
        memory_used_gb = memory.used / (1024**3)

        return SystemInfo(
            app_name=settings.APP_NAME,
            app_version=settings.APP_VERSION,
            python_version=platform.python_version(),
            platform=platform.platform(),
            hostname=platform.node(),
            cpu_count=psutil.cpu_count(),
            memory_total=f"{memory_total_gb:.2f} GB",
            memory_used=f"{memory_used_gb:.2f} GB"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取系统信息失败: {str(e)}")


@router.get("/health", response_model=HealthStatus)
async def get_health_status():
    """
    获取系统健康状态

    Returns:
        健康状态信息
    """
    try:
        import datetime

        # 检查数据库连接状态
        db_status = {
            "postgresql": "unknown",
            "mysql": "unknown",
            "redis": "unknown"
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

        # 获取系统信息
        system_info = await get_system_info()

        # 总体状态
        all_healthy = all(status == "healthy" for status in db_status.values())
        overall_status = "healthy" if all_healthy else "degraded"

        return HealthStatus(
            status=overall_status,
            timestamp=datetime.datetime.now().isoformat(),
            system=system_info,
            database=DatabaseStatus(**db_status)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取健康状态失败: {str(e)}")


@router.get("/config")
async def get_configuration():
    """
    获取应用配置（不包含敏感信息）

    Returns:
        应用配置信息
    """
    try:
        # 过滤掉敏感信息
        config_dict = settings.dict()
        sensitive_fields = ["api_key", "secret", "password", "token"]

        filtered_config = {}
        for key, value in config_dict.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields):
                filtered_config[key] = "***HIDDEN***"
            else:
                filtered_config[key] = value

        return filtered_config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/logs")
async def get_logs(
    lines: int = 100,
    level: str = "INFO"
):
    """
    获取应用日志

    Args:
        lines: 返回的行数
        level: 日志级别过滤

    Returns:
        日志内容
    """
    try:
        log_file = settings.LOG_FILE
        if not log_file or not log_file.exists():
            return {"logs": [], "message": "日志文件不存在"}

        # 读取日志文件最后 N 行
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        # 按级别过滤
        filtered_lines = [
            line for line in recent_lines
            if level in line or level == "ALL"
        ]

        return {
            "total_lines": len(all_lines),
            "filtered_lines": len(filtered_lines),
            "logs": filtered_lines
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取日志失败: {str(e)}")


@router.post("/clear-cache")
async def clear_cache():
    """
    清除系统缓存

    Returns:
        清除结果
    """
    try:
        # TODO: 实现缓存清除逻辑
        # 清除 Redis 缓存
        if db_manager.redis_client:
            await db_manager.redis_client.flushdb()

        return {
            "message": "缓存清除成功",
            "redis": "flushed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@router.get("/metrics")
async def get_metrics():
    """
    获取系统指标

    Returns:
        系统指标数据
    """
    try:
        # CPU 使用率
        cpu_percent = psutil.cpu_percent(interval=1)

        # 内存使用率
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # 磁盘使用率
        disk = psutil.disk_usage("/")
        disk_percent = disk.percent

        # 网络IO
        net_io = psutil.net_io_counters()

        return {
            "cpu": {
                "percent": cpu_percent,
                "cores": psutil.cpu_count(),
                "frequency": psutil.cpu_freq().current if psutil.cpu_freq() else None
            },
            "memory": {
                "percent": memory_percent,
                "total": memory.total,
                "available": memory.available,
                "used": memory.used
            },
            "disk": {
                "percent": disk_percent,
                "total": disk.total,
                "used": disk.used,
                "free": disk.free
            },
            "network": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取指标失败: {str(e)}")


@router.post("/restart")
async def restart_service():
    """
    重启服务（需要管理员权限）

    Returns:
        重启结果
    """
    # 注意：这是一个危险操作，实际项目中应该需要身份验证
    try:
        import sys
        import subprocess

        # 获取当前 Python 解释器和脚本路径
        python = sys.executable
        script = sys.argv[0]

        # 在新进程中启动应用
        subprocess.Popen([python, script])

        # 退出当前进程
        os._exit(0)

        return {"message": "服务重启中..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重启服务失败: {str(e)}")