# 阶段一：全局架构与项目认知审查结论报告

> 审查基线时间：2026-10-09
> 执行规范依据：[AI 辅助软件工程统一执行规范](../AI_ENGINEERING_STANDARDS.md)

---

## 1. 整体审查多阶段路线图

| 阶段 | 审查主题 | 状态 | 核心交付物 |
| :--- | :--- | :--- | :--- |
| **阶段一** | **全局架构与项目认知审查 (System Baseline)** | **已完成 (COMPLETED)** | 本文档：系统拓扑、状态真源对账、技术栈复用度审查、工作区基线 |
| **阶段二** | **后端 Agent Runtime 与领域服务审查 (Backend Deep-Dive)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-2-backend-deep-dive-review.md`](./2026-10-09-stage-2-backend-deep-dive-review.md) |
| **阶段三** | **前端架构与 WebGIS Runtime 审查 (Frontend Deep-Dive)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-3-frontend-deep-dive-review.md`](./2026-10-09-stage-3-frontend-deep-dive-review.md) |
| **阶段四** | **跨端契约、协议与安全防御审查 (Contracts & Security)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-4-contracts-and-security-review.md`](./2026-10-09-stage-4-contracts-and-security-review.md) |
| **阶段五** | **工程质量、测试套件与基线验证 (Harness & Evals)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-5-engineering-harness-and-evals-review.md`](./2026-10-09-stage-5-engineering-harness-and-evals-review.md) |
| **阶段六** | **多视角收敛对账与改进路线图 (Convergence & Roadmap)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-6-convergence-and-roadmap-review.md`](./2026-10-09-stage-6-convergence-and-roadmap-review.md) |

---

## 2. 阶段一审查详细结论

### 2.1 系统定位与业务边界

- **系统定位**：面向国土空间规划、测绘标准、自然资源资料理解与 WebGIS 操作场景的 GeoAI Agent / RAG 工业级应用。
- **演进路径**：传统 RAG（检索 → Prompt → 生成）升级为闭环 Agent 决策系统：
  $$\text{User Query} \to \text{Controller 决策} \to \text{Tool 执行 (PostGIS / 浏览器 GIS / 检索)} \to \text{Evidence Ledger 记录} \to \text{Frozen 冻结} \to \text{Answer 生成/审查} \to \text{发布隔离}$$
- **架构不变式（Invariants）**：
  1. 空间事实必须由 PostGIS（后端）或真实地图状态（前端 MapContext）背书，大模型严禁幻觉推断空间拓扑。
  2. 回答生成严格绑定 Frozen Evidence Snapshot 的 `unit_id` 与 `citation`。
  3. 未经发布边界审查的结果，不得向用户呈现。

### 2.2 物理目录拓扑与职责划分

```text
ragAI知识库/
├── Backend/                        # FastAPI 后端服务 (Python 3.12+)
│   ├── app/
│   │   ├── api/                    # HTTP/SSE 接入层 (agent, search, spatial, document, auth)
│   │   ├── core/                   # 基础设施 (config, database, auth, llm_config)
│   │   ├── models/                 # 数据模型 (Pydantic models, ORM mappings)
│   │   └── services/               # 核心业务服务层
│   │       ├── agent/              # Agent 核心体系 (Runtime, Controller, LangGraph, Tools)
│   │       ├── geosql/             # GeoSQL 安全解析器与参数化执行引擎
│   │       ├── rag/                # 向量检索、混合检索与文档切片
│   │       └── spatial_service.py  # PostGIS 空间拓扑、叠加分析与测地缓冲区
│   ├── migrations/                 # 数据库迁移脚本
│   └── tests/                      # pytest 自动化测试套件
├── frontend/                       # React 19 + TypeScript + Vite 前端
│   ├── src/
│   │   ├── gis/                    # WebGIS 抽象层 (OpenLayers, Cesium 适配器与图层管理)
│   │   ├── components/             # UI 组件 (Chat, AgentProcess, AnswerMarkdown 等)
│   │   ├── store/                  # 状态管理 (Zustand stores)
│   │   ├── services/               # 前端 HTTP/SSE 及地图桥接服务
│   │   └── App.tsx                 # 核心工作区大单体组装页面
│   └── tests/                      # Vitest 单元与合约测试
├── evals/                          # 36-task GeoAI Evaluation 基准评测套件
├── docs/superpowers/               # Spec 驱动开发规格与计划归档
└── aoci.*.txt                      # AOCI 仓库级结构化认知索引
```

### 2.3 技术栈能力来源与复用度评估

- **PostGIS 空间计算**：严格复用 PostgreSQL + PostGIS 原生空间拓扑与缓冲区函数，严禁在应用层重复造几何计算轮子（符合规范“成熟能力优先”）。
- **pgvector 向量检索**：复用同一关系型实例承载 2048 维向量检索，避免引入额外向量数据库基础设施。
- **状态编排双轨**：
  - 系统同时存在自研 `AgentRuntime` 与 LangGraph `StateGraph`。
  - **重要发现**：LangGraph 实现目前仅作为外层壳（通过 `PlanningGraphContext` 回调函数反向驱动 `AgentRuntime.run` 内部闭包），存在一定程度的过度封装与双轨并行倾向，需在阶段二重点评估。

### 2.4 状态真源（Source of Truth）审查

1. **会话与轮次真源**：后端持久化 PostgreSQL 表（`agent_sessions`, `agent_turns`, `agent_events`），受乐观并发控制（OCC）版本号保护。
2. **事实证据真源**：`EvidenceLedger` 维护的 Working Evidence 与发布时的 Frozen Evidence Snapshot。
3. **地图上下文真源**：前端实时收集的 `MapContext`（包含视口、图层树、要素属性），后端对其仅做只读断言与守卫，不维护冗余影子地图状态。

### 2.5 工作区现状与健康基线

- **Git 状态**：工作区当前包含未提交的 Answer Readability 相关改动（涉及 `answer_generator.py`、`Chat.tsx`、`AgentProcess.tsx` 等），审查过程保持严格只读，不覆写用户未提交内容。
- **测试健康度**：
  - 后端 pytest 执行 `tests/test_agent_answer_generation.py`，10 项测试全数通过。
  - 前端执行 `npm run contract:check`，API 契约检查通过。
- **初查技术债与代码气味**：
  - `Backend/app/services/agent/store.py` (76KB) 承担过多职责（接口定义、内存实现、SQL 持久化、类型编解码、OCC 锁）。
  - `Backend/app/services/agent/runtime.py` (68KB) 的 `run` 方法存在约 900 行的大闭包逻辑。
  - `frontend/src/App.tsx` (62KB) 存在大单体组件风险。
  - Pydantic V1 遗留废弃语法（`BaseSettings`, `@validator`, `min_items`），在升级 Pydantic V3 时存在隐患。
