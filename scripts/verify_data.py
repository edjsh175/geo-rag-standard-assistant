"""验证PostgreSQL中的数据"""
import psycopg2
import config

conn = psycopg2.connect(**config.DB_CONFIG)
cur = conn.cursor()

print('=== 验证PostgreSQL数据 ===\n')

# 1. 统计记录数
cur.execute("SELECT COUNT(*) FROM policy_chunks")
count = cur.fetchone()[0]
print(f'[1] 总记录数: {count}')

# 2. 查看表结构
print('\n[2] 表结构:')
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'policy_chunks'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f'   {row[0]}: {row[1]}')

# 3. 查看样例数据
print('\n[3] 样例数据（前3条）:')
cur.execute("""
    SELECT standard_code, category, keyword, chinese_name, 
           release_date, draft_unit, LEFT(content, 80) as content_preview
    FROM policy_chunks 
    LIMIT 3
""")
for i, row in enumerate(cur.fetchall(), 1):
    print(f'\n   记录 {i}:')
    print(f'      标准号: {row[0]}')
    print(f'      分类: {row[1]}')
    print(f'      关键词: {row[2]}')
    print(f'      中文名: {row[3][:50]}...' if row[3] and len(row[3]) > 50 else f'      中文名: {row[3]}')
    print(f'      发布日期: {row[4]}')
    print(f'      起草单位: {row[5][:40]}...' if row[5] and len(row[5]) > 40 else f'      起草单位: {row[5]}')
    print(f'      内容预览: {row[6]}...')

# 4. 按标准号统计
print('\n[4] 按标准号统计:')
cur.execute("""
    SELECT standard_code, COUNT(*) as chunk_count
    FROM policy_chunks
    GROUP BY standard_code
    ORDER BY chunk_count DESC
    LIMIT 5
""")
for row in cur.fetchall():
    print(f'   {row[0]}: {row[1]} 个切片')

# 5. 测试向量检索
print('\n[5] 测试向量检索:')
cur.execute("""
    SELECT embedding <=> embedding as similarity
    FROM policy_chunks
    LIMIT 1
""")
result = cur.fetchone()
if result:
    print(f'   向量自相似度: {result[0]} (应为0.0)')

conn.close()
print('\n=== 验证完成 ===')
