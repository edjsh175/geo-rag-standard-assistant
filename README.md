# GeoAI 空间规划智能检索与可视化系统

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![requirement](https://img.shields.io/badge/requirement-V1.0-blueviolet)](docs/requirement.md)

> 国家级标准与空间数据融合的智能检索系统，支持地理空间规划决策

## 🚀 项目概述

GeoAI是一个结合了国家标准知识库、地理空间数据（GIS）和人工智能检索技术的企业级应用系统。项目从桌面爬虫应用演进为完整的WebGIS解决方案，为空间规划决策提供智能支持。

### 核心功能

- **📚 国家标准知识库**: 自动爬取、解析和向量化国家标准文档
- **🗺️ 空间数据处理**: 支持PostGIS的地理空间数据导入与分析
- **🔍 智能检索**: 基于语义相似度的智能检索与推荐
- **🌐 WebGIS可视化**: 基于OpenLayers的地理数据交互式可视化
- **📊 数据分析**: 空间规划决策支持与数据洞察

## 📁 项目结构

```
geoai/
├── src/                           # 源代码
│   ├── geoai/                     # 主包
│   │   ├── core/                  # 核心配置与工具
│   │   ├── data/                  # 数据处理模块
│   │   │   ├── extractor.py       # 数据提取
│   │   │   ├── crawler.py         # 网络爬虫
│   │   │   └── processor.py       # 向量化处理
│   │   ├── spatial/               # 空间数据处理
│   │   │   └── importer.py        # 空间数据导入
│   │   ├── api/                   # API接口 (预留)
│   │   ├── web/                   # Web与GUI
│   │   │   └── gui.py             # 桌面GUI应用
│   │   └── utils/                 # 工具函数
│   └── scripts/                   # 独立脚本
├── tests/                         # 测试目录
│   ├── unit/                      # 单元测试
│   └── integration/               # 集成测试
├── docs/                          # 文档
├── config/                        # 配置文件
│   ├── development.yaml           # 开发环境配置
│   ├── production.yaml            # 生产环境配置
│   ├── pachong.py                 # 爬虫配置
│   └── logging.conf               # 日志配置
├── data/                          # 数据目录
│   ├── raw/                       # 原始数据
│   ├── processed/                 # 处理后的数据
│   └── external/                  # 外部数据源
├── docker/                        # Docker配置
├── notebooks/                     # Jupyter笔记本
└── scripts/                       # 系统脚本
```

## 🛠️ 技术栈

### 后端核心
- **Python 3.11+**: 主编程语言
- **FastAPI**: 现代异步Web框架
- **PostgreSQL + PostGIS**: 空间数据库
- **pgvector**: 向量相似度搜索
- **MySQL**: 关系型数据库 (原始数据)

### 数据处理
- **Geopandas**: 地理空间数据处理
- **Pandas/Numpy**: 数据计算与分析
- **LangChain**: 文档处理与向量化
- **智谱AI Embedding**: 中文文本向量化

### 前端与可视化
- **Vue 3**: 前端框架
- **OpenLayers**: WebGIS地图引擎
- **Element Plus**: UI组件库
- **ECharts**: 数据可视化

### 开发工具
- **Poetry**: 依赖管理与打包
- **Black/isort**: 代码格式化
- **Flake8/pylint**: 代码质量检查
- **Pytest**: 测试框架
- **Git**: 版本控制

## 🚀 快速开始

### 环境要求

- Python 3.11+
- PostgreSQL 14+ with PostGIS extension
- MySQL 8.0+
- Node.js 18+ (前端开发)

### 安装步骤

1. **克隆项目**
   ```bash
   git clone <repository-url>
   cd geoai
   ```

2. **设置Python环境**
   ```bash
   # 使用Poetry (推荐)
   poetry install

   # 或使用传统方式
   python -m venv venv
   venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **数据库配置**
   ```bash
   # PostgreSQL (带PostGIS)
   createdb geoai_db
   psql -d geoai_db -c "CREATE EXTENSION postgis;"
   psql -d geoai_db -c "CREATE EXTENSION pgvector;"

   # MySQL
   mysql -u root -p
   CREATE DATABASE geoai_metadata;
   ```

4. **配置文件**
   ```bash
   cp config/development.yaml.example config/development.yaml
   # 编辑配置文件，填入数据库连接信息
   ```

5. **数据导入**
   ```bash
   # 导入空间数据 (Shapefile)
   python scripts/import_spatial_data.py

   # 构建向量知识库
   python scripts/build_vector_db.py
   ```

6. **启动服务**
   ```bash
   # 启动后端API
   uvicorn src.geoai.api.main:app --reload

   # 启动前端 (需要先构建)
   cd frontend
   npm install
   npm run dev
   ```

## 📊 数据流程

### 1. 数据采集阶段
- **网络爬虫**: 自动采集国家标准文档
- **文件解析**: 支持7z/rar/zip等压缩格式
- **元数据提取**: 提取文档标题、编号、发布机构等信息

### 2. 数据处理阶段
- **文本向量化**: 使用智谱AI生成文档向量
- **空间数据处理**: Shapefile导入PostGIS
- **数据关联**: 建立标准与空间数据的关联关系

### 3. 检索与可视化阶段
- **语义检索**: 基于向量相似度的智能搜索
- **空间查询**: 地理空间范围查询
- **WebGIS可视化**: 交互式地图展示

## 🔧 开发指南

### 代码规范
- 遵循PEP 8编码规范
- 使用类型注解 (Type Hints)
- 编写完整的文档字符串

### 测试
```bash
# 运行单元测试
pytest tests/unit/

# 运行集成测试
pytest tests/integration/

# 生成测试覆盖率报告
pytest --cov=src.geoai tests/
```

### 代码质量
```bash
# 代码格式化
black src/ tests/
isort src/ tests/

# 代码检查
flake8 src/
pylint src/geoai/

# 类型检查
mypy src/geoai/
```

## 🐳 Docker部署

### 开发环境
```bash
docker-compose up -d
```

### 生产环境
```bash
docker build -t geoai:latest .
docker run -p 8000:8000 geoai:latest
```

## 📈 项目路线图

### Phase 1: 基础平台 (当前)
- [x] 国家标准爬虫系统
- [x] 向量知识库构建
- [x] 空间数据导入
- [x] 桌面GUI应用

### Phase 2: Web系统开发
- [ ] FastAPI后端开发
- [ ] Vue3前端开发
- [ ] OpenLayers地图集成
- [ ] 智能检索API

### Phase 3: 高级功能
- [ ] 空间分析算法
- [ ] 预测模型集成
- [ ] 多用户权限系统
- [ ] API文档自动生成

## 🤝 贡献指南

1. Fork 项目仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📞 联系方式

- **项目负责人**: [您的姓名]
- **邮箱**: [您的邮箱]
- **文档**: [docs/](docs/)

## 🙏 致谢

- 感谢智谱AI提供的中文Embedding服务
- 感谢开源社区提供的各种工具和库
- 感谢所有为项目做出贡献的开发者

---

**GeoAI** - 让空间规划更智能 🚀