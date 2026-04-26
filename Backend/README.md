# GeoAI Backend

## 概述
GeoAI 后端基于 FastAPI，提供：
- 智能检索 API（`/api/search/*`）
- 空间相关 API（`/api/spatial/*`）
- 文档管理 API（`/api/documents/*`）
- 系统管理 API（`/api/system/*`）

## 运行入口
唯一联调入口：`Backend/main.py`

## 本地启动
```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

`Backend/.env` 必须指向可用的 PostgreSQL 和 MySQL。PostgreSQL 存储 `policy_chunks` 向量/空间检索数据，MySQL 使用 `disaster_knowledge.geoai_metadata` 存储标准元数据；任一核心数据库不可用时后端会启动失败。Redis 仅作为缓存依赖，不可用时后端仍可启动。

API 文档：
- Swagger: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

MinIO 当前不是必需依赖，只为后续文档对象存储和下载流程预留。

## 环境变量
请复制 `.env.example` 为 `.env` 后填写实际值。
不要将真实密钥提交到仓库。

## 关键目录
```text
Backend/
├─ main.py
├─ requirements.txt
├─ .env.example
└─ app/
   ├─ api/
   ├─ services/
   ├─ models/
   └─ core/
```
