"""
配置文件，存放所有硬编码的配置项
"""

# ================= 智谱 AI 配置 =================
# 智谱 AI 的 API Key（用来生成向量 Embedding）
# 请替换为你的真实 API Key，获取地址：https://open.bigmodel.cn/usercenter/apikeys
ZHIPU_API_KEY = "f8acb3f151a0410897278c2a620abedf.OyMbU8EFpwYp6lsU"

# 向量模型配置
EMBEDDING_MODEL = "embedding-3"  # 智谱的通用向量模型，输出2048维
VECTOR_DIMENSION = 2048

# ================= 数据库配置 =================
DB_CONFIG = {
    "dbname": "geoai_db",    # 你的数据库名
    "user": "postgres",      # 默认用户名通常是 postgres
    "password": "postgres",
    "host": "localhost",
    "port": "5432"
}

# ================= 文件路径配置 =================
import os

# 项目根目录（配置文件所在位置：src/geoai/core/，根目录是三级父目录）
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_CONFIG_DIR)))

# 数据目录结构
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
EXTERNAL_DATA_DIR = os.path.join(DATA_DIR, "external")

# 存放压缩包的目录（包含 .zip, .rar, .7z 等文件）
COMPRESSED_DIR = r"D:\work\shixi\py\md_output"  # 实际压缩包目录

# 解压后的文件存放目录（新位置）
EXTRACT_DIR = os.path.join(PROCESSED_DATA_DIR, "md_extracted")

# 安全解压目录
SAFE_EXTRACT_DIR = os.path.join(PROCESSED_DATA_DIR, "md_extracted_safe")

# 向后兼容：MD_DIR 指向解压后的目录（供旧代码使用）
MD_DIR = EXTRACT_DIR

# Shapefile 数据路径
SHPFILE_DIR = os.path.join(EXTERNAL_DATA_DIR, "shpfile")
SHENG_2022_SHP = os.path.join(SHPFILE_DIR, "sheng2022", "sheng2022.shp")

# ================= MySQL 数据库配置 =================
MYSQL_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "root",  # 密码也是 root
    "database": "disaster_knowledge",
    "charset": "utf8mb4"
}

# MySQL 表名和字段配置（用于双库联动）
MYSQL_TABLE = "standard_norm_detail"
MYSQL_STANDARD_CODE_FIELD = "standard_code"
MYSQL_RELEASE_DATE_FIELD = "release_date"  # 发布日期
MYSQL_IMPLEMENT_DATE_FIELD = "implement_date"  # 实施日期
MYSQL_DRAFT_UNIT_FIELD = "draft_unit"  # 起草单位
MYSQL_KEYWORD_FIELD = "keyword"  # 关键词/分类

# ================= 解压配置 =================
# 支持的压缩文件扩展名
SUPPORTED_ARCHIVE_EXTENSIONS = ['.zip', '.rar', '.7z']

# 是否强制重新解压（如果解压目录已存在）
FORCE_EXTRACT = False

# 解压后是否删除压缩包（谨慎使用）
DELETE_AFTER_EXTRACT = False

# 是否递归解压（处理压缩包内的压缩包）
RECURSIVE_EXTRACT = True

# ================= 文本分割配置 =================
# Markdown 标题切分配置
HEADERS_TO_SPLIT_ON = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]

# 递归字符切分配置
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50