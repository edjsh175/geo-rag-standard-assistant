"""
[DEPRECATED / OFFLINE RECOVERY ONLY] 离线修复PostgreSQL表结构工具。

警告：生产环境严禁使用此脚本！
所有正式数据库表结构更新、字段增改必须通过 Backend/migrations/ 下的版本化 SQL 迁移文件管理。
使用脚本直接 ALTER 生产表会绕过版本契约与校验，破坏迁移审计。
"""

import sys

if "--confirm-offline-schema-fix" not in sys.argv:
    print("=" * 60)
    print("错误: 生产环境严禁绕过版本化 Migration 直接修改表结构！")
    print("标准流程请应用 Backend/migrations/ 下的 SQL 迁移。")
    print("若作为纯离线孤立测试库恢复，请显式传入: --confirm-offline-schema-fix")
    print("=" * 60)
    sys.exit(1)

try:
    import config
except ImportError:
    try:
        from src.geoai.core import config
    except ImportError:
        print("错误: 无法导入数据库配置文件 config.py")
        sys.exit(1)

import psycopg2
from pgvector.psycopg2 import register_vector

print("=== [离线警告] 执行修复PostgreSQL表结构 ===")
conn = psycopg2.connect(**config.DB_CONFIG)
cur = conn.cursor()

# 检查表是否存在
cur.execute("""
    SELECT EXISTS (
        SELECT FROM information_schema.tables 
        WHERE table_name = 'policy_chunks'
    );
""")
table_exists = cur.fetchone()[0]

if table_exists:
    print("[信息] policy_chunks 表已存在，检查字段...")
    
    # 获取现有字段
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'policy_chunks';
    """)
    existing_columns = [row[0] for row in cur.fetchall()]
    print(f"现有字段: {existing_columns}")
    
    # 需要添加的字段
    required_columns = {
        "keyword": "varchar(100)",
        "chinese_name": "varchar(500)",
        "english_name": "varchar(500)",
        "release_date": "varchar(20)",
        "implement_date": "varchar(20)",
        "standard_status": "varchar(50)",
        "release_unit": "varchar(255)",
        "charge_unit": "varchar(255)",
        "draft_unit": "varchar(255)",
        "replace_standard": "varchar(500)",
        "application_scope": "text",
        "document_name": "varchar(255)",
        "header_path": "text"
    }
    
    # 添加缺失的字段
    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            print(f"[添加] 添加字段 {col_name} ({col_type})")
            cur.execute(f"ALTER TABLE policy_chunks ADD COLUMN {col_name} {col_type};")
        else:
            print(f"[存在] 字段 {col_name} 已存在")
    
    conn.commit()
    print("[成功] 表结构更新完成")
else:
    print("[信息] policy_chunks 表不存在，将创建新表")
    vector_dim = getattr(config, "VECTOR_DIMENSION", 2048)
    cur.execute(f"""
        CREATE TABLE policy_chunks (
            id bigserial PRIMARY KEY,
            standard_code varchar(100),
            category varchar(100),
            keyword varchar(100),
            chinese_name varchar(500),
            english_name varchar(500),
            release_date varchar(20),
            implement_date varchar(20),
            standard_status varchar(50),
            release_unit varchar(255),
            charge_unit varchar(255),
            draft_unit varchar(255),
            replace_standard varchar(500),
            application_scope text,
            document_name varchar(255),
            header_path text,
            content text,
            embedding vector({vector_dim})
        );
    """)
    conn.commit()
    print("[成功] 新表创建完成")

# 验证最终结构
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'policy_chunks'
    ORDER BY ordinal_position;
""")
print("\n=== 最终表结构 ===")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.close()
print("\n[完成] 数据库修复完成")
