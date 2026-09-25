# GeoRAG Planning Assistant

> 面向国土空间规划、测绘标准、自然资源资料理解与 WebGIS 操作场景的 **GeoAI Agent / RAG 应用**。
>
> 项目将知识检索、证据约束、Agent 多步规划、浏览器 GIS 工具执行、PostGIS 空间分析与 2D/3D 地图联动统一到一套可追踪的 Agent Runtime 中，使系统从“检索后直接让模型回答”的传统 RAG，升级为能够 **查资料、读地图、操作图层、执行空间分析并基于真实执行结果继续决策** 的 GeoAI Agent。

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-TypeScript-61DAFB.svg)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector%20%2B%20PostGIS-336791.svg)](https://www.postgresql.org/)
[![GeoAI](https://img.shields.io/badge/GeoAI-Agent%20%2B%20RAG-6A5ACD.svg)](#核心架构)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

---

## 项目概览

GeoRAG Planning Assistant 最初是一个面向规划标准、测绘规范和地理信息政策资料的 RAG 检索系统。在保留原有检索、文档管理、PostGIS、OpenLayers、Cesium 与公开演示能力的基础上，项目完成了后端 Agent 化与浏览器 GIS Runtime 升级。

现在系统可以围绕同一个用户目标连续完成：

```text
资料检索
  ↓
证据选择与引用
  ↓
导入 GeoJSON / SHP
  ↓
读取真实地图状态
  ↓
控制图层显隐 / 样式
  ↓
定位地图 / 图层
  ↓
读取要素属性与精确几何
  ↓
执行 PostGIS 空间关系 / 叠加分析
  ↓
根据 Tool Receipt 继续决策
  ↓
基于 Frozen Evidence 生成最终回答
```

系统的目标不是“给地图加一个聊天框”，而是让 **LLM 负责语义决策，Runtime 负责确定性执行，Browser 负责真实地图状态，PostGIS 负责空间事实，Evidence Ledger 负责最终回答依据**。

## 项目状态

当前仓库按完整项目状态维护，核心能力已形成闭环：

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Agent Runtime | ✅ | Session / Turn / Trace、多步工具调用、暂停与恢复、资源边界 |
| RAG / Evidence | ✅ | Hybrid Retrieval、Evidence Ledger、Working / Frozen Evidence、Citation |
| Structured Output | ✅ | 确定性校验、单次协议修复、fail-close |
| Grounding Reviewer | ✅ | 可选开启，按 Answer Unit 做证据完整性审查 |
| Publication Boundary | ✅ | Candidate 与最终 Published Answer 显式分离 |
| Browser GIS Runtime | ✅ | Browser Bridge、Frontend Executor、Tool Receipt、Continuation |
| 稳定 GIS 引用 | ✅ | `file_ref` / `layer_ref` / `feature_ref` |
| MapContext | ✅ | 视口、完整递归图层树、用户图层状态、工具能力 |
| GIS 操作工具 | ✅ | 导入、显隐、样式、定位、要素读取 |
| PostGIS Agent Tools | ✅ | 空间关系判断、交集 / 并集 / 差集 |
| 36-task GeoAI Evaluation | ✅ Harness 已实现 | 36 条固定任务 + 场景依赖 + 机器断言 + Playwright 浏览器执行；真实 36/36 需以结果文件为证 |

---

## 核心能力

### 1. Agent 化 RAG

传统 RAG 通常只有一条固定链路：

```text
问题 → 检索 → Prompt → LLM → 回答
```

本项目将其改造成可持续规划的 Agent Loop：

```text
问题
  ↓
Controller 判断下一步
  ↓
Tool Runtime 执行工具
  ↓
Observation / Evidence
  ↓
更新 Session / Working Evidence
  ↓
Controller 再规划
  ↓
compose_answer 冻结证据
  ↓
Answer Generator
  ↓
Optional Reviewer
  ↓
Publication Boundary
```

Runtime 不使用关键词规则、固定意图枚举或实体特判替模型做语义规划，只维护执行事实、状态、资源预算和发布契约。

### 2. 可审计 Evidence 生命周期

检索结果并不会直接成为最终答案依据，而是进入显式证据生命周期：

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
        ↓
Citation
```

最终回答只能引用 Frozen Evidence 中存在的 Evidence，因此可以区分：

- 模型“曾经看到过”的信息；
- Runtime 当前持有的信息；
- 最终答案真正使用的信息。

Browser Tool Receipt 与 PostGIS 确定性结果也进入同一 Evidence Ledger，使“知识证据”和“真实 GIS 执行事实”共用一套发布边界。

### 3. Answer Units + Grounding Reviewer

Answer Generator 输出结构化 Answer Units：

```text
Answer Unit
├─ unit_id
├─ text
└─ citations[]
```

Reviewer 开启时：

- 每个 Answer Unit 必须且只能对应一条审查结果；
- 不允许漏审、重复审或引用不存在的 Unit；
- `SUPPORTED` 必须有真实 Evidence 支撑；
- `UNSUPPORTED / OVERSTATED` 会阻止不安全 Candidate 发布；
- Reviewer 只负责 Grounding Control，不拥有重新规划或替代 Controller 的权限。

### 4. Publication Boundary

系统显式区分：

```text
Generated Candidate
        ↓
Deterministic Validation
        ↓
Optional Reviewer
        ↓
Publication Decision
        ↓
Published Result
```

模型生成了文本，不代表该文本可以直接返回用户。以下情况会 fail-close：

- Structured Candidate 连续协议失败；
- 最终知识回答没有 Frozen Evidence；
- Reviewer 协议不完整；
- Reviewer 明确拒绝 Candidate；
- Runtime 资源保险丝触发；
- 模型调用超过逻辑调用 deadline。

### 5. 统一 Structured Candidate 协议

Controller、Answer Generator、Reviewer 的结构化模型输出统一经过：

```text
Generate
  ↓
Deterministic Validate
  ↓ invalid
One Protocol-only Retry
  ├─ reasoning = off
  ├─ temperature = 0
  └─ semantic input unchanged
  ↓ invalid
Fail Close
```

系统不会从 `reasoning_content` 中抽取“看起来像答案”的文本进行兜底，也不会通过无限重试绕过协议边界。

### 6. 请求级 Main Model Identity

一次请求只解析一次 Main Model Identity。

Controller、Answer Generator 以及该请求中的协议修复共享同一模型身份；阶段策略只控制 reasoning、temperature、deadline 等调用参数，不在执行过程中偷偷更换语义主模型。

每次逻辑模型调用可记录：

- `call_id`
- `stage`
- `attempt`
- `model_name`
- `timeout_seconds`
- `elapsed_seconds`
- `outcome`

协议重试与初始调用共享同一个逻辑 deadline，不能通过重试重新获得一整份时间预算。

---

## GeoAI / GIS Agent

### 浏览器权威地图状态

WebGIS 中真正的图层对象、要素和视口存在于浏览器，因此项目没有让 Backend 猜测地图状态，而是采用：

> **Browser-authoritative MapContext**

`MapContext` 包含：

- 当前地图 Viewport；
- 支持的 Browser GIS Tools；
- 可用本地文件摘要；
- 完整递归 Layer Tree；
- 用户矢量图层状态；
- 稳定 `layer_ref`；
- 有界 `feature_ref` 摘要。

地图对象仍由 OpenLayers 管理，Agent 只消费稳定、结构化、可序列化的状态。

### 三层稳定引用

多步 GIS Agent 最容易出现的问题，是模型第一次操作得到一个对象，下一步却失去这个对象的稳定身份。

项目为此定义三类引用：

```text
file_ref
  └─ 浏览器本地文件或文件组

layer_ref
  └─ 导入后的用户矢量图层

feature_ref
  └─ 图层中的稳定要素身份
```

因此 Agent 可以连续执行：

```text
导入数据
→ 获得 layer_ref
→ 修改样式
→ 隐藏 / 显示
→ fit 图层
→ inspect features
→ 获得 feature_ref
→ 读取精确几何
→ 交给 PostGIS 做空间分析
```

而不依赖 JavaScript 对象地址、数组下标或模型重新猜测目标图层。

### Browser Tool Continuation

浏览器工具采用暂停 / 恢复协议：

```text
Main Controller
      ↓
GIS Tool Call
      ↓
Agent Runtime
      ↓ pause current logical turn
continuation_token + MapAction
      ↓
Browser Bridge
      ↓
Frontend Executor
      ↓
GIS Capability
      ↓
OpenLayers
      ↓
Tool Receipt + latest MapContext
      ↓
Agent Runtime resume same Turn / Trace
      ↓
Controller continues planning
```

浏览器只负责真实副作用执行，不拥有第二套 Agent 状态机。Agent Loop 的所有权始终在 Backend Runtime。

### 浏览器 GIS 工具

| Tool | 作用 |
| --- | --- |
| `import_vector_dataset` | 导入 GeoJSON / SHP 等本地矢量数据 |
| `set_layer_visibility` | 修改用户图层显隐 |
| `set_vector_style` | 修改边线、填充、点样式等 |
| `fit_vector_layer` | 缩放至目标图层范围 |
| `locate_map` | 定位坐标与缩放级别 |
| `inspect_layer_features` | 分页读取要素 `feature_ref` 与属性 |
| `get_feature_geometry` | 获取指定 `feature_ref` 的精确 EPSG:4326 GeoJSON |

Browser Tool 通过 `runId + toolCallId` 做幂等与冲突校验，避免网络重试导致同一个地图副作用重复执行。

### PostGIS Agent Tools

确定性空间语义由 PostGIS 负责，而不是让 LLM 自己判断几何关系。

当前支持：

```text
query_spatial_relation
├─ intersects
├─ within
├─ contains
├─ overlaps
├─ disjoint
└─ touches

spatial_overlay
├─ intersection
├─ union
└─ difference
```

空间操作数可以来自：

- GeoJSON Geometry；
- `spatial_regions` 中按 `adcode` 精确解析的实体；
- `spatial_regions` 中按 `region_name` 精确解析的实体；
- Browser GIS Tool 返回的真实 feature geometry。

PostGIS Result 会作为 Observation 进入 Evidence Ledger，随后可以被冻结并作为最终自然语言结论的 Citation 来源。

---

## RAG 与检索

### Retrieval

项目保留并整合原有检索能力：

- PostgreSQL + pgvector 向量检索；
- Keyword Search；
- Hybrid Retrieval；
- 可选 Rerank；
- Metadata Filter；
- Spatial Filter；
- Follow-up Evidence Reuse；
- 检索通道诊断；
- “没有证据”和“检索服务不可用”状态区分。

### Document Pipeline

文档解析与切分尽量保留原始结构信息：

- Markdown 标题层级；
- Markdown 表格；
- 代码块；
- DOCX 正文与表格；
- Excel Sheet 结构；
- 文档上传、索引与状态生命周期。

这些结构最终进入统一 RetrievalPort，而不是让 Controller 直接依赖某一个具体向量库实现。

---

## 核心架构

```text
┌──────────────────────────────────────────────────────────────┐
│                         User / Web UI                        │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                  Search API / Application Service            │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                        Agent Runtime                         │
│  Session · Turn · Trace · Deadline · Tool Lifecycle         │
│  Evidence · Continuation · Publication Contract             │
└──────────────┬────────────────────────────────┬──────────────┘
               │                                │
               ▼                                ▼
┌──────────────────────────────┐   ┌───────────────────────────┐
│       Main Controller        │   │       Evidence Ledger      │
│ semantic planning / tools    │   │ Working → Frozen Evidence  │
└──────────────┬───────────────┘   └─────────────┬─────────────┘
               │                                 │
               ▼                                 │
┌──────────────────────────────┐                  │
│         Tool Runtime         │                  │
├──────────────────────────────┤                  │
│ RAG Tools                    │                  │
│ Browser GIS Tools            │                  │
│ PostGIS Tools                │                  │
│ Clarify / Limitation         │                  │
└───────┬───────────┬──────────┘                  │
        │           │                             │
        ▼           ▼                             │
┌──────────────┐ ┌────────────────────────────┐   │
│ RetrievalPort│ │ Browser Bridge / OpenLayers│   │
│ pgvector/RAG │ │ MapContext / Tool Receipt  │   │
└──────┬───────┘ └──────────────┬─────────────┘   │
       │                         │                 │
       ▼                         ▼                 │
┌──────────────────┐   ┌──────────────────────┐   │
│ PostgreSQL       │   │ 2D OpenLayers        │   │
│ pgvector/PostGIS │   │ 3D Cesium            │   │
└──────────────────┘   └──────────────────────┘   │
                                                  │
                                                  ▼
                                ┌────────────────────────────┐
                                │      Answer Generator       │
                                │ Frozen Evidence only        │
                                └─────────────┬──────────────┘
                                              ▼
                                ┌────────────────────────────┐
                                │ Optional Grounding Reviewer │
                                └─────────────┬──────────────┘
                                              ▼
                                ┌────────────────────────────┐
                                │    Publication Boundary     │
                                └─────────────┬──────────────┘
                                              ▼
                                Answer + Citations + MapAction
```

### 关键边界

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| Main Controller | 理解目标、选择工具、决定下一步 | 执行地图副作用 |
| Agent Runtime | 状态、执行、资源、恢复、发布边界 | 预判业务语义 |
| Tool Runtime | 工具参数验证、执行与 Observation | 最终自然语言回答 |
| Evidence Ledger | 证据身份、激活、冻结与引用 | 决定用户意图 |
| Browser Runtime | 真实地图状态与地图副作用 | Agent 语义规划 |
| PostGIS | 确定性空间关系与几何计算 | 语言推理 |
| Answer Generator | 基于 Frozen Evidence 组织回答 | 新增外部事实 |
| Reviewer | Grounding 审查 | 重新规划任务 |

---

## 36-task GeoAI Evaluation

仓库提供固定的 36 个 GeoAI Agent 任务：

`evals/geoai_agent_36_tasks.json`

覆盖从知识问答到复杂 GIS Agent 连续操作：

| 类别 | 数量 | 主要验证目标 |
| --- | ---: | --- |
| Knowledge | 6 | 检索、证据复用、引用、澄清、无证据限制 |
| Import | 4 | GeoJSON / SHP 导入、稳定 `layer_ref`、失败回执 |
| Layer Control | 6 | 显隐、样式、连续操作、完整 Layer Tree |
| Viewport | 4 | 坐标定位、图层 fit、跨工具 continuation、非法坐标 |
| Feature Observation | 6 | 分页属性读取、稳定 `feature_ref`、精确几何 |
| Spatial Analysis | 6 | PostGIS relation、overlay、Frozen Evidence |
| Recovery | 4 | 失败 observation、Controller 恢复与安全结束 |
| **Total** | **36** | **完整 GeoAI Agent 任务闭环** |

当前仓库提供的是 **36 条完整任务定义与真实浏览器 E2E Harness**。是否已经达到 36/36，不由 README 预先声明，而由最新一次真实执行产生的 `evals/results/<run>/results.json` 决定。

项目完成态验收基线仍然是：

```text
36 / 36 tasks completed
Completion Rate: 100%
```

环境预检：

```bash
python scripts/preflight_geoai_agent_e2e.py
```

完整真实 E2E：

```bash
python scripts/run_geoai_agent_e2e.py
```

该入口严格执行：

```text
preflight
→ Playwright 打开真实前端
→ 真实 Agent / Browser GIS continuation
→ Tool Receipt / MapContext
→ 机器断言
→ results.json
→ evaluator
```

Frontend 也可以单独运行：

```bash
cd frontend
npm run e2e:geoai
```

结果聚合：

```bash
python scripts/evaluate_geoai_agent_results.py path/to/results.json
```

评测器要求每个任务恰好有一条执行结果，并且 `completed=true` 必须由该任务 Manifest 中所有 required assertions 实际通过计算得到。单独提供一个裸 `completed=true` 会被拒绝。

结果汇总输出：

- 总完成数；
- 完成率；
- 各类别完成率；
- 失败任务；
- failure reason。

---

## 三种查询模式

为了兼容不同调用场景，项目没有强制所有 API 都进入 Agent：

| 模式 | 用途 |
| --- | --- |
| `use_generation=false` | 只执行确定性检索，不生成自然语言回答 |
| `mode=linear` | 保留传统线性 RAG 兼容路径 |
| `mode=agent` | 默认生成模式，进入 Agent Runtime |

这使项目可以同时服务“检索 API”“传统 RAG”“多步 Agent”三类需求。

---

## 产品预览

### 登录与公开演示

![Login page](docs/screenshots/login-light.png)

### 2D 地图工作台

标准检索、AI 问答、Citation、图层操作与地图联动位于同一工作台。

![2D map workspace](docs/screenshots/workspace-2d-map.png)

### 3D 地球

![3D globe workspace](docs/screenshots/workspace-3d-globe.png)

---

## 技术栈

### Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy Async
- PostgreSQL
- pgvector
- PostGIS
- MySQL
- Redis
- OpenAI-compatible LLM API
- pytest

### Frontend

- React
- TypeScript
- Vite
- OpenLayers
- Cesium
- Zustand
- Vitest

### Agent / RAG

- Agent Runtime / Controller Loop
- Tool Calling
- Browser Continuation
- Evidence Ledger
- Frozen Evidence
- Structured Output
- Grounding Reviewer
- Publication Boundary
- Hybrid Retrieval
- Spatial Tooling

---

## 项目结构

```text
geo-rag-standard-assistant/
├─ Backend/
│  ├─ main.py
│  ├─ tests/
│  └─ app/
│     ├─ api/
│     ├─ core/
│     ├─ models/
│     └─ services/
│        ├─ agent/
│        │  ├─ runtime.py
│        │  ├─ controller.py
│        │  ├─ tool_runtime.py
│        │  ├─ tools.py
│        │  ├─ evidence.py
│        │  ├─ answer_generator.py
│        │  ├─ reviewer.py
│        │  ├─ publication.py
│        │  ├─ structured_candidate.py
│        │  └─ model_client.py
│        ├─ rag/
│        └─ spatial_service.py
│
├─ frontend/
│  ├─ tests/
│  └─ src/
│     ├─ gis/
│     │  ├─ browserBridge.ts
│     │  ├─ frontendExecutor.ts
│     │  ├─ mapContext.ts
│     │  ├─ fileReferenceStore.ts
│     │  ├─ userVectorCapabilities.ts
│     │  └─ openlayersAdapter.ts
│     └─ components/
│
├─ evals/
│  └─ geoai_agent_36_tasks.json
├─ scripts/
│  ├─ preflight_geoai_agent_e2e.py
│  └─ evaluate_geoai_agent_results.py
├─ docs/
├─ docker/
├─ docker-compose.yml
└─ README.md
```

---

## 快速开始

### Non-Docker local development

#### 1. 准备环境

推荐：

- Python 3.12+
- Node.js 20+
- PostgreSQL + pgvector + PostGIS
- MySQL
- Redis（可选缓存 / 演示额度）
- 一个可用的 OpenAI-compatible LLM Endpoint

#### 2. Backend

```bash
cd Backend
python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Linux / macOS：

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

配置 `Backend/.env` 后启动：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

主要配置项：

```env
DATABASE_URL=postgresql+asyncpg://...
MYSQL_URL=mysql+aiomysql://...
REDIS_URL=redis://...

LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-flash
# Optional; unset for direct connection, set only to a reachable proxy.
DEEPSEEK_PROXY=
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=qwen3-embedding:4b-q4_K_M
OLLAMA_EMBEDDING_DIMENSIONS=2048
# Optional; unset for direct connection, set only to a reachable proxy.
OPENAI_PROXY=

SECRET_KEY=...
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
```

不要将真实密钥提交到 Git。

#### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

默认开发地址：

```text
http://localhost:3000
```

本地开发时 `/api` 通过 Vite Proxy 指向 Backend；特殊部署场景可以通过 `VITE_API_URL` 覆盖。

### Optional Docker Compose

也可以使用：

```bash
docker compose up -d
```

启动前应根据 `.env.example` 设置数据库、Redis、对象存储与 LLM 等配置。

---

## 验证与测试

### Backend Agent / GIS 相关测试

```bash
pytest Backend/tests -q
```

### Frontend GIS Contract

```bash
cd frontend
npm run test:gis
```

### Frontend 类型与契约检查

```bash
npm run lint
npm run build
```

### E2E 环境预检

在仓库根目录：

```bash
python scripts/preflight_geoai_agent_e2e.py
```

预检会分别检查：

- 36-task Manifest；
- PostgreSQL 配置与可达性；
- MySQL 配置与可达性；
- Admin Auth 启动配置；
- LLM Credential；
- Backend Health；
- Frontend；
- Browser；
- npm；
- Redis / Docker 可选依赖。

---

## 设计原则

项目遵循以下架构原则：

1. **语义决策归模型，确定性执行归 Runtime。**
2. **Browser 是 WebGIS 实时状态的权威来源。**
3. **PostGIS 是空间关系与叠加计算的权威来源。**
4. **最终知识回答只能基于 Frozen Evidence。**
5. **Candidate 不等于 Published Answer。**
6. **失败状态必须可观察，不能把失败伪装成成功。**
7. **稳定引用优于跨步骤传递内存对象。**
8. **Runtime 保险丝只限制物理资源，不替 Controller 做业务规划。**
9. **协议修复有界，禁止无限重试和隐藏兜底。**
10. **保留原系统有价值能力，升级职责边界而不是整体推倒重写。**

---

## 设计文档

主要设计与实施文档：

- `docs/superpowers/specs/2026-09-20-georag-backend-rag-agent-adaptation-design.md`
- `docs/superpowers/plans/2026-09-20-georag-backend-rag-agent-adaptation.md`
- `docs/superpowers/specs/2026-09-22-georag-reference-rag-contract-delta.md`
- `docs/superpowers/specs/2026-09-23-georag-gis-observation-spatial-eval-design.md`
- `docs/superpowers/plans/2026-09-23-georag-gis-observation-spatial-eval.md`
- `docs/PRD.md`
- `docs/DEPLOY.md`

---

## License

MIT
