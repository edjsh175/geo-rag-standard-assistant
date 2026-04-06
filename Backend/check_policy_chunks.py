#!/usr/bin/env python3
"""
检查 policy_chunks 表数据
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.database import db_manager
from sqlalchemy import text


async def check_policy_chunks():
    """检查 policy_chunks 表数据"""
    print("检查 policy_chunks 表...")

    try:
        # 初始化 PostgreSQL 连接
        await db_manager._init_postgres()
        print("✅ PostgreSQL 连接成功")
    except Exception as e:
        print(f"❌ PostgreSQL 连接失败: {e}")
        return

    try:
        async with db_manager.get_postgres_session() as session:
            # 1. 检查表是否存在
            table_check = await session.execute(
                text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'policy_chunks')")
            )
            table_exists = table_check.scalar()

            if not table_exists:
                print("❌ policy_chunks 表不存在")
                print("请运行数据导入脚本或检查表名是否正确")
                return

            print("✅ policy_chunks 表存在")

            # 2. 检查表结构
            columns_check = await session.execute(
                text("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'policy_chunks'
                    ORDER BY ordinal_position
                """)
            )
            columns = columns_check.fetchall()

            print("表结构:")
            for col_name, col_type in columns:
                print(f"  - {col_name}: {col_type}")

            # 检查必需列
            required_columns = {'id', 'embedding', 'content', 'standard_code', 'document_name'}
            actual_columns = {col[0] for col in columns}
            missing_columns = required_columns - actual_columns

            if missing_columns:
                print(f"❌ 缺少必需列: {missing_columns}")
                print("请检查表结构是否与预期一致")
            else:
                print("✅ 所有必需列都存在")

            # 3. 检查数据量
            count_check = await session.execute(
                text("SELECT COUNT(*) FROM policy_chunks")
            )
            total_count = count_check.scalar()
            print(f"📊 总记录数: {total_count}")

            # 4. 检查是否有向量数据
            embedding_check = await session.execute(
                text("SELECT COUNT(*) FROM policy_chunks WHERE embedding IS NOT NULL")
            )
            embedding_count = embedding_check.scalar()
            print(f"📊 有向量嵌入的记录数: {embedding_count}")

            # 5. 查看前几条记录
            if total_count > 0:
                sample_check = await session.execute(
                    text("""
                        SELECT id, standard_code, document_name,
                               LEFT(content, 100) as content_preview,
                               embedding IS NOT NULL as has_embedding
                        FROM policy_chunks
                        ORDER BY id
                        LIMIT 5
                    """)
                )
                samples = sample_check.fetchall()

                print("\n📝 前5条记录示例:")
                for i, row in enumerate(samples, 1):
                    print(f"  {i}. ID: {row.id}")
                    print(f"     标准号: {row.standard_code}")
                    print(f"     文档名: {row.document_name}")
                    print(f"     内容预览: {row.content_preview}...")
                    print(f"     有嵌入: {row.has_embedding}")
                    print()

                # 6. 检查向量维度
                if embedding_count > 0:
                    dim_check = await session.execute(
                        text("SELECT array_length(embedding, 1) as dim FROM policy_chunks WHERE embedding IS NOT NULL LIMIT 1")
                    )
                    dim_result = dim_check.fetchone()
                    if dim_result and dim_result.dim:
                        print(f"📐 向量维度: {dim_result.dim}")
                    else:
                        print("⚠️  无法获取向量维度")

                    # 7. 检查向量索引
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
                        print(f"✅ 已发现 HNSW 向量索引: {len(indexes)} 个")
                        for idx in indexes:
                            print(f"  索引名: {idx.indexname}")
                    else:
                        print("⚠️  未发现 HNSW 向量索引")
                        print("   建议执行: CREATE INDEX ON policy_chunks USING hnsw (embedding vector_cosine_ops);")
                else:
                    print("⚠️  无向量数据，跳过索引检查")
            else:
                print("❌ 表中没有数据")
                print("请运行数据导入脚本填充数据")

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理连接
        await db_manager.close()


async def main():
    """主函数"""
    print("=" * 60)
    print("policy_chunks 表数据诊断")
    print("=" * 60)

    await check_policy_chunks()

    print("\n" + "=" * 60)
    print("建议:")
    print("=" * 60)
    print("1. 如果表不存在，需要创建表并导入数据")
    print("2. 如果表为空，需要运行数据导入脚本")
    print("3. 如果缺少嵌入，需要运行向量嵌入生成脚本")
    print("4. 确保向量维度与模型匹配（通常为1536）")
    print("5. 如果检索速度慢（>1秒），请创建 HNSW 向量索引:")
    print("   CREATE INDEX ON policy_chunks USING hnsw (embedding vector_cosine_ops);")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"脚本执行失败: {e}")
        sys.exit(1)