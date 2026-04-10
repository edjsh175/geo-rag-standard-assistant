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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    print("正在初始化数据库连接...")

    # 初始化状态跟踪
    app.state.postgres_initialized = False
    app.state.mysql_initialized = False
    app.state.redis_initialized = False

    # 1. 初始化 PostgreSQL (核心组件)
    try:
        await db_manager._init_postgres()
        app.state.postgres_initialized = True
        print("[OK] PostgreSQL 连接初始化成功")
    except Exception as e:
        print(f"[ERROR] PostgreSQL 连接初始化失败: {e}")
        print("警告: 向量搜索功能将不可用，请检查以下配置:")
        print("1. 确保 PostgreSQL 服务正在运行")
        print("2. 检查 .env 中的 DATABASE_URL 配置")
        print("3. 确认数据库 'geoai_db' 已创建")
        print("4. 确保 PostgreSQL 已安装 pgvector 和 postgis 扩展")

    # 2. 初始化 MySQL (元数据存储)
    try:
        await db_manager._init_mysql()
        app.state.mysql_initialized = True
        print("[OK] MySQL 连接初始化成功")
    except Exception as e:
        print(f"[WARNING] MySQL 连接初始化失败，元数据功能将受限: {e}")

    # 3. 初始化 Redis (缓存，非核心组件)
    try:
        await db_manager._init_redis()
        app.state.redis_initialized = True
        print("[OK] Redis 连接初始化成功")
    except Exception as e:
        print(f"[WARNING] Redis 连接初始化失败，暂时禁用缓存功能: {e}")
        # Redis 是非核心组件，不影响主流程
        app.state.redis_initialized = False

    # 测试连接状态
    try:
        await db_manager.test_connections()
    except Exception as e:
        print(f"⚠️ 连接测试过程中出现异常: {e}")

    # 大模型配置已在导入时初始化
    print("大模型配置已加载")

    yield

    # 关闭时清理
    print("正在关闭数据库连接...")
    await db_manager.close()
    print("数据库连接已关闭")


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