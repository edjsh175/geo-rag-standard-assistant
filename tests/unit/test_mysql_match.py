"""测试MySQL标准号匹配"""
import pymysql
import config

conn = pymysql.connect(**config.MYSQL_CONFIG)

test_codes = [
    'DB61_T 1533-2022',
    'DB61/T 1533-2022',
    'DB61T 1533-2022',
    'DB61-T 1533-2022',
]

print('=== 测试MySQL标准号匹配 ===')
for code in test_codes:
    with conn.cursor() as cursor:
        sql = f"SELECT standard_code, chinese_name FROM {config.MYSQL_TABLE} WHERE standard_code = %s"
        cursor.execute(sql, (code,))
        row = cursor.fetchone()
        if row:
            print(f'[匹配成功] {code} -> {row[0]}: {row[1][:30]}...')
        else:
            print(f'[匹配失败] {code}')

# 模糊查询
print('\n=== 模糊查询测试 ===')
with conn.cursor() as cursor:
    sql = f"SELECT standard_code, chinese_name FROM {config.MYSQL_TABLE} WHERE standard_code LIKE %s"
    cursor.execute(sql, ('%1533%',))
    rows = cursor.fetchall()
    for row in rows:
        print(f'  {row[0]}: {row[1][:40]}...')

conn.close()
