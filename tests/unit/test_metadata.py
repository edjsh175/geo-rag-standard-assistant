import sys
sys.path.insert(0, '.')

import pymysql
import config
from build_vector_db import get_standard_metadata

mysql_config = config.MYSQL_CONFIG

try:
    conn = pymysql.connect(**mysql_config)
    print("MySQL连接成功")

    # 测试标准号
    test_codes = [
        "DB1310_T 365-2025",
        "DB41/T 1979-2020",
        "DB11/T 1481-2024",
        "DB1310/T 365-2025",  # 假设的规范格式
        "DB1310_T 365-2025",
        "DB1310_T 365-2025".replace('_', '/'),
    ]

    for code in test_codes:
        print(f"\n查询标准号: {code}")
        metadata = get_standard_metadata(conn, code)
        if metadata:
            print(f"  发布日期: {metadata['release_date']}")
            print(f"  实施日期: {metadata['implement_date']}")
            print(f"  起草单位: {metadata['draft_unit']}")
            print(f"  关键词: {metadata['keyword']}")
        else:
            print("  未找到元数据")

    conn.close()

except Exception as e:
    print(f"错误: {e}")