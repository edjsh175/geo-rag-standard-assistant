# GeoAI 空间规划智能检索与可视化系统 - 后端

基于 FastAPI 的后端服务，为 GeoAI 空间规划智能检索与可视化系统提供 API 支持。

## 项目概述

GeoAI 系统是一个基于大模型和空间数据库的智能检索与可视化平台，支持：

- **智能文档检索**：基于语义的文档搜索
- **空间分析**：地理编码、缓冲区分析、空间查询
- **知识库构建**：文档向量化与存储
- **可视化服务**：空间数据可视化接口

## 技术栈

- **Web框架**: FastAPI + Uvicorn
- **数据库**: PostgreSQL (pgvector + PostGIS) + MySQL + Redis
- **向量数据库**: pgvector / ChromaDB
- **大模型**: OpenAI / 智谱AI / DeepSeek
- **地理空间**: GeoAlchemy2, Shapely, GeoPandas
- **部署**: Docker, Docker Compose

## 项目结构

```
/GeoAI_Backend
├── app/
│   ├── api/          # API路由接口
│   │   ├── search_routes.py     # 智能检索接口
│   │   ├── spatial_routes.py    # 空间分析接口
│   │   ├── document_routes.py   # 文档管理接口
│   │   └── system_routes.py     # 系统管理接口
│   ├── core/         # 核心配置
│   │   ├── config.py            # 应用配置
│   │   ├── database.py          # 数据库连接管理
│   │   └── llm_config.py        # 大模型配置
│   ├── models/       # 数据模型
│   │   ├── search_models.py     # 检索相关模型
│   │   ├── spatial_models.py    # 空间相关模型
│   │   └── document_models.py   # 文档相关模型
│   └── services/     # 业务服务
│       ├── search_service.py    # 检索服务
│       └── __init__.py
├── main.py           # FastAPI 应用入口
├── requirements.txt  # Python 依赖
├── .env.example      # 环境变量示例
└── README.md         # 项目说明
```

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd GeoAI_Backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制环境变量示例文件
cp .env.example .env

# 编辑 .env 文件，配置数据库和大模型API密钥
```

### 3. 数据库初始化

```bash
# 启动 PostgreSQL、MySQL 和 Redis
docker-compose up -d

# 创建数据库和扩展
# PostgreSQL: 需要创建 geoai_db 数据库，并启用 postgis 和 vector 扩展
# MySQL: 需要创建 geoai_metadata 数据库
```

### 4. 启动服务

```bash
# 开发模式（热重载）
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 5. 访问API文档

服务启动后，访问以下地址查看API文档：

- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## API 接口

### 智能检索接口
- `POST /api/search/query` - 智能文档检索
- `POST /api/search/hybrid` - 混合检索（文本+空间）
- `GET /api/search/suggest` - 搜索建议
- `GET /api/search/similar/{doc_id}` - 相似文档查找

### 空间分析接口
- `POST /api/spatial/query` - 空间查询
- `POST /api/spatial/geocode` - 地理编码（地址转坐标）
- `POST /api/spatial/reverse-geocode` - 逆地理编码（坐标转地址）
- `GET /api/spatial/distance` - 计算两点距离

### 文档管理接口
- `POST /api/documents/upload` - 上传文档
- `GET /api/documents/list` - 文档列表
- `GET /api/documents/{doc_id}` - 文档详情
- `DELETE /api/documents/{doc_id}` - 删除文档

### 系统管理接口
- `GET /api/system/info` - 系统信息
- `GET /api/system/health` - 健康检查
- `GET /api/system/config` - 配置信息
- `GET /api/system/metrics` - 系统指标

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t geoai-backend .

# 运行容器
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name geoai-backend \
  geoai-backend
```

### Docker Compose 部署

```bash
# 使用 docker-compose.yml 启动所有服务
docker-compose up -d
```

## 开发指南

### 添加新的API接口

1. 在 `app/api/` 目录下创建新的路由文件
2. 在 `app/api/__init__.py` 中注册路由
3. 在 `app/models/` 目录下创建对应的数据模型
4. 在 `app/services/` 目录下实现业务逻辑

### 数据库迁移

```bash
# 使用 Alembic 进行数据库迁移
alembic init alembic
alembic revision --autogenerate -m "描述变更"
alembic upgrade head
```

### 测试

```bash
# 运行测试
pytest

# 生成测试覆盖率报告
pytest --cov=app --cov-report=html
```

## 配置说明

详细配置请参考 `app/core/config.py` 和 `.env.example` 文件。

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 联系方式

如有问题或建议，请通过以下方式联系：

- 项目仓库: <repository-url>
- 问题跟踪: <issues-url>