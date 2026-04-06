"""测试标准号解析正则表达式"""
import re

test_cases = [
    "DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南",
    "DB15_T 3652—2024 沙化土地综合治理技术规程",
    "GB_T 32864-2016 滑坡防治工程勘查规范",
    "QX_T 185-2013 人工影响天气藏语术语",
    "CH_T 1012-2005 基础地理信息数字产品",
    "NB_T 10497-2021 水电工程水库塌岸与滑坡治理技术规程",
    "SL_T165-2019 滑坡涌浪模拟技术规程",
    "DB2203_T 13-2024 梨树模式黑土地保护",
    "DB22_T 3394-2022 黑土地质量",
    "GB_T 38509-2020 滑坡防治设计规范",
    "DB12_T 990—2020 建筑类建设工程规划许可证设计方案规范",
]

# 改进的正则表达式：
# 匹配中国标准号格式：
# - 字母开头（如 DB, GB, QX, CH, NB, SL）
# - 可选数字（如 DB61, DB2203）
# - 可选分隔符（/, _, .）
# - 可选字母（如 T, Z）
# - 可选空格
# - 数字-数字（年份）
# 例如：DB61_T 1533-2022, GB_T32864-2016, SL_T165-2019, DB2203_T 13-2024
pattern = r'^([A-Z]+\d*[/._]?[A-Z]*\s*\d+[—\-]\d+)(?:\s+(.+))?$'

print('=== 测试标准号解析 ===')
for test in test_cases:
    match = re.match(pattern, test, re.IGNORECASE)
    if match:
        standard_code = match.group(1).strip()
        standard_name = match.group(2) if match.group(2) else ""
        print(f'[成功] 输入: {test[:50]}...')
        print(f'       标准号: {standard_code}')
        print(f'       标准名: {standard_name[:30]}...' if standard_name else '       标准名: (空)')
    else:
        print(f'[失败] 输入: {test}')
    print()
