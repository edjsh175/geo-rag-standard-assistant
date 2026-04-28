"""
GeoAI API route registration.
"""

from fastapi import APIRouter

from . import auth_routes, document_routes, search_routes, spatial_routes, system_routes

router = APIRouter()

router.include_router(auth_routes.router, prefix="/auth", tags=["认证"])
router.include_router(search_routes.public_router, prefix="/search", tags=["智能检索"])
router.include_router(search_routes.router, prefix="/search", tags=["智能检索"])
router.include_router(spatial_routes.router, prefix="/spatial", tags=["空间分析"])
router.include_router(document_routes.router, prefix="/documents", tags=["文档管理"])
router.include_router(system_routes.router, prefix="/system", tags=["系统管理"])

__all__ = ["router"]
