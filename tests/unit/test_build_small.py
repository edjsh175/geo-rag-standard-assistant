"""测试小批量文件处理"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_vector_db import init_mysql, init_db, process_markdown_file, safe_extract_archives
import config

print('=== 测试小批量文件处理 ===')

# 连接MySQL
print('[1] 连接MySQL...')
mysql_conn = init_mysql()
if mysql_conn:
    print('   MySQL连接成功')
else:
    print('   MySQL连接失败')
    sys.exit(1)

# 连接PostgreSQL
print('[2] 连接PostgreSQL...')
conn, cur = init_db()
print('   PostgreSQL连接成功')

# 安全解压（使用小批量文件）
print('[3] 安全解压压缩包...')
extract_dir = safe_extract_archives()
print(f'   安全解压目录: {extract_dir}')

# 查找MD文件
print('[4] 查找MD文件...')
md_files = []
for root, dirs, files in os.walk(extract_dir):
    for file in files:
        if file.endswith('.md'):
            md_files.append(os.path.join(root, file))

print(f'   找到 {len(md_files)} 个MD文件')

# 只处理前3个文件
print('[5] 处理前3个文件...')
processed = 0
for i, md_file in enumerate(md_files[:3]):
    print(f'\n[处理文件 {i+1}/{3}]')
    print(f'   文件: {md_file}')
    try:
        process_markdown_file(md_file, conn, cur, mysql_conn)
        processed += 1
    except Exception as e:
        print(f'   [错误] 处理失败: {e}')

print(f'\n[6] 处理完成: 成功 {processed} 个，失败 {3 - processed} 个')

# 验证数据
print('[7] 验证数据...')
cur.execute("SELECT COUNT(*) FROM policy_chunks")
count = cur.fetchone()[0]
print(f'   总记录数: {count}')

# 按标准号统计
cur.execute("""
    SELECT standard_code, COUNT(*) as chunk_count
    FROM policy_chunks
    GROUP BY standard_code
    ORDER BY chunk_count DESC
""")
print('   按标准号统计:')
for row in cur.fetchall():
    print(f'   {row[0]}: {row[1]} 个切片')

mysql_conn.close()
conn.close()
print('\n[8] 测试完成！')
