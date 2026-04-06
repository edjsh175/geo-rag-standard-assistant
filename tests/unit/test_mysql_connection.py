"""快速测试 MySQL 连接"""
import config
import pymysql
from build_vector_db import init_mysql, get_standard_metadata

print('=== 快速测试 MySQL 连接 ===')
mysql_conn = init_mysql()
if mysql_conn:
    print('MySQL 连接成功')
    # 测试查询
    metadata = get_standard_metadata(mysql_conn, 'DB61_T 1533-2022')
    if metadata:
        print('元数据查询成功:')
        print(f'  关键词: {metadata["keyword"]}')
        print(f'  中文名: {metadata["chinese_name"]}')
    else:
        print('元数据查询失败')
    mysql_conn.close()
else:
    print('MySQL 连接失败')
print('测试完成')
