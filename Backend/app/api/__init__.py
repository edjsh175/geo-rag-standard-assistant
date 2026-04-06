"""
GeoAI API 路由模块
"""

from fastapi import APIRouter

# 创建主路由
router = APIRouter()

# 导入子路由
from . import search_routes, spatial_routes, document_routes, system_routes

# 注册子路由
router.include_router(search_routes.router, prefix="/search", tags=["智能检索"])
router.include_router(spatial_routes.router, prefix="/spatial", tags=["空间分析"])
router.include_router(document_routes.router, prefix="/documents", tags=["文档管理"])
router.include_router(system_routes.router, prefix="/system", tags=["系统管理"])

__all__ = ["router"]