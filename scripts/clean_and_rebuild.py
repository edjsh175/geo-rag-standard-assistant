"""
[DEPRECATED / OFFLINE ONLY] 清理离线知识库旧数据脚本。

警告：本脚本为离线恢复工具，严禁在生产环境直接运行！
直接清空 live 数据库表将破坏文档索引一致性。生产环境请使用标准迁移和生命周期服务。
"""

import os
import shutil
import sys

if "--confirm-destructive-clean" not in sys.argv:
    print("=" * 60)
    print("错误: 本脚本包含直接破坏性删除操作 (DELETE FROM policy_chunks)！")
    print("严禁在生产或常规调试环境执行。")
    print("如果确实需要离线重建测试库，请显式追加参数: --confirm-destructive-clean")
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

print("=== [离线警告] 执行清理旧数据 ===")

# 连接PostgreSQL
conn = psycopg2.connect(**config.DB_CONFIG)
cur = conn.cursor()

# 删除旧数据
cur.execute("DELETE FROM policy_chunks")
deleted = cur.rowcount
conn.commit()
print(f"[1] 已删除 {deleted} 条旧记录")

# 删除解压目录
if os.path.exists("md_extracted_safe"):
    shutil.rmtree("md_extracted_safe")
    print("[2] 已删除 md_extracted_safe 目录")

conn.close()
print("[3] 清理完成，可离线重新运行 build_vector_db.py")
