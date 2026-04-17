import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from redis import asyncio as redis
from minio import Minio
from minio.error import S3Error

from geoai.core.config import REDIS_URL, MINIO_CONFIG

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局客户端
redis_client: redis.Redis = None
minio_client: Minio = None

async def init_minio():
    """初始化 MinIO Bucket 并设置公共权限"""
    global minio_client
    try:
        minio_client = Minio(
            MINIO_CONFIG["endpoint"],
            access_key=MINIO_CONFIG["access_key"],
            secret_key=MINIO_CONFIG["secret_key"],
            secure=MINIO_CONFIG["secure"]
        )
        
        bucket_name = MINIO_CONFIG["bucket"]
        if not minio_client.bucket_exists(bucket_name):
            logger.info(f"Creating bucket: {bucket_name}")
            minio_client.make_bucket(bucket_name)
            
            # 设置公共读取策略
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                        "Resource": [f"arn:aws:s3:::{bucket_name}"]
                    },
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
                    }
                ]
            }
            minio_client.set_bucket_policy(bucket_name, json.dumps(policy))
            logger.info(f"Public policy applied to bucket: {bucket_name}")
        else:
            logger.info(f"Bucket {bucket_name} already exists.")
            
    except S3Error as e:
        logger.error(f"MinIO initialization failed: {e}")
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up GeoAI API...")
    
    # 初始化 Redis (Strict Async)
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis_client.ping()
        logger.info("Connected to Redis successfully.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
    
    # 初始化 MinIO
    await init_minio()
    
    yield
    
    # Shutdown
    logger.info("Shutting down GeoAI API...")
    if redis_client:
        await redis_client.close()

app = FastAPI(
    title="GeoAI Spatial Visualization System API",
    description="Enterprise-grade architecture for GeoAI with Redis and MinIO.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    return {"message": "Welcome to GeoAI API", "status": "running"}

@app.get("/health")
async def health_check():
    health = {"status": "ok", "redis": "unknown", "minio": "unknown"}
    
    # Check Redis
    try:
        await redis_client.ping()
        health["redis"] = "connected"
    except Exception:
        health["redis"] = "disconnected"
        
    # Check MinIO
    try:
        if minio_client.bucket_exists(MINIO_CONFIG["bucket"]):
            health["minio"] = "connected"
    except Exception:
        health["minio"] = "disconnected"
        
    return health

# --- 示例接口：RAG 聊天记忆 ---
@app.post("/chat/session/{user_id}")
async def save_session_memory(user_id: str, content: str):
    """保存会话缓存（1小时过期）"""
    key = f"rag_session_{user_id}"
    await redis_client.set(key, content, ex=3600)
    return {"message": "Session memory saved"}

@app.get("/chat/session/{user_id}")
async def get_session_memory(user_id: str):
    """读取会话缓存"""
    key = f"rag_session_{user_id}"
    content = await redis_client.get(key)
    if not content:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"user_id": user_id, "content": content}

# --- 示例接口：MinIO 资产访问 ---
@app.get("/assets/{filename}")
async def get_asset_url(filename: str):
    """获取 MinIO 中的资产访问链接 (由于是 Public，直接返回拼接 URL 即可)"""
    # 在生产环境下通常返回 CDN 或 签名 URL，此处根据配置返回直连 URL
    endpoint = MINIO_CONFIG["endpoint"]
    bucket = MINIO_CONFIG["bucket"]
    if MINIO_CONFIG["secure"]:
        url = f"https://{endpoint}/{bucket}/{filename}"
    else:
        url = f"http://{endpoint}/{bucket}/{filename}"
    return {"url": url}
