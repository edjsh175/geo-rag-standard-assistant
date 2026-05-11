import pymysql
import config


mysql_config = config.MYSQL_CONFIG

try:
    conn = pymysql.connect(**mysql_config)
    cursor = conn.cursor()

    cursor.execute("SELECT standard_code FROM geoai_metadata LIMIT 20")
    rows = cursor.fetchall()

    print("Sample standard codes in MySQL:")
    for row in rows:
        print(f"  {row[0]}")

    cursor.execute("SELECT standard_code FROM geoai_metadata WHERE standard_code LIKE '%DB1310%'")
    rows = cursor.fetchall()

    print("\nStandard codes containing 'DB1310':")
    for row in rows:
        print(f"  {row[0]}")

    cursor.execute("SELECT standard_code FROM geoai_metadata WHERE standard_code LIKE '%DB41/T%'")
    rows = cursor.fetchall()

    print("\nStandard codes containing 'DB41/T':")
    for row in rows:
        print(f"  {row[0]}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"Error: {e}")
