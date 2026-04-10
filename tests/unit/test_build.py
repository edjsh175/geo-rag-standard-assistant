"""测试构建脚本 - 只处理一个文件"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_vector_db import init_mysql, get_standard_metadata, get_embedding, process_markdown_file, init_db
import config

print('=== 测试单文件处理 ===')

# 连接MySQL
print('[1] 连接MySQL...')
mysql_conn = init_mysql()
if mysql_conn:
    print('   MySQL连接成功')
else:
    print('   MySQL连接失败')

# 连接PostgreSQL
print('[2] 连接PostgreSQL...')
conn, cur = init_db()
print('   PostgreSQL连接成功')

# 测试文件路径
test_file = r'D:\work\Project\ragAI知识库\md_extracted_safe\崩塌\DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南\full.md'

if not os.path.exists(test_file):
    print(f'[错误] 测试文件不存在: {test_file}')
    sys.exit(1)

print(f'[3] 处理测试文件...')
print(f'   文件: {test_file}')

# 测试查询MySQL元数据
import re
parent_dir_name = "DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南"
match = re.match(r'^([A-Z]+\d*[/._]?[A-Z]*\s*\d+[—\-]\d+)(?:\s+(.+))?$', parent_dir_name, re.IGNORECASE)
standard_code = match.group(1).strip() if match else parent_dir_name

print(f'   标准号: {standard_code}')
print('[4] 查询MySQL元数据...')
metadata = get_standard_metadata(mysql_conn, standard_code)
if metadata:
    print(f'   关键词: {metadata["keyword"]}')
    print(f'   中文名: {metadata["chinese_name"][:40]}...')
    print(f'   发布日期: {metadata["release_date"]}')
    print(f'   起草单位: {metadata["draft_unit"][:40]}...' if len(metadata["draft_unit"]) > 40 else f'   起草单位: {metadata["draft_unit"]}')
else:
    print('   [警告] 未找到元数据')

# 测试完整处理流程
print('[5] 测试完整处理流程...')
try:
    process_markdown_file(test_file, conn, cur, mysql_conn)
    print('   处理成功！')
except Exception as e:
    print(f'   [错误] 处理失败: {e}')
    import traceback
    traceback.print_exc()

print('[6] 测试完成！')

if mysql_conn:
    mysql_conn.close()
conn.close()
