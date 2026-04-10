import pymysql
import config

# 使用config中的配置
mysql_config = config.MYSQL_CONFIG

try:
    conn = pymysql.connect(**mysql_config)
    cursor = conn.cursor()

    # 查询所有标准号
    cursor.execute("SELECT standard_code FROM standard_norm_detail LIMIT 20")
    rows = cursor.fetchall()

    print("MySQL中的标准号样例：")
    for row in rows:
        print(f"  {row[0]}")

    # 查询DB1310相关的标准号
    cursor.execute("SELECT standard_code FROM standard_norm_detail WHERE standard_code LIKE '%DB1310%'")
    rows = cursor.fetchall()

    print("\n包含'DB1310'的标准号：")
    for row in rows:
        print(f"  {row[0]}")

    # 查询DB41/T 1979-2020
    cursor.execute("SELECT standard_code FROM standard_norm_detail WHERE standard_code LIKE '%DB41/T%'")
    rows = cursor.fetchall()

    print("\n包含'DB41/T'的标准号：")
    for row in rows:
        print(f"  {row[0]}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"错误: {e}")