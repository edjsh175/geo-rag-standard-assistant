# GeoRAG Planning Assistant Backend / GeoRAG 后端服务

## Overview / 概述

The backend is a FastAPI service for GeoRAG Planning Assistant. It provides retrieval, spatial, document, authentication, and system APIs for the planning standards assistant.

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
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

`Backend/.env` must point to usable PostgreSQL and MySQL instances. PostgreSQL stores vector and spatial retrieval data such as `policy_chunks`; MySQL stores standard metadata in `disaster_knowledge.geoai_metadata`. The backend fails fast if either core database is unavailable. Redis is used as a cache dependency, but the backend can still start when Redis is unavailable.

`Backend/.env` 必须指向可用的 PostgreSQL 和 MySQL。PostgreSQL 存储 `policy_chunks` 等向量/空间检索数据，MySQL 使用 `disaster_knowledge.geoai_metadata` 存储标准元数据；任一核心数据库不可用时后端会启动失败。Redis 仅作为缓存依赖，不可用时后端仍可启动。

API docs:

- Swagger: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

MinIO is reserved for future document object storage and download flows. It is not required for the current main path.

MinIO 当前只为后续文档对象存储和下载流程预留，不是主流程必需依赖。

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
