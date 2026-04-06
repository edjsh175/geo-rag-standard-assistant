"""清理旧数据并重新构建"""
import psycopg2
import config
import os
import shutil

print('=== 清理旧数据 ===')

# 连接PostgreSQL
conn = psycopg2.connect(**config.DB_CONFIG)
cur = conn.cursor()

# 删除旧数据
cur.execute("DELETE FROM policy_chunks")
deleted = cur.rowcount
conn.commit()
print(f'[1] 已删除 {deleted} 条旧记录')

# 删除解压目录
if os.path.exists('md_extracted_safe'):
    shutil.rmtree('md_extracted_safe')
    print('[2] 已删除 md_extracted_safe 目录')

conn.close()
print('[3] 清理完成，可以重新运行 build_vector_db.py')
