# GeoRAG 后端适配前测试基线

日期：2026-09-20

基线提交：`833851e`

## 运行环境

- Python：`3.12.10`
- 隔离环境：项目 worktree 内 `.venv`
- 测试入口：`.venv\Scripts\python.exe -m pytest Backend\tests -q`

## 环境建立过程

初始机器仅安装 Python 3.11，而项目 `pyproject.toml` 声明 `requires-python = ">=3.12"`。因此先安装用户级 Python 3.12.10，再创建 `.venv`。

直接执行：

```text
pip install -e ".[dev]"
```

后首次测试收集出现 20 个 import error，主要缺少：

- `pydantic_settings`
- `minio`

继续检查发现，仓库当前存在依赖真源分裂：

- 顶层 `pyproject.toml` / `requirements.txt`；
- `Backend/requirements.txt`。

Backend 实际代码直接 import 的多项依赖只声明在 `Backend/requirements.txt` 中，包括 `pydantic-settings`、`SQLAlchemy`、`Redis`、`MinIO`、`Celery` 等。因此首次 20 个 collection error 属于**测试环境未完整建立**，不能解释为业务代码失败。

同时，`Backend/requirements.txt` 还把 `sentence-transformers` 与 `chromadb` 作为历史依赖整体声明。为避免仅建立测试基线时额外安装 Torch/Chroma 并污染本次“PostgreSQL/pgvector 单一正式索引”的迁移目标，基线环境只补齐了当前 Backend 代码实际 import、测试收集所需的后端依赖，而没有为了基线安装 Chroma。

该依赖真源分裂属于既有工程问题，后续应在本次适配完成后单独收敛；它不作为 Agent 架构迁移的隐式扩展任务。

## 原始测试基线

收集到：`64` 个测试。

最终执行：

```text
.venv\Scripts\python.exe -m pytest Backend\tests -q
```

结果：

```text
64 passed
```

未发现既有失败测试。

存在但不阻塞基线的既有 warning：

- Pydantic v2 对 class-based `Config` 的弃用提示；
- `Field(min_items/max_items)` 弃用提示；
- Pydantic v1 `@validator` 弃用提示；
- `datetime.utcnow()` 弃用提示。

这些 warning 在本次业务改造前已存在，不应被误归因为后续 Agent 迁移回归。

## OpenAPI 基线

当前 FastAPI `app.openapi()` 已按 key 排序冻结到：

```text
docs/superpowers/baselines/2026-09-20-search-openapi.json
```

后续 Task 7 必须以该快照校验 `/api/search/query`、`SearchRequest`、`SearchResponse` 的向后兼容，而不是凭印象判断旧 API 是否仍可用。
