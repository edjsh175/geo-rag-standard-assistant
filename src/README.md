# src/ 模块架构定位与边界说明

## 模块定位与职责划分

根据项目架构演进规范，本仓库中存在两组后端代码结构，其职责分工与边界如下：

1. **`Backend/app/`（生产环境核心后端）**：
   - 承载现代 FastAPI 服务、统一认证与权限系统。
   - 承载 Agent Runtime、LangGraph 规划图、分布式会话锁（PostgreSQL Advisory Lock）。
   - 承载 GeoSQL 引擎、PostGIS 空间拓扑分析、RFC 7807 统一错误模型与大文件分片上传服务。
   - 是系统线上部署、API 调用与 36-Task E2E 自动化评测的**唯一生产执行入口**。

2. **`src/geoai/`（离线数据处理与 ETL 工具箱）**：
   - 承载历史与离线批处理脚本：规划规范数据爬虫（`crawler.py`）、离线文档解析（`extractor.py`）、压缩包批量提取处理（`processor.py`）。
   - 承载独立桌面端辅助工具（`web/gui.py`）。
   - 该目录作为离线运维与数据准备支持库存在，不直接参与在线 Agent 运行时与前端交互。

3. **`scripts/`（运维与评测命令行入口）**：
   - 提供连接 `src/geoai`（如 `build_vector_db.py`, `import_spatial_data.py`）或评估 `Backend`（如 `benchmark_concurrency.py`, `run_retrieval_eval.py`）的独立 CLI 脚本。
