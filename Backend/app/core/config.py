"""
GeoAI 应用配置
基于 Pydantic Settings 管理环境变量
"""

from pydantic_settings import BaseSettings
from typing import List, Optional
from pathlib import Path


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "GeoAI 空间规划智能检索与可视化系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS 配置
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",  # Vite 默认端口
        "http://localhost:8080",
        "http://localhost:3000",
    ]

    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/geoai_db"
    MYSQL_URL: str = "mysql+aiomysql://root:password@localhost:3306/geoai_metadata"
    REDIS_URL: str = "redis://localhost:6379/0"

    # 向量数据库配置
    VECTOR_DB_TYPE: str = "pgvector"  # 支持: pgvector, chromadb
    PG_VECTOR_DIMENSION: int = 2048  # 智谱 embedding-3 维度

    # 大模型配置
    LLM_PROVIDER: str = "openai"  # 支持: openai, zhipu, deepseek
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4-turbo-preview"
    EMBEDDING_MODEL: str = "embedding-3"  # 智谱 embedding-3 模型

    # 智谱AI配置
    ZHIPU_API_KEY: Optional[str] = None
    ZHIPU_MODEL: str = "glm-4"

    # DeepSeek配置
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # 检索配置
    SIMILARITY_THRESHOLD: float = 0.7
    TOP_K_RESULTS: int = 10

    # 空间检索配置
    SPATIAL_SEARCH_RADIUS: float = 5000.0  # 默认搜索半径5公里
    COORDINATE_SYSTEM: str = "EPSG:4326"  # WGS84坐标系

    # 文件存储配置 (MinIO)
    MINIO_URL: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "geoai-assets"
    
    # 遗留的本地存储上传项 (临时兼容)
    UPLOAD_DIR: Path = Path("uploads")
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB

    # 安全配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[Path] = Path("logs/geoai.log")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# 全局配置实例
settings = Settings()