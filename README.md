# GeoRAG Planning Assistant / GeoRAG 国土空间规划智能检索与可视化助手

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Node](https://img.shields.io/badge/Node-18%2B-green.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

GeoRAG Planning Assistant is a retrieval-augmented assistant for spatial planning and surveying standards. It combines semantic document search, LLM-based Q&A, citation-backed answers, and 2D/3D geospatial visualization.

GeoRAG 国土空间规划智能检索与可视化助手面向国土空间规划、测绘标准与地理信息政策资料，提供文档语义检索、大模型问答、引用溯源和二维/三维地图联动能力。

## Live Demo / 在线演示

- Demo: [https://8.156.85.7/](https://8.156.85.7/)
- Click `访客体验` to enter without registration.
- Visitor mode supports retrieval, map exploration, citations, and limited AI answers. When the AI quota is used up, search results remain available.

## Features / 功能

- Document ingestion and chunking for planning, surveying, and GIS standards.
- Vector retrieval over standards, policies, and technical documents.
- LLM Q&A with document citations and follow-up context.
- 2D/3D map visualization with OpenLayers and Cesium.
- Backend APIs for search, spatial data, documents, authentication, and system status.

- 标准文档切分、清洗与向量化入库。
- 面向标准、规范、政策资料的语义检索。
- 支持引用来源和上下文追问的大模型问答。
- 基于 OpenLayers 与 Cesium 的二维/三维地图展示。
- 提供检索、空间、文档、认证和系统管理相关 API。

## Tech Stack / 技术栈

- Backend: FastAPI, SQLAlchemy Async, PostgreSQL, pgvector, PostGIS, MySQL, Redis.
- Frontend: React 19, TypeScript, Vite, OpenLayers, Cesium, Zustand.
- Data services: PostgreSQL stores vector and spatial data in tables such as `policy_chunks` and `spatial_regions`; MySQL stores standard metadata in `disaster_knowledge.geoai_metadata`.

MinIO is currently reserved for future object storage and source-document download flows. It is not required for the main retrieval and visualization path.

MinIO 当前作为后续对象存储和源文档下载能力预留，不是主检索与可视化链路的必需依赖。

## Architecture / 架构概览

```text
geo-rag-planning-assistant/
├─ Backend/                  # FastAPI backend entrypoint: Backend/main.py
│  ├─ main.py
│  └─ app/
├─ frontend/                 # React + Vite frontend
│  ├─ src/
│  └─ package.json
├─ src/geoai/                # Legacy scripts and modules
├─ scripts/                  # Data processing and deployment scripts
├─ docs/                     # Product, deployment, and release docs
└─ docker-compose.yml
```

## Quick Start / 快速开始

### Backend / 后端

```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Before starting the backend, configure usable PostgreSQL and MySQL connections in `Backend/.env`. PostgreSQL is required for vector and spatial retrieval data; MySQL is required for standards metadata. The backend fails fast if either core database is unavailable.

启动后端前，请在 `Backend/.env` 中配置可用的 PostgreSQL 和 MySQL。PostgreSQL 用于向量/空间检索数据，MySQL 用于标准元数据；任一核心数据库不可用时后端会启动失败。

### Frontend / 前端

```bash
cd frontend
npm install
npm run dev
```

The frontend uses `/api` by default. During local development, Vite proxies `/api` to `http://localhost:8000`; use `VITE_API_URL` only for cross-origin or special deployment scenarios.

前端默认请求同源 `/api`。本地开发时 Vite 会把 `/api` 代理到 `http://localhost:8000`；只有跨域或特殊部署时才需要通过 `VITE_API_URL` 覆盖。

### Docker

```bash
docker compose up -d
```

## Documentation / 文档

- Product requirements / 产品需求：`docs/requirement.md`
- Backend guide / 后端说明：`Backend/README.md`
- Frontend guide / 前端说明：`frontend/README.md`
- Deployment guide / 部署说明：`docs/DEPLOY.md`
- Release workflow / 发布流程：`docs/RELEASE_WORKFLOW.md`

## Security / 安全说明

- Example configuration values are placeholders and must not be used in production.
- Real credentials should be injected through local `.env` files or deployment platform secret management.
- Do not commit real API keys, database passwords, or server credentials.

- 仓库示例配置均应使用占位符。
- 生产凭据请通过本地 `.env` 或部署平台密钥管理注入。
- 不要提交真实 API Key、数据库密码或服务器凭据。

## License

MIT
