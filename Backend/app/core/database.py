"""
Database connection manager for PostgreSQL, MySQL, and Redis.
"""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator, Optional

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class DatabaseManager:
    """Manage database and cache clients."""

    def __init__(self):
        self.postgres_engine: Optional[AsyncEngine] = None
        self.postgres_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

        self.mysql_engine: Optional[AsyncEngine] = None
        self.mysql_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

        self.redis_client: Optional[Redis] = None

        import asyncio

        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize required databases and optional cache.

        PostgreSQL backs vector/spatial search and MySQL backs standard
        metadata. Both are required for the current application path. Redis is
        a cache dependency and may be unavailable without blocking startup.
        """

        async with self._init_lock:
            if self._initialized:
                return
            self._initialized = True

        required_errors: list[str] = []

        try:
            await self._init_postgres()
            await self._test_engine("PostgreSQL", self.postgres_engine)
            logger.info("PostgreSQL initialized successfully")
        except Exception as exc:
            logger.error("PostgreSQL initialization failed: %s", exc)
            required_errors.append(f"PostgreSQL: {exc}")

        try:
            await self._init_mysql()
            await self._test_engine("MySQL", self.mysql_engine)
            logger.info("MySQL initialized successfully")
        except Exception as exc:
            logger.error("MySQL initialization failed: %s", exc)
            required_errors.append(f"MySQL: {exc}")

        try:
            await self._init_redis()
            logger.info("Redis initialized successfully")
        except Exception as exc:
            logger.warning("Redis initialization failed; cache will be unavailable: %s", exc)

        if required_errors:
            await self.close()
            raise RuntimeError(
                "Required database initialization failed: "
                + "; ".join(required_errors)
            )

    async def _init_postgres(self) -> None:
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

        async with self.postgres_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    async def _init_mysql(self) -> None:
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

    async def _init_redis(self) -> None:
        self.redis_client = Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await self.redis_client.ping()

    async def _test_engine(self, name: str, engine: Optional[AsyncEngine]) -> None:
        if engine is None:
            raise RuntimeError(f"{name} engine was not initialized")

        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

    async def test_connections(self) -> None:
        """Log the current connectivity state for all initialized clients."""

        connections = {
            "PostgreSQL": self.postgres_engine,
            "MySQL": self.mysql_engine,
            "Redis": self.redis_client,
        }

        for name, conn in connections.items():
            if conn is None:
                logger.warning("%s connection is not initialized", name)
                continue

            try:
                if name == "Redis":
                    await conn.ping()
                else:
                    await self._test_engine(name, conn)
                logger.info("%s connection test succeeded", name)
            except Exception as exc:
                logger.error("%s connection test failed: %s", name, exc)

    @asynccontextmanager
    async def get_postgres_session(self) -> AsyncGenerator[AsyncSession, None]:
        if not self.postgres_sessionmaker:
            raise RuntimeError("PostgreSQL connection is not initialized")

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
        if not self.mysql_sessionmaker:
            raise RuntimeError("MySQL connection is not initialized")

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
        if not self.redis_client:
            raise RuntimeError("Redis connection is not initialized")
        return self.redis_client

    async def close(self) -> None:
        if self.postgres_engine:
            await self.postgres_engine.dispose()
            logger.info("PostgreSQL connection closed")

        if self.mysql_engine:
            await self.mysql_engine.dispose()
            logger.info("MySQL connection closed")

        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")


db_manager = DatabaseManager()
