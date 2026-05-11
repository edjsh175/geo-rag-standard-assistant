import pymysql
import config

mysql_config = config.MYSQL_CONFIG
conn = pymysql.connect(**mysql_config)
cursor = conn.cursor()

# 查询DB61/T 1533-2022
cursor.execute("SELECT standard_code FROM geoai_metadata WHERE standard_code LIKE '%DB61%1533%'")
rows = cursor.fetchall()
print("DB61/T 1533-2022 相关记录:")
for row in rows:
    print(f"  {row[0]}")

# 查询转换
cursor.execute("SELECT standard_code, REPLACE(REPLACE(standard_code, '/', '_'), '-', '_') as converted FROM geoai_metadata WHERE standard_code LIKE '%DB61%' LIMIT 5")
rows = cursor.fetchall()
print("\n转换示例:")
for row in rows:
    print(f"  {row[0]} -> {row[1]}")

cursor.close()
conn.close()
