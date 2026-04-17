"""
配置文件，存放所有硬编码的配置项，优先从 .env 加载
"""
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# ================= 智谱 AI 配置 =================
# 智谱 AI 的 API Key
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "f8acb3f151a0410897278c2a620abedf.OyMbU8EFpwYp6lsU")

# 向量模型配置
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embedding-3")
VECTOR_DIMENSION = int(os.getenv("VECTOR_DIMENSION", "2048"))

# ================= 数据库配置 =================
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "geoai_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

DATABASE_URL = os.getenv("DATABASE_URL", f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")

# ================= Redis 配置 =================
REDIS_URL = os.getenv("REDIS_URL", "redis://:123456@127.0.0.1:6379/0")

# ================= MinIO 配置 =================
MINIO_CONFIG = {
    "endpoint": os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
    "access_key": os.getenv("MINIO_ACCESS_KEY", "admin"),
    "secret_key": os.getenv("MINIO_SECRET_KEY", "password123"),
    "secure": os.getenv("MINIO_SECURE", "False").lower() == "true",
    "bucket": os.getenv("MINIO_BUCKET", "geoai-assets")
}

# ================= 文件路径配置 =================
# 项目根目录
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_CONFIG_DIR)))

# 数据目录结构
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
EXTERNAL_DATA_DIR = os.path.join(DATA_DIR, "external")

# 存放压缩包的目录
COMPRESSED_DIR = os.getenv("COMPRESSED_DIR", r"D:\work\shixi\py\md_output")

# 解压后的文件存放目录
EXTRACT_DIR = os.path.join(PROCESSED_DATA_DIR, "md_extracted")

# 安全解压目录
SAFE_EXTRACT_DIR = os.path.join(PROCESSED_DATA_DIR, "md_extracted_safe")

# 向后兼容
MD_DIR = EXTRACT_DIR

# Shapefile 数据路径
SHPFILE_DIR = os.path.join(EXTERNAL_DATA_DIR, "shpfile")
SHENG_2022_SHP = os.path.join(SHPFILE_DIR, "sheng2022", "sheng2022.shp")

# ================= MySQL 数据库配置 =================
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "root"),
    "database": os.getenv("MYSQL_DATABASE", "disaster_knowledge"),
    "charset": "utf8mb4"
}

MYSQL_URL = os.getenv("MYSQL_URL", f"mysql://{MYSQL_CONFIG['user']}:{MYSQL_CONFIG['password']}@{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}")

# MySQL 表名和字段配置
MYSQL_TABLE = "standard_norm_detail"
MYSQL_STANDARD_CODE_FIELD = "standard_code"
MYSQL_RELEASE_DATE_FIELD = "release_date"
MYSQL_IMPLEMENT_DATE_FIELD = "implement_date"
MYSQL_DRAFT_UNIT_FIELD = "draft_unit"
MYSQL_KEYWORD_FIELD = "keyword"

# ================= 解压配置 =================
SUPPORTED_ARCHIVE_EXTENSIONS = ['.zip', '.rar', '.7z']
FORCE_EXTRACT = False
DELETE_AFTER_EXTRACT = False
RECURSIVE_EXTRACT = True

# ================= 文本分割配置 =================
HEADERS_TO_SPLIT_ON = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50