"""测试MySQL连接和表结构"""
import config
import pymysql

print('=== 测试MySQL连接 ===')
try:
    conn = pymysql.connect(**config.MYSQL_CONFIG)
    print('[成功] MySQL连接成功')
    
    # 查询表结构
    with conn.cursor() as cursor:
        cursor.execute(f"DESCRIBE {config.MYSQL_TABLE}")
        columns = cursor.fetchall()
        print(f'\n表 {config.MYSQL_TABLE} 结构:')
        for col in columns:
            print(f'  - {col[0]}: {col[1]}')
        
        # 查询几条示例数据
        cursor.execute(f"SELECT standard_code, keyword, chinese_name, draft_unit, release_date FROM {config.MYSQL_TABLE} LIMIT 3")
        rows = cursor.fetchall()
        print(f'\n示例数据:')
        for row in rows:
            print(f'  标准号: {row[0]}, 关键词: {row[1]}, 中文名: {row[2][:30]}...')
    
    conn.close()
    print('\n[成功] MySQL测试完成')
except Exception as e:
    print(f'[错误] MySQL连接失败: {e}')
