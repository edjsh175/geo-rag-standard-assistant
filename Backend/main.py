"""
GeoAI 空间规划智能检索与可视化系统 - FastAPI 后端入口
基于 requirement V1.0 (2026年3月) 设计
"""

import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import router as api_router
from app.core.config import settings
from app.core.database import db_manager
from app.core.llm_config import llm_config

import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("正在初始化数据库连接...")

    # 使用 db_manager 统一初始化的锁机制
    await db_manager.initialize()
    
    app.state.postgres_initialized = db_manager.postgres_engine is not None
    app.state.mysql_initialized = db_manager.mysql_engine is not None
    app.state.redis_initialized = db_manager.redis_client is not None
    
    if not app.state.postgres_initialized:
        logger.error("PostgreSQL 连接初始化失败。向量搜索功能将会不可用。")

    logger.info("大模型配置已加载")

    yield

    # 关闭时清理
    logger.info("正在关闭数据库连接...")
    await db_manager.close()
    logger.info("数据库连接已关闭")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="GeoAI 空间规划智能检索与可视化系统 API",
    description="基于大模型和空间数据库的智能检索与可视化后端服务",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 API 路由
app.include_router(api_router, prefix="/api")

# 调试：打印所有路由
print("=== 注册的路由 ===")
for route in app.routes:
    if hasattr(route, "methods") and hasattr(route, "path"):
        print(f"{route.path} [{', '.join(route.methods)}]")
print("=================")

@app.get("/")
async def root():
    """根端点，返回服务状态"""
    # 获取各个数据库的初始化状态
    postgres_status = "connected" if hasattr(app.state, "postgres_initialized") and app.state.postgres_initialized else "disconnected"
    mysql_status = "connected" if hasattr(app.state, "mysql_initialized") and app.state.mysql_initialized else "disconnected"
    redis_status = "connected" if hasattr(app.state, "redis_initialized") and app.state.redis_initialized else "disconnected"

    # 总体状态：如果 PostgreSQL 连接成功则认为数据库功能可用
    overall_db_status = "connected" if postgres_status == "connected" else "disconnected"

    return {
        "service": "GeoAI 空间规划智能检索与可视化系统 API",
        "version": "1.0.0",
        "status": "running",
        "database": overall_db_status,
        "databases": {
            "postgres": postgres_status,
            "mysql": mysql_status,
            "redis": redis_status
        },
        "docs": "/api/docs",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    # 获取各个数据库的初始化状态
    postgres_status = "connected" if hasattr(app.state, "postgres_initialized") and app.state.postgres_initialized else "disconnected"
    mysql_status = "connected" if hasattr(app.state, "mysql_initialized") and app.state.mysql_initialized else "disconnected"
    redis_status = "connected" if hasattr(app.state, "redis_initialized") and app.state.redis_initialized else "disconnected"

    # 总体健康状态：如果 PostgreSQL 连接成功则认为服务健康
    overall_status = "healthy" if postgres_status == "connected" else "degraded"

    return {
        "status": overall_status,
        "databases": {
            "postgres": postgres_status,
            "mysql": mysql_status,
            "redis": redis_status
        },
        "timestamp": datetime.now().isoformat(),
        "message": "PostgreSQL is required for vector search functionality" if postgres_status == "disconnected" else "All core systems operational"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )