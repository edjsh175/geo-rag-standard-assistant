import pymysql
import config

# 使用config中的配置
mysql_config = config.MYSQL_CONFIG

try:
    conn = pymysql.connect(**mysql_config)
    cursor = conn.cursor()

    # 查询所有标准号，查看格式
    cursor.execute("SELECT standard_code, LENGTH(standard_code) as len FROM standard_norm_detail ORDER BY len DESC LIMIT 30")
    rows = cursor.fetchall()

    print("MySQL中的标准号样例（按长度排序）：")
    for row in rows:
        print(f"  {row[0]} (长度:{row[1]})")

    # 查询包含'1310'或'365'的标准号
    cursor.execute("SELECT standard_code FROM standard_norm_detail WHERE standard_code LIKE '%1310%' OR standard_code LIKE '%365%'")
    rows = cursor.fetchall()

    print("\n包含'1310'或'365'的标准号：")
    for row in rows:
        print(f"  {row[0]}")

    # 查询标准号中是否包含空格
    cursor.execute("SELECT standard_code FROM standard_norm_detail WHERE standard_code LIKE '% %' LIMIT 10")
    rows = cursor.fetchall()

    print("\n包含空格的标准号：")
    for row in rows:
        print(f"  {row[0]}")

    # 测试转换逻辑：将标准号中的'/'替换为'_'，'-'替换为'_'
    cursor.execute("SELECT standard_code, REPLACE(REPLACE(standard_code, '/', '_'), '-', '_') as converted FROM standard_norm_detail LIMIT 10")
    rows = cursor.fetchall()

    print("\n转换测试（/→_, -→_）：")
    for row in rows:
        print(f"  {row[0]} -> {row[1]}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"错误: {e}")