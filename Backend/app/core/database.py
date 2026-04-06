"""
数据库连接管理器
支持 PostgreSQL (pgvector + PostGIS) 和 MySQL
"""

import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from redis.asyncio import Redis

from .config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        self.postgres_engine: Optional[AsyncEngine] = None
        self.postgres_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

        self.mysql_engine: Optional[AsyncEngine] = None
        self.mysql_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

        self.redis_client: Optional[Redis] = None

    async def initialize(self):
        """初始化所有数据库连接，容忍部分失败"""
        # 初始化 PostgreSQL (核心组件)
        try:
            await self._init_postgres()
            logger.info("PostgreSQL 初始化成功")
        except Exception as e:
            logger.error(f"PostgreSQL 初始化失败: {e}")
            # 继续初始化其他组件，但 PostgreSQL 不可用将影响核心功能

        # 初始化 MySQL (元数据存储)
        try:
            await self._init_mysql()
            logger.info("MySQL 初始化成功")
        except Exception as e:
            logger.warning(f"MySQL 初始化失败，元数据功能将受限: {e}")

        # 初始化 Redis (缓存，非核心组件)
        try:
            await self._init_redis()
            logger.info("Redis 初始化成功")
        except Exception as e:
            logger.warning(f"Redis 初始化失败，缓存功能将不可用: {e}")

        # 测试连接
        await self.test_connections()

    async def _init_postgres(self):
        """初始化 PostgreSQL 连接"""
        try:
            self.postgres_engine = create_async_engine(
                settings.DATABASE_URL,
                echo=settings.DEBUG,
                pool_size=20,
                max_overflow=30,
                pool_pre_ping=True,
            )

            self.postgres_sessionmaker = async_sessionmaker(
                self.postgres_engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )

            logger.info("PostgreSQL 连接池初始化成功")

            # 创建 pgvector 扩展（如果不存在）
            async with self.postgres_engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                logger.info("PostgreSQL 扩展 (vector, postgis) 已启用")

        except Exception as e:
            logger.error(f"PostgreSQL 连接初始化失败: {e}")
            raise

    async def _init_mysql(self):
        """初始化 MySQL 连接"""
        try:
            self.mysql_engine = create_async_engine(
                settings.MYSQL_URL,
                echo=settings.DEBUG,
                pool_size=10,
                max_overflow=15,
                pool_pre_ping=True,
            )

            self.mysql_sessionmaker = async_sessionmaker(
                self.mysql_engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )

            logger.info("MySQL 连接池初始化成功")

        except Exception as e:
            logger.error(f"MySQL 连接初始化失败: {e}")
            raise

    async def _init_redis(self):
        """初始化 Redis 连接"""
        try:
            self.redis_client = Redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )

            # 测试连接
            await self.redis_client.ping()
            logger.info("Redis 连接初始化成功")

        except Exception as e:
            logger.error(f"Redis 连接初始化失败: {e}")
            raise

    async def test_connections(self):
        """测试所有数据库连接"""
        connections = {
            "PostgreSQL": self.postgres_engine,
            "MySQL": self.mysql_engine,
            "Redis": self.redis_client,
        }

        for name, conn in connections.items():
            if conn is None:
                logger.warning(f"{name} 连接未初始化")
                continue

            try:
                if name == "Redis":
                    await conn.ping()
                else:
                    async with conn.begin() as _:
                        pass
                logger.info(f"{name} 连接测试成功")
            except Exception as e:
                logger.error(f"{name} 连接测试失败: {e}")

    @asynccontextmanager
    async def get_postgres_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取 PostgreSQL 会话"""
        if not self.postgres_sessionmaker:
            raise RuntimeError("PostgreSQL 连接未初始化")

        async with self.postgres_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @asynccontextmanager
    async def get_mysql_session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取 MySQL 会话"""
        if not self.mysql_sessionmaker:
            raise RuntimeError("MySQL 连接未初始化")

        async with self.mysql_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def get_redis(self) -> Redis:
        """获取 Redis 客户端"""
        if not self.redis_client:
            raise RuntimeError("Redis 连接未初始化")
        return self.redis_client

    async def close(self):
        """关闭所有数据库连接"""
        if self.postgres_engine:
            await self.postgres_engine.dispose()
            logger.info("PostgreSQL 连接已关闭")

        if self.mysql_engine:
            await self.mysql_engine.dispose()
            logger.info("MySQL 连接已关闭")

        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis 连接已关闭")


# 全局数据库管理器实例
db_manager = DatabaseManager()