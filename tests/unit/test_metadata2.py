import pymysql
import config
import datetime

# 从config读取
MYSQL_CONFIG = config.MYSQL_CONFIG
MYSQL_TABLE = config.MYSQL_TABLE
MYSQL_STANDARD_CODE_FIELD = config.MYSQL_STANDARD_CODE_FIELD
MYSQL_RELEASE_DATE_FIELD = config.MYSQL_RELEASE_DATE_FIELD
MYSQL_IMPLEMENT_DATE_FIELD = config.MYSQL_IMPLEMENT_DATE_FIELD
MYSQL_DRAFT_UNIT_FIELD = config.MYSQL_DRAFT_UNIT_FIELD
MYSQL_KEYWORD_FIELD = config.MYSQL_KEYWORD_FIELD

def get_standard_metadata(mysql_conn, standard_code):
    """从 MySQL 查询标准的完整元数据"""
    if not mysql_conn:
        return None

    try:
        with mysql_conn.cursor() as cursor:
            # 构建查询语句，获取所有重要元数据字段
            # 支持多种标准号格式匹配（下划线/斜杠/连字符）
            query = f"""
                SELECT
                    {MYSQL_RELEASE_DATE_FIELD},
                    {MYSQL_IMPLEMENT_DATE_FIELD},
                    {MYSQL_DRAFT_UNIT_FIELD},
                    {MYSQL_KEYWORD_FIELD},
                    chinese_name,
                    english_name,
                    standard_status,
                    release_unit,
                    charge_unit,
                    replace_standard,
                    application_scope
                FROM {MYSQL_TABLE}
                WHERE {MYSQL_STANDARD_CODE_FIELD} = %s
                   OR REPLACE(REPLACE({MYSQL_STANDARD_CODE_FIELD}, '/', '_'), '-', '_') = REPLACE(REPLACE(%s, '/', '_'), '-', '_')
                   OR REPLACE({MYSQL_STANDARD_CODE_FIELD}, '_', '/') = %s
                   OR REPLACE({MYSQL_STANDARD_CODE_FIELD}, '/', '_') = %s
                   OR REPLACE(%s, '_', '/') = REPLACE({MYSQL_STANDARD_CODE_FIELD}, '_', '/')
                   OR REPLACE(%s, '_', '/') = {MYSQL_STANDARD_CODE_FIELD}
                LIMIT 1
            """
            cursor.execute(query, (standard_code, standard_code, standard_code, standard_code, standard_code, standard_code))
            result = cursor.fetchone()

            if result:
                # 解包结果（11个字段）
                (release_date, implement_date, draft_unit, keyword,
                 chinese_name, english_name, standard_status, release_unit,
                 charge_unit, replace_standard, application_scope) = result

                # 处理日期格式
                def format_date(date_val):
                    if isinstance(date_val, datetime.date):
                        return date_val.strftime("%Y-%m-%d")
                    elif date_val is None:
                        return "未知"
                    else:
                        return str(date_val)

                # 处理空值
                def format_text(text_val):
                    if text_val is None:
                        return "未知"
                    return str(text_val)

                metadata = {
                    "release_date": format_date(release_date),
                    "implement_date": format_date(implement_date),
                    "draft_unit": format_text(draft_unit),
                    "keyword": format_text(keyword),
                    "chinese_name": format_text(chinese_name),
                    "english_name": format_text(english_name),
                    "standard_status": format_text(standard_status),
                    "release_unit": format_text(release_unit),
                    "charge_unit": format_text(charge_unit),
                    "replace_standard": format_text(replace_standard),
                    "application_scope": format_text(application_scope)
                }

                print(f"[MySQL] 查询到标准号 {standard_code}:")
                print(f"       发布日期: {metadata['release_date']}, 实施日期: {metadata['implement_date']}")
                print(f"       起草单位: {metadata['draft_unit']}, 关键词: {metadata['keyword']}")
                print(f"       中文名称: {metadata['chinese_name'][:30]}...")

                return metadata
            else:
                print(f"[MySQL 警告] 未找到标准号 {standard_code} 的元数据")
                # 返回默认元数据
                return {
                    "release_date": "未知",
                    "implement_date": "未知",
                    "draft_unit": "未知",
                    "keyword": "未知",
                    "chinese_name": "未知",
                    "english_name": "未知",
                    "standard_status": "未知",
                    "release_unit": "未知",
                    "charge_unit": "未知",
                    "replace_standard": "未知",
                    "application_scope": "未知"
                }
    except Exception as e:
        print(f"[MySQL 错误] 查询失败: {e}")
        # 返回默认元数据
        return {
            "release_date": "未知",
            "implement_date": "未知",
            "draft_unit": "未知",
            "keyword": "未知",
            "chinese_name": "未知",
            "english_name": "未知",
            "standard_status": "未知",
            "release_unit": "未知",
            "charge_unit": "未知",
            "replace_standard": "未知",
            "application_scope": "未知"
        }

try:
    conn = pymysql.connect(**MYSQL_CONFIG)
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