# GeoAI 空间规划智能检索与可视化系统

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node](https://img.shields.io/badge/Node-18%2B-green.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

本项目是一个面向“测绘/国土空间规划标准文档”的 GeoAI 全栈系统：  
文档向量化入库 -> 语义检索 -> 大模型生成回答 -> 地图联动展示（2D/3D）。

## 当前代码现状（已对齐仓库）

### 技术栈
- 后端：FastAPI + SQLAlchemy Async + PostgreSQL(pgvector/PostGIS) + MySQL + Redis + MinIO
- 前端：React 19 + TypeScript + Vite + OpenLayers + Cesium + Zustand
- 数据处理：Python 脚本（文档解压、切分、向量化、空间数据导入）

### 关键目录
```text
ragAI知识库/
├─ Backend/                  # 主后端（前端当前对接的是这套 /api）
│  ├─ main.py
│  └─ app/
│     ├─ api/                # search/spatial/documents/system 路由
│     ├─ services/           # 业务逻辑（检索、空间、文档）
│     └─ core/               # 配置、数据库、LLM 配置
├─ frontend/                 # React 前端
│  ├─ src/
│  │  ├─ App.tsx
│  │  ├─ components/
│  │  ├─ services/
│  │  └─ store/
│  └─ package.json
├─ src/geoai/                # 旧版/并行实现（含另一套 api.main）
├─ scripts/                  # 数据构建与校验脚本入口
├─ docs/
│  └─ requirement.md
└─ docker-compose.yml
```

### 现有功能完成度
- 已有：
  - 向量检索主链路（query -> embedding -> pgvector 检索 -> 结果返回）
  - 检索增强回答（LLM 生成回答、支持历史上下文）
  - 前端 2D/3D 地图与聊天面板联动框架
  - 省级行政区数据查询接口（`/api/spatial/provinces`）
- 部分完成 / 占位：
  - 文档管理部分接口仍为示例或 TODO
  - 空间分析大多数接口仍为模拟实现
  - 部分推荐、反馈、日志统计接口未完全落地

## 重要说明（避免联调踩坑）

仓库当前存在“两套后端入口”：
- `Backend/main.py`：功能较完整，前端服务层按 `/api/search/*` 对接这一套
- `src/geoai/api/main.py`：较轻量，接口集合不同

`docker-compose.yml` 中 backend 默认命令是：
```bash
uvicorn src.geoai.api.main:app --host 0.0.0.0 --port 8000 --reload
```
如果你要与当前 `frontend/src/services/*` 无缝联调，建议启动 `Backend/main.py` 这套。

## 本地开发（推荐）

### 1. 后端（Backend 方案）
```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- Swagger: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

### 2. 前端
```bash
cd frontend
npm install
npm run dev
```

默认运行在：
- `http://localhost:3000`

前端 API 基础地址来自：
- `frontend/src/lib/api/config.ts`
- 环境变量：`VITE_API_URL`（默认 `http://localhost:8000/api`）

### 3. 数据依赖
你至少需要准备：
- PostgreSQL（含 `vector`、`postgis` 扩展）
- MySQL（标准元数据）
- 可选：Redis、MinIO

## Docker 方式

项目已提供 `docker-compose.yml`，但目前默认走 `src.geoai.api.main`。  
如需与现有前端完全对齐，请先确认 backend 启动入口与前端 API 契约一致。

## 测试与脚本

```bash
# 单元测试
pytest tests/unit/

# 常用脚本
python scripts/build_vector_db.py
python scripts/import_spatial_data.py
python scripts/verify_data.py
```

## 文档

- 需求说明：[`docs/requirement.md`](docs/requirement.md)
- 后端说明：[`Backend/README.md`](Backend/README.md)
- 前端说明：[`frontend/README.md`](frontend/README.md)

## 安全提示

当前仓库中仍存在默认密钥/默认账号配置示例（含 API Key 占位或历史值）。  
请在部署前统一迁移到 `.env` 并轮换密钥。

## License

MIT，详见 [`LICENSE`](LICENSE)。
