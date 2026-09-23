# GeoRAG Planning Assistant

> 面向国土空间规划、测绘标准与 GIS 资料理解场景的 **GeoAI Agent / RAG 应用**。
>
> 项目将知识检索、证据管理、Agent 自主规划、可选 Grounding Reviewer 与 2D/3D WebGIS 联动整合到同一工作台中，使系统不再停留在“检索后直接交给模型回答”的传统 RAG 流程。

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-TypeScript-61DAFB.svg)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector%20%2B%20PostGIS-336791.svg)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

## 项目定位

GeoRAG Planning Assistant 最初是一个面向规划标准、测绘规范和地理信息政策资料的传统 RAG 项目。当前后端已经完成 Agent 化升级：

- **Main Controller** 负责理解用户目标并决定下一步工具调用；
- **Agent Runtime** 只负责执行、状态、资源边界与发布契约，不预判业务语义；
- **Retrieval / Evidence** 将检索结果从候选证据推进到 Working Evidence，再冻结为最终回答唯一可用的 Frozen Evidence；
- **Answer Generator** 只能基于冻结证据生成结构化 Answer Units；
- **Grounding Reviewer** 可按开关启用，对每个 Answer Unit 与证据进行一一审查；
- **Publication Boundary** 决定答案是否允许真正发布；
- **MapAction** 作为结构化地图动作从后端传递给前端，与 OpenLayers / Cesium 地图联动。

项目保留了原有的 PostgreSQL / pgvector、PostGIS、文档上传与索引、2D/3D 地图、公开演示等产品能力，没有为了适配 Agent 架构整体替换原系统。

## 核心链路

```text
用户问题
  ↓
Search API / Application Service
  ↓
Agent Runtime
  ↓
Main Controller
  ↓
Tool Runtime
  ├─ retrieve_kb      检索知识库
  ├─ reuse_evidence   复用会话证据
  ├─ compose_answer   冻结回答证据
  ├─ import_vector_dataset  导入浏览器矢量数据
  ├─ set_layer_visibility   控制用户图层显隐
  ├─ set_vector_style       修改矢量图层样式
  ├─ fit_vector_layer       定位用户图层
  ├─ locate_map             定位地图视角
  ├─ clarify          请求用户澄清
  └─ limitation       安全结束当前任务
  ↓
RetrievalPort
  ↓
PostgreSQL + pgvector + PostGIS
  ↓
Evidence Ledger
  Working Evidence → Frozen Evidence Snapshot
  ↓
Answer Generator
  ↓
Optional Grounding Reviewer
  ↓
Publication Boundary
  ↓
Answer + Citations + MapAction
  ↓
React + OpenLayers / Cesium
```

这个链路的核心不是“增加几个 Agent 类”，而是重新划分职责：

> **模型负责语义判断，Runtime 负责确定性执行；知识回答只能来自冻结证据，任何未通过发布契约的 Candidate 都不能成为最终答案。**

## 关键设计

### 1. Agent Runtime：从一次性 RAG 调用到多步执行

传统流程通常是：

```text
问题 → 检索 → 拼 Prompt → LLM → 回答
```

当前 Agent 模式则是：

```text
问题
→ Controller 判断下一步
→ 调用工具
→ 获得 Observation
→ 更新 Working Evidence / Session
→ Controller 继续判断
→ 冻结证据
→ 生成并发布答案
```

Runtime 不通过关键词、意图枚举或实体特判替模型做语义决策。它只维护：

- Tool 调用生命周期；
- Session / Turn / Trace；
- Working Evidence；
- 物理资源保险丝；
- Structured Candidate 协议；
- 最终发布边界。

### 2. Evidence 生命周期：回答依据不是“检索结果列表”

检索结果进入系统后不会直接交给最终回答模型，而是经过明确的证据生命周期：

```text
Retrieval Candidate
  ↓
Evidence Ledger
  ↓
Working Evidence
  ↓ Controller 显式选择
Frozen Evidence Snapshot
  ↓
Answer Generator
```

Frozen Evidence 一旦生成即作为该轮知识回答的不可变事实来源。最终 Citation 只能引用这一快照内的 Evidence。

这使“模型看过什么”和“最终答案真正依据什么”成为两个可审计概念。

### 3. Answer Units + Grounding Reviewer

Answer Generator 不再只返回一整段不可定位文本，而是输出稳定的 Answer Units：

```text
Answer Unit
├─ unit_id
├─ text
└─ citations[]
```

Reviewer 开启时必须满足：

- 每个 Answer Unit 恰好对应一条审查结果；
- 不能漏审；
- 不能重复审；
- 不能引用不存在的 Unit；
- `SUPPORTED` Unit 必须拥有实际证据引用；
- 顶层 `SUPPORTED` 与 Unit 级 `UNSUPPORTED / OVERSTATED` 冲突时直接判定协议无效。

因此：

```text
“Reviewer 没审到” ≠ “默认支持”
```

Reviewer 只是 Grounding Control，不拥有重新规划、重新检索或改变用户目标的权限。

### 4. Publication Boundary：Candidate 不等于 Published Answer

系统显式区分：

```text
Generated Candidate
        ↓
Validation / Review
        ↓
Publication Decision
        ↓
Published Result
```

模型已经生成文本，并不意味着该文本可以直接返回用户。

以下场景都会 fail-close：

- 结构化协议连续两次失败；
- Frozen Evidence 不存在；
- Reviewer 协议不完整；
- Reviewer 拒绝答案；
- Runtime 资源预算耗尽；
- 上游模型调用超过剩余 deadline。

### 5. Structured Candidate 单轨协议

Controller、Answer Generator、Reviewer 的结构化输出统一遵循有界协议：

```text
Generate
  ↓
Deterministic Validate
  ↓ invalid
One Clean Retry
  ├─ reasoning = off
  ├─ temperature = 0
  └─ same semantic input
  ↓ invalid
Fail Close
```

不会从 `reasoning_content` 中提取“看起来像答案”的文本进行补救，也不会无限重试。

### 6. 请求级 Main Model Identity

一次 Agent 请求只解析一次 Main Model 身份。

Controller、Answer Generator 以及该请求内的协议重试共享同一模型身份；`thinking` 只改变阶段调用策略，不在运行中偷偷把 Answer Generator 切换到另一套模型。

同时每次逻辑模型调用记录：

- `call_id`
- `stage`
- `attempt`
- `model_name`
- `timeout_seconds`
- `elapsed_seconds`
- `outcome`

Structured Candidate 的协议重试共用同一个 logical call deadline，不能通过重试重新获得一整份超时预算。

### 7. WebGIS 联动与空间能力

项目在原有 WebGIS 产品能力上增加了浏览器侧 GIS Agent 执行闭环：

- OpenLayers 2D 地图；
- Cesium 3D 地球；
- PostGIS 空间范围、包含、相交等查询；
- GeoJSON 等空间数据接口；
- 浏览器本地 SHP / GeoJSON 文件登记与导入；
- 稳定 `file_ref` / `layer_ref` 引用；
- 用户矢量图层显隐、样式修改与视图定位；
- 浏览器权威 `MapContext`；
- 结构化 `MapAction` 与 Browser Tool Receipt；
- `runId + toolCallId` 幂等执行与冲突校验。

浏览器文件字节保留在本地页面内，Agent 仅接收文件摘要与不透明 `file_ref`。导入后生成稳定 `layer_ref`，后续显隐、样式和定位工具均围绕这一引用执行，避免多步操作时依赖脆弱的图层对象地址。

浏览器工具采用暂停/续接协议：

```text
Controller
  ↓
GIS Tool Call
  ↓
Agent Runtime 暂停当前 Turn
  ↓ continuation_token + MapAction
Browser Bridge
  ↓
FrontendExecutor
  ↓
GIS Capability
  ↓
OpenLayers
  ↓
Tool Receipt + 最新 MapContext
  ↓
Agent Runtime 恢复同一 Turn / Trace
  ↓
Controller 继续规划下一步
```

Agent Loop 的所有权始终位于后端 GeoRAG Runtime；浏览器只负责真实地图状态与地图副作用执行，不维护第二套规划状态机。

### GIS 状态观测与评测

`MapContext` 以浏览器真实 OpenLayers 状态为准，除视口与用户图层摘要外，还提供完整递归图层树。导入矢量数据时为要素建立稳定 `feature_ref`；属性和精确几何不全量塞入上下文，而通过 `inspect_layer_features` / `get_feature_geometry` 按需读取。PostGIS 的空间关系与叠加结果、Browser Tool Receipt 都作为 Observation 进入同一 Evidence Ledger，最终回答仍必须通过 Frozen Evidence 发布。

仓库提供 `evals/geoai_agent_36_tasks.json` 的 36 个端到端任务契约，以及 `scripts/evaluate_geoai_agent_results.py` 聚合真实执行结果。评测器只根据完整结果记录计算任务完成率；README 不预置或宣称未经执行得到的百分比。

## 三种查询入口

项目保留不同使用场景，而不是强制所有请求都走 Agent：

| 模式 | 用途 |
| --- | --- |
| `use_generation=false` | 确定性检索，只返回搜索结果 |
| `mode=linear` | 兼容传统线性 RAG 路径 |
| `mode=agent` | 默认生成模式，进入 Agent Runtime |

这样可以在迁移 Agent 架构后继续兼容已有 API 与产品功能。

## 检索与文档处理

### Retrieval

- PostgreSQL + pgvector 向量检索；
- 关键词检索；
- Hybrid Retrieval；
- 可选 rerank；
- Metadata Filter；
- Spatial Filter / PostGIS；
- 检索通道诊断，可区分“没有证据”和“检索服务不可用”。

### Document Pipeline

文档解析与切分保留结构信息，包括：

- Markdown 标题层级；
- 表格；
- 代码块；
- DOCX 表格；
- Excel Sheet 结构；
- 文档上传、索引与状态生命周期。

## 产品预览

### 登录与公开演示

![Login page](docs/screenshots/login-light.png)

### 2D 地图工作台

标准检索、AI 问答、引用和地图联动位于同一工作台。

![2D map workspace](docs/screenshots/workspace-2d-map.png)

### 3D 地球

![3D globe workspace](docs/screenshots/workspace-3d-globe.png)

## 技术栈

### Backend

- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy Async
- PostgreSQL
- pgvector
- PostGIS
- MySQL
- Redis
- OpenAI-compatible LLM API

### Frontend

- React
- TypeScript
- Vite
- OpenLayers
- Cesium
- Zustand

## 项目结构

```text
geo-rag-standard-assistant/
├─ Backend/
│  ├─ main.py
│  └─ app/
│     ├─ api/
│     ├─ models/
│     └─ services/
│        ├─ agent/
│        │  ├─ runtime.py
│        │  ├─ controller.py
│        │  ├─ tool_runtime.py
│        │  ├─ evidence.py
│        │  ├─ answer_generator.py
│        │  ├─ reviewer.py
│        │  ├─ publication.py
│        │  ├─ structured_candidate.py
│        │  └─ model_client.py
│        └─ rag/
├─ frontend/
│  └─ src/
│     ├─ gis/
│     │  ├─ browserBridge.ts
│     │  ├─ frontendExecutor.ts
│     │  ├─ mapContext.ts
│     │  ├─ fileReferenceStore.ts
│     │  ├─ userVectorCapabilities.ts
│     │  └─ openlayersAdapter.ts
│     └─ components/
├─ docs/
├─ scripts/
└─ docker-compose.yml
```

## 快速开始

### 1. Backend

本地运行需要可用的 PostgreSQL 与 MySQL。Redis 属于缓存与公开演示额度相关依赖。

```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

根据实际环境配置 `Backend/.env` 中的数据库、LLM 与对象存储参数。

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

本地开发时 Vite 默认将 `/api` 代理到后端；特殊部署场景可以通过 `VITE_API_URL` 覆盖。

### 3. Docker Compose（可选）

```bash
docker compose up -d
```

## 36-task 真实 E2E 评测

仓库中的 `evals/geoai_agent_36_tasks.json` 固定定义 36 个 GeoAI Agent 任务，`scripts/evaluate_geoai_agent_results.py` 只根据真实执行结果计算完成率，不内置任何目标百分比。

在把结果称为真实 E2E 完成率之前，先运行环境预检：

```bash
python scripts/preflight_geoai_agent_e2e.py
```

预检会检查 36-task 清单、PostgreSQL/MySQL 配置与可达性、Backend 启动所需的 Admin Auth 配置、LLM 凭证、Backend/Frontend 服务以及本机浏览器可用性，并且不会打印密钥值。Redis 与 Docker 会单独报告，但不是 36-task 验收的硬前置；Frontend 默认按项目实际开发端口 `3000` 检查。单元测试、契约测试和模拟 Controller 的通过结果不能计作 36 个真实任务的完成记录。

## 设计文档

- `docs/superpowers/specs/2026-09-20-georag-backend-rag-agent-adaptation-design.md`
- `docs/superpowers/plans/2026-09-20-georag-backend-rag-agent-adaptation.md`
- `docs/superpowers/specs/2026-09-22-georag-reference-rag-contract-delta.md`
- `docs/PRD.md`
- `docs/DEPLOY.md`

## License

MIT
