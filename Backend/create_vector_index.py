#!/usr/bin/env python3
"""
创建 pgvector HNSW 索引以提高检索性能
此脚本检查 policy_chunks 表是否已存在 HNSW 索引，如果不存在则创建
"""

import asyncio
import re
from pathlib import Path
import sys

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def create_vector_index():
    """创建 HNSW 向量索引"""
    print("🔍 检查并创建 pgvector HNSW 索引")

    # 尝试使用 app.core.database 中的连接
    try:
        from app.core.database import db_manager
    except ImportError as e:
        print(f"❌ 导入数据库模块失败: {e}")
        print("请确保已安装所有依赖: pip install -r requirements.txt")
        return

    try:
        # 初始化 PostgreSQL 连接
        print("正在连接到 PostgreSQL...")
        await db_manager._init_postgres()
        print("✅ PostgreSQL 连接成功")

        async with db_manager.get_postgres_session() as session:
            from sqlalchemy import text

            # 1. 检查表是否存在
            table_check = await session.execute(
                text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'policy_chunks')")
            )
            table_exists = table_check.scalar()

            if not table_exists:
                print("❌ policy_chunks 表不存在，无法创建索引")
                print("请先运行数据导入脚本创建表")
                return

            print("✅ policy_chunks 表存在")

            # 2. 检查是否有向量数据
            count_check = await session.execute(
                text("SELECT COUNT(*) FROM policy_chunks WHERE embedding IS NOT NULL")
            )
            embedding_count = count_check.scalar()

            if embedding_count == 0:
                print("⚠️  表中没有向量数据，无法创建索引")
                print("请先运行向量嵌入生成脚本")
                return

            print(f"📊 向量数据条数: {embedding_count}")

            # 3. 检查是否已存在 HNSW 索引
            index_check = await session.execute(
                text("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = 'policy_chunks'
                    AND indexdef LIKE '%hnsw%'
                """)
            )
            indexes = index_check.fetchall()

            if indexes:
                print(f"✅ 已存在 HNSW 索引: {len(indexes)} 个")
                for idx in indexes:
                    print(f"  索引名: {idx.indexname}")
                    print(f"  定义: {idx.indexdef[:100]}...")
                print("\n无需创建新索引")
                return

            # 4. 检查 pgvector 版本是否支持 HNSW
            version_check = await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            version_result = version_check.fetchone()

            if not version_result:
                print("❌ pgvector 扩展未安装")
                print("请先安装 pgvector 扩展: CREATE EXTENSION vector;")
                return

            pgvector_version = version_result.extversion
            print(f"📦 pgvector 版本: {pgvector_version}")

            # 检查版本是否支持 HNSW（HNSW 需要 pgvector 0.5.0+）
            try:
                major, minor, patch = map(int, pgvector_version.split('.'))
                if major == 0 and minor < 5:
                    print(f"⚠️  pgvector 版本 {pgvector_version} 可能不支持 HNSW 索引")
                    print("建议升级到 pgvector 0.5.0 或更高版本")
                    print("继续尝试创建索引...")
            except ValueError:
                print(f"⚠️  无法解析版本号: {pgvector_version}")
                print("继续尝试创建索引...")

            # 5. 创建 HNSW 索引
            print("\n🚀 正在创建 HNSW 索引...")
            print("   这可能需要一些时间，取决于数据量和硬件性能")
            print("   执行: CREATE INDEX ON policy_chunks USING hnsw (embedding vector_cosine_ops);")

            try:
                # 开始创建索引
                start_time = asyncio.get_event_loop().time()
                await session.execute(
                    text("CREATE INDEX ON policy_chunks USING hnsw (embedding vector_cosine_ops)")
                )
                await session.commit()
                end_time = asyncio.get_event_loop().time()

                creation_time = end_time - start_time
                print(f"✅ HNSW 索引创建成功！耗时: {creation_time:.2f} 秒")
                print("\n🎉 索引创建完成！")
                print("   现在向量检索性能应该从 10+ 秒提升到毫秒级别")

                # 6. 验证索引
                verify_check = await session.execute(
                    text("""
                        SELECT indexname, indexdef
                        FROM pg_indexes
                        WHERE tablename = 'policy_chunks'
                        AND indexdef LIKE '%hnsw%'
                    """)
                )
                verified_indexes = verify_check.fetchall()

                if verified_indexes:
                    print(f"\n✅ 索引验证成功:")
                    for idx in verified_indexes:
                        print(f"   索引名: {idx.indexname}")
                else:
                    print("\n⚠️  索引创建成功但验证时未找到")

            except Exception as create_error:
                print(f"❌ 创建索引失败: {create_error}")
                print("\n可能的原因:")
                print("1. pgvector 版本太低，不支持 HNSW")
                print("2. 内存不足（创建索引需要足够的内存）")
                print("3. 数据库权限不足")
                print("\n解决方案:")
                print("1. 升级 pgvector: ALTER EXTENSION vector UPDATE;")
                print("2. 尝试使用 IVFFlat 索引:")
                print("   CREATE INDEX ON policy_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);")
                print("3. 联系数据库管理员")

    except Exception as e:
        print(f"❌ 脚本执行失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理连接
        try:
            await db_manager.close()
        except:
            pass

async def main():
    """主函数"""
    print("=" * 60)
    print("pgvector HNSW 索引创建工具")
    print("=" * 60)
    print("")
    print("此脚本将:")
    print("1. 检查 policy_chunks 表是否存在")
    print("2. 检查是否已有 HNSW 索引")
    print("3. 如果没有索引，创建 HNSW 索引以提升检索性能")
    print("")
    print("注意: 创建索引需要一定时间，且需要足够的数据库内存")
    print("=" * 60)

    await create_vector_index()

    print("\n" + "=" * 60)
    print("完成！")
    print("=" * 60)
    print("\n性能对比:")
    print("🔴 无索引: 10-30 秒（全表扫描）")
    print("🟢 有 HNSW 索引: 10-100 毫秒")
    print("\n测试方法:")
    print("1. 重启后端服务")
    print("2. 执行一次搜索")
    print("3. 观察 search_time 字段是否降到 1 秒以内")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"脚本执行失败: {e}")
        sys.exit(1)