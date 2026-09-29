# GeoRAG Standard Assistant Backend / GeoRAG 后端服务

## Overview / 概述

The backend is a FastAPI service for GeoRAG Standard Assistant. It provides retrieval, spatial, document, authentication, and system APIs for the planning standards assistant.

GeoRAG 后端基于 FastAPI，为国土空间规划与测绘标准智能助手提供检索、空间、文档、认证和系统管理接口。

Core API groups:

- Search APIs: `/api/search/*`
- Spatial APIs: `/api/spatial/*`
- Document APIs: `/api/documents/*`
- Auth APIs: `/api/auth/*`
- System APIs: `/api/system/*`

## Entrypoint / 运行入口

The unified backend entrypoint is `Backend/main.py`.

统一联调与部署入口：`Backend/main.py`

## Local Development / 本地启动

```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
ollama pull qwen3-embedding:4b-q4_K_M
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

`Backend/.env` must point to usable PostgreSQL and MySQL instances. PostgreSQL stores vector and spatial retrieval data such as `policy_chunks`; MySQL stores standard metadata in `geoai_knowledge.geoai_metadata`. The backend fails fast if either core database is unavailable. Redis is used as a cache dependency, but the backend can still start when Redis is unavailable.

`Backend/.env` 必须指向可用的 PostgreSQL 和 MySQL。PostgreSQL 存储 `policy_chunks` 等向量/空间检索数据，MySQL 使用 `geoai_knowledge.geoai_metadata` 存储标准元数据；任一核心数据库不可用时后端会启动失败。Redis 仅作为缓存依赖，不可用时后端仍可启动。

默认向量模型为本地 Ollama 上的 `qwen3-embedding:4b-q4_K_M`，首次运行前执行 `ollama pull qwen3-embedding:4b-q4_K_M`。项目检索向量固定为 2048 维；切换 embedding 模型后，必须用同一模型重新生成已有 `policy_chunks` 的向量。

API docs:

- Swagger: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

MinIO object storage is required when `DOCUMENT_UPLOAD_ENABLED=True` for uploaded document persistence, file downloads, and asynchronous Celery worker indexing (`index_document_job`). If running in a minimal development setup for read-only standards retrieval (`policy_chunks`), document upload may be disabled (`DOCUMENT_UPLOAD_ENABLED=False`) without running MinIO.

MinIO 对象存储在启用上传文档闭环（`DOCUMENT_UPLOAD_ENABLED=True`）时为必需依赖，用于原始文档持久化、下载以及 Celery 异步索引 Worker（`index_document_job`）的数据解析。在仅运行本地只读标准库（`policy_chunks`）检索的最小开发调试环境中，可配置 `DOCUMENT_UPLOAD_ENABLED=False` 暂时不运行 MinIO。

## Configuration / 环境变量

Copy `.env.example` to `.env`, then fill in deployment-specific values. Never commit real secrets.

请复制 `.env.example` 为 `.env` 后填写实际值。不要将真实密钥提交到仓库。

## Key Directories / 关键目录

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
