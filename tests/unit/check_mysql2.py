import pymysql
import config


mysql_config = config.MYSQL_CONFIG

try:
    conn = pymysql.connect(**mysql_config)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT standard_code, LENGTH(standard_code) as len "
        "FROM geoai_metadata ORDER BY len DESC LIMIT 30"
    )
    rows = cursor.fetchall()

    print("Sample standard codes ordered by length:")
    for row in rows:
        print(f"  {row[0]} (length:{row[1]})")

    cursor.execute(
        "SELECT standard_code FROM geoai_metadata "
        "WHERE standard_code LIKE '%1310%' OR standard_code LIKE '%365%'"
    )
    rows = cursor.fetchall()

    print("\nStandard codes containing '1310' or '365':")
    for row in rows:
        print(f"  {row[0]}")

    cursor.execute("SELECT standard_code FROM geoai_metadata WHERE standard_code LIKE '% %' LIMIT 10")
    rows = cursor.fetchall()

    print("\nStandard codes containing spaces:")
    for row in rows:
        print(f"  {row[0]}")

    cursor.execute(
        "SELECT standard_code, REPLACE(REPLACE(standard_code, '/', '_'), '-', '_') as converted "
        "FROM geoai_metadata LIMIT 10"
    )
    rows = cursor.fetchall()

    print("\nConversion test:")
    for row in rows:
        print(f"  {row[0]} -> {row[1]}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"Error: {e}")
