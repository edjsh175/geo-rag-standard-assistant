#!/usr/bin/env python3
"""
测试 policy_chunks 表数据
"""

import asyncio
import asyncpg
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 从 .env 文件解析 PostgreSQL 连接信息
def parse_postgres_url():
    """解析 .env 中的 DATABASE_URL"""
    env_file = Path(project_root) / ".env"
    if not env_file.exists():
        print(f"❌ .env 文件不存在: {env_file}")
        return None

    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"\'')
                # 格式: postgresql+asyncpg://user:password@host:port/dbname?ssl=disable
                if url.startswith("postgresql+asyncpg://"):
                    url = url[len("postgresql+asyncpg://"):]

                # 移除查询参数
                if '?' in url:
                    url = url.split('?')[0]

                parts = url.split('@')
                if len(parts) != 2:
                    print(f"❌ 连接字符串格式不正确: {url}")
                    return None

                user_pass = parts[0].split(':')
                host_port_db = parts[1].split('/')

                if len(user_pass) < 2 or len(host_port_db) < 2:
                    print(f"❌ 连接字符串格式不正确: {url}")
                    return None

                user = user_pass[0]
                password = user_pass[1] if len(user_pass) > 1 else ""
                host_port = host_port_db[0].split(':')
                host = host_port[0]
                port = host_port[1] if len(host_port) > 1 else "5432"
                database = host_port_db[1]

                return {
                    "user": user,
                    "password": password,
                    "host": host,
                    "port": int(port),
                    "database": database
                }

    print("❌ 在 .env 中找不到 DATABASE_URL")
    return None


async def test_table():
    """测试 policy_chunks 表"""
    print("测试 policy_chunks 表数据...")

    conn_info = parse_postgres_url()
    if not conn_info:
        return

    print(f"连接信息: {conn_info['user']}@{conn_info['host']}:{conn_info['port']}/{conn_info['database']}")

    try:
        # 连接数据库
        conn = await asyncpg.connect(**conn_info)
        print("✅ PostgreSQL 连接成功")

        # 1. 检查表是否存在
        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'policy_chunks')"
        )

        if not table_exists:
            print("❌ policy_chunks 表不存在")
            await conn.close()
            return

        print("✅ policy_chunks 表存在")

        # 2. 获取表结构
        columns = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'policy_chunks' ORDER BY ordinal_position"
        )

        print("\n表结构:")
        for col in columns:
            print(f"  - {col['column_name']}: {col['data_type']}")

        # 3. 检查数据量
        total_count = await conn.fetchval("SELECT COUNT(*) FROM policy_chunks")
        print(f"\n📊 总记录数: {total_count}")

        embedding_count = await conn.fetchval("SELECT COUNT(*) FROM policy_chunks WHERE embedding IS NOT NULL")
        print(f"📊 有向量嵌入的记录数: {embedding_count}")

        # 4. 查看前几条记录
        if total_count > 0:
            samples = await conn.fetch("""
                SELECT id, standard_code, document_name,
                       LEFT(content, 100) as content_preview,
                       embedding IS NOT NULL as has_embedding,
                       array_length(embedding, 1) as embedding_dim
                FROM policy_chunks
                ORDER BY id
                LIMIT 5
            """)

            print("\n📝 前5条记录示例:")
            for i, row in enumerate(samples, 1):
                print(f"  {i}. ID: {row['id']}")
                print(f"     标准号: {row['standard_code']}")
                print(f"     文档名: {row['document_name']}")
                print(f"     内容预览: {row['content_preview']}...")
                print(f"     有嵌入: {row['has_embedding']}")
                if row['embedding_dim']:
                    print(f"     嵌入维度: {row['embedding_dim']}")
                print()

        # 5. 检查向量维度分布
        if embedding_count > 0:
            dims = await conn.fetch("""
                SELECT array_length(embedding, 1) as dim, COUNT(*) as count
                FROM policy_chunks
                WHERE embedding IS NOT NULL
                GROUP BY array_length(embedding, 1)
                ORDER BY dim
            """)

            print("📐 向量维度分布:")
            for row in dims:
                print(f"  - 维度 {row['dim']}: {row['count']} 条记录")

        # 6. 测试相似度查询
        if embedding_count > 0:
            print("\n🧪 测试相似度查询...")
            # 获取一个样本嵌入
            sample = await conn.fetchrow("""
                SELECT embedding FROM policy_chunks WHERE embedding IS NOT NULL LIMIT 1
            """)

            if sample:
                test_embedding = sample['embedding']
                test_results = await conn.fetch("""
                    SELECT id, standard_code, document_name,
                           1 - (embedding <=> $1) as similarity
                    FROM policy_chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> $1
                    LIMIT 3
                """, test_embedding)

                print("  相似度查询结果（使用表中第一个嵌入作为查询）:")
                for i, row in enumerate(test_results, 1):
                    print(f"    {i}. ID: {row['id']}, 相似度: {row['similarity']:.4f}, 标准号: {row['standard_code']}")
            else:
                print("  无法找到测试嵌入")

        await conn.close()

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """主函数"""
    print("=" * 60)
    print("policy_chunks 表数据测试")
    print("=" * 60)

    await test_table()

    print("\n" + "=" * 60)
    print("建议:")
    print("=" * 60)
    print("1. 确保表中有数据且包含向量嵌入")
    print("2. 向量维度应为 2048（智谱 embedding-3）")
    print("3. 如果表为空，运行数据导入脚本")
    print("4. 如果缺少嵌入，检查 embedding API 配置")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"脚本执行失败: {e}")
        sys.exit(1)