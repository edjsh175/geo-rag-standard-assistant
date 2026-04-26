# GeoAI 空间规划智能检索与可视化系统

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node](https://img.shields.io/badge/Node-18%2B-green.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

GeoAI 面向测绘/国土空间规划标准文档，提供：
- 文档切分与向量化入库
- 语义检索 + 大模型回答
- 地图联动展示（OpenLayers 2D + Cesium 3D）

## 当前技术栈
- 后端：FastAPI、SQLAlchemy Async、PostgreSQL(pgvector/PostGIS)、MySQL、Redis
- 前端：React 19、TypeScript、Vite、OpenLayers、Cesium、Zustand

MinIO 目前不是当前运行路径的必需依赖，仅作为后续“AI 引用文档点击下载”对象存储流程的预留能力。

## 后端入口（已统一）
容器与联调统一使用：`Backend/main.py`
- 本地启动：`uvicorn main:app --reload --host 0.0.0.0 --port 8000`（在 `Backend` 目录）
- Docker 启动：`docker-compose.yml` 中 backend 命令已对齐 `Backend.main:app`

## 目录结构
```text
ragAI知识库/
├─ Backend/                  # 主后端（唯一联调入口）
│  ├─ main.py
│  └─ app/
├─ frontend/                 # React 前端
│  ├─ src/
│  └─ package.json
├─ src/geoai/                # 历史脚本与模块
├─ scripts/                  # 数据处理脚本
├─ docs/
│  └─ requirement.md
└─ docker-compose.yml
```

## 快速开始

### 后端
```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后端前必须在 `Backend/.env` 中配置可用的 PostgreSQL 和 MySQL。PostgreSQL 用于 `policy_chunks` 向量/空间检索数据，MySQL 用于 `standard_norm_detail` 标准元数据；任一核心数据库不可用时后端会启动失败。

### 前端
```bash
cd frontend
npm install
npm run dev
```

前端默认请求同源路径 `/api`。本地开发时 Vite 会把 `/api` 代理到 `http://localhost:8000`；只有跨域或特殊部署时才需要通过 `VITE_API_URL` 覆盖。

### Docker
```bash
docker compose up -d
```

## 安全说明
- 仓库中的示例配置已替换为占位符，不再包含真实密钥。
- 生产环境请通过本地 `.env` 或部署平台密钥管理注入凭据。

## 文档
- 产品需求：`docs/requirement.md`
- 后端说明：`Backend/README.md`
- 前端说明：`frontend/README.md`

## License
MIT
