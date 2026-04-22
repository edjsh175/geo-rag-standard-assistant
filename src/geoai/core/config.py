"""
Project configuration module.
Load sensitive values from environment variables first.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ================= AI / Embedding =================
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embedding-3")
VECTOR_DIMENSION = int(os.getenv("VECTOR_DIMENSION", "2048"))

# ================= PostgreSQL =================
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "geoai_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}",
)

# ================= Redis =================
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# ================= MinIO =================
MINIO_CONFIG = {
    "endpoint": os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
    "access_key": os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    "secret_key": os.getenv("MINIO_SECRET_KEY", ""),
    "secure": os.getenv("MINIO_SECURE", "False").lower() == "true",
    "bucket": os.getenv("MINIO_BUCKET", "geoai-assets"),
}

# ================= Paths =================
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_CONFIG_DIR)))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
EXTERNAL_DATA_DIR = os.path.join(DATA_DIR, "external")

COMPRESSED_DIR = os.getenv("COMPRESSED_DIR", r"D:\work\shixi\py\md_output")
EXTRACT_DIR = os.path.join(PROCESSED_DATA_DIR, "md_extracted")
SAFE_EXTRACT_DIR = os.path.join(PROCESSED_DATA_DIR, "md_extracted_safe")
MD_DIR = EXTRACT_DIR

SHPFILE_DIR = os.path.join(EXTERNAL_DATA_DIR, "shpfile")
SHENG_2022_SHP = os.path.join(SHPFILE_DIR, "sheng2022", "sheng2022.shp")

# ================= MySQL =================
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "disaster_knowledge"),
    "charset": "utf8mb4",
}

MYSQL_URL = os.getenv(
    "MYSQL_URL",
    f"mysql://{MYSQL_CONFIG['user']}:{MYSQL_CONFIG['password']}@{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}",
)

MYSQL_TABLE = "standard_norm_detail"
MYSQL_STANDARD_CODE_FIELD = "standard_code"
MYSQL_RELEASE_DATE_FIELD = "release_date"
MYSQL_IMPLEMENT_DATE_FIELD = "implement_date"
MYSQL_DRAFT_UNIT_FIELD = "draft_unit"
MYSQL_KEYWORD_FIELD = "keyword"

# ================= Archive =================
SUPPORTED_ARCHIVE_EXTENSIONS = [".zip", ".rar", ".7z"]
FORCE_EXTRACT = False
DELETE_AFTER_EXTRACT = False
RECURSIVE_EXTRACT = True

# ================= Text Split =================
HEADERS_TO_SPLIT_ON = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
