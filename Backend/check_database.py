#!/usr/bin/env python3
"""
数据库连接检查脚本
用于诊断 PostgreSQL 连接问题
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.core.database import db_manager


async def test_postgresql_connection():
    """测试 PostgreSQL 连接"""
    print("测试 PostgreSQL 连接...")
    print(f"连接字符串: {settings.DATABASE_URL}")

    # 解析连接字符串以显示详细信息
    try:
        # 格式: postgresql+asyncpg://user:password@host:port/dbname
        url = settings.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            url = url[len("postgresql+asyncpg://"):]

        parts = url.split("@")
        if len(parts) != 2:
            print(f"  错误: 连接字符串格式不正确")
            return False

        user_pass = parts[0].split(":")
        host_port_db = parts[1].split("/")

        if len(user_pass) < 2 or len(host_port_db) < 2:
            print(f"  错误: 连接字符串格式不正确")
            return False

        user = user_pass[0]
        password = user_pass[1] if len(user_pass) > 1 else ""
        host_port = host_port_db[0].split(":")
        host = host_port[0]
        port = host_port[1] if len(host_port) > 1 else "5432"
        database = host_port_db[1]

        print(f"  用户: {user}")
        print(f"  主机: {host}")
        print(f"  端口: {port}")
        print(f"  数据库: {database}")

    except Exception as e:
        print(f"  解析连接字符串失败: {e}")
        return False

    # 尝试连接
    try:
        await db_manager._init_postgres()
        print("  ✅ PostgreSQL 连接成功!")

        # 测试扩展
        try:
            async with db_manager.postgres_engine.begin() as conn:
                from sqlalchemy import text
                result = await conn.execute(text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'postgis')"))
                extensions = [row[0] for row in result.fetchall()]

                if 'vector' in extensions:
                    print("  ✅ pgvector 扩展已安装")
                else:
                    print("  ❌ pgvector 扩展未安装，请运行: CREATE EXTENSION vector;")

                if 'postgis' in extensions:
                    print("  ✅ postgis 扩展已安装")
                else:
                    print("  ❌ postgis 扩展未安装，请运行: CREATE EXTENSION postgis;")

        except Exception as e:
            print(f"  检查扩展失败: {e}")

        return True

    except Exception as e:
        print(f"  ❌ PostgreSQL 连接失败: {e}")
        print("\n可能的解决方案:")
        print("1. 确保 PostgreSQL 服务正在运行")
        print("   Windows: 检查 PostgreSQL 服务是否启动")
        print("   Linux/macOS: sudo systemctl status postgresql 或 pg_ctl status")
        print()
        print("2. 创建数据库（如果不存在）:")
        print(f"   createdb -U {user} {database}")
        print()
        print("3. 在数据库中启用扩展:")
        print(f"   psql -U {user} -d {database} -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS postgis;'")
        print()
        print("4. 检查防火墙设置（如果使用远程数据库）")
        print()
        print("5. 验证用户名/密码是否正确")
        print(f"   当前配置: {user}:{'*' * len(password) if password else '(空密码)'}")
        print()
        print("6. 检查 .env 文件中的 DATABASE_URL 配置")
        return False


async def test_mysql_connection():
    """测试 MySQL 连接"""
    print("\n测试 MySQL 连接...")
    print(f"连接字符串: {settings.MYSQL_URL}")

    try:
        await db_manager._init_mysql()
        print("  ✅ MySQL 连接成功!")
        return True
    except Exception as e:
        print(f"  ❌ MySQL 连接失败: {e}")
        print("\n注意: MySQL 用于存储元数据，如果不可用，部分功能可能受限")
        return False


async def main():
    """主函数"""
    print("=" * 60)
    print("GeoAI 数据库连接诊断工具")
    print("=" * 60)

    postgres_ok = await test_postgresql_connection()
    mysql_ok = await test_mysql_connection()

    print("\n" + "=" * 60)
    print("诊断结果:")
    print("=" * 60)

    if postgres_ok:
        print("✅ PostgreSQL: 连接正常")
    else:
        print("❌ PostgreSQL: 连接失败（向量搜索功能将不可用）")

    if mysql_ok:
        print("✅ MySQL: 连接正常")
    else:
        print("⚠️  MySQL: 连接失败（元数据功能将受限）")

    print("\n建议:")
    if not postgres_ok:
        print("- PostgreSQL 是向量搜索的核心组件，必须修复连接问题")
        print("- 请按照上面的指导步骤检查和修复 PostgreSQL 连接")
    else:
        print("- PostgreSQL 连接正常，可以运行完整功能")

    if not mysql_ok:
        print("- MySQL 用于存储文档元数据，如果不需要元数据功能可以忽略")

    print("\n启动服务:")
    print("1. 修复所有数据库连接问题")
    print("2. 运行: uvicorn main:app --reload")
    print("3. 访问 http://localhost:8000 检查服务状态")
    print("4. 访问 http://localhost:8000/health 检查健康状态")

    # 清理
    await db_manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"脚本执行失败: {e}")
        sys.exit(1)