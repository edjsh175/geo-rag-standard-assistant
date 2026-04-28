"""
GeoAI application settings.
Use environment variables in production.
"""

from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "GeoAI 空间规划智能检索与可视化系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:8080",
        "http://localhost:3000",
    ]

    DATABASE_URL: str = "postgresql+asyncpg://geoai:geoai_dev_password@localhost:5432/geoai_db"
    MYSQL_URL: str = "mysql+aiomysql://geoai_mysql:geoai_dev_password@localhost:3306/disaster_knowledge"
    REDIS_URL: str = "redis://localhost:6379/0"

    VECTOR_DB_TYPE: str = "pgvector"
    PG_VECTOR_DIMENSION: int = 2048

    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4-turbo-preview"
    EMBEDDING_MODEL: str = "embedding-3"

    ZHIPU_API_KEY: Optional[str] = None
    ZHIPU_MODEL: str = "glm-4"

    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-chat"

    SIMILARITY_THRESHOLD: float = 0.7
    TOP_K_RESULTS: int = 10

    SPATIAL_SEARCH_RADIUS: float = 5000.0
    COORDINATE_SYSTEM: str = "EPSG:4326"

    MINIO_URL: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "geoai-assets"
    MINIO_SECURE: bool = False
    MINIO_PRESIGNED_UPLOAD_EXPIRES_SECONDS: int = 300
    PUBLIC_API_BASE_URL: Optional[str] = None

    UPLOAD_DIR: Path = Path("uploads")
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024

    SECRET_KEY: str = "dev-only-secret-key-set-SECRET_KEY-in-env"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ADMIN_USERNAME: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None
    ADMIN_PASSWORD_HASH: Optional[str] = None
    AUTH_COOKIE_NAME: str = "geoai_session"
    AUTH_COOKIE_SECURE: bool = True
    AUTH_COOKIE_SAMESITE: str = "lax"
    SYSTEM_API_KEY: Optional[str] = None
    SYSTEM_CLEAR_CACHE_CONFIRM_VALUE: str = "clear-cache"

    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[Path] = Path("logs/geoai.log")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
