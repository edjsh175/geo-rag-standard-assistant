# GeoAI Agent 通用框架复用、GIS 执行闭环与 GeoSQL 能力收敛 PRD

- **Document status**: IMPLEMENTED / Phase 0-6 code + automated regression complete; live cluster E2E pending.
- **日期**：2026-09-30
- **目标仓库**：GeoAI
- **适用范围**：Backend Agent Runtime、Tool Calling、RAG、PostGIS 空间分析、Browser GIS Runtime、Linear/Agent 发布链路、GeoSQL
- **优先级**：P0 / P1
- **实施原则**：第一性原则、最小充分原则、复用优先原则、局部-模块-整体多视角审查

---

## 1. 背景

当前 GeoAI 已具备较完整的 RAG + GIS Agent 雏形，包括：

- Main Controller；
- 动态 Tool / Control Action Surface；
- RAG 检索、Evidence Ledger、Frozen Evidence；
- Answer Generator；
- Reviewer；
- Browser GIS Runtime；
- OpenLayers / Cesium；
- SHP / GeoJSON 导入；
- 图层显隐、样式、视角定位、要素读取；
- PostGIS 空间关系和 Overlay；
- Agent trace、session、turn、browser continuation；
- Linear 与 Agent 两种回答模式。

同时，当前项目与“AI 智能体开发工程师（GIS + Agent）”岗位的主要重合能力包括：

1. Agent 架构设计与 Tool Calling；
2. GIS Tool / Plugin 封装；
3. 空间 RAG；
4. PostGIS 空间分析；
5. Agent 推理结果与地图交互。

但当前代码继续增长时已经出现四类结构性风险：

1. **通用 Agent 基础设施自研过多**：Tool Calling 协议、结构化输出、状态流转、兼容层等正在重复实现成熟框架已经提供的能力；
2. **Agent Runtime 物理边界失守**：`AgentRuntime.run()` 聚合 session、context、planning、tool、browser、answer、review、publish、persistence 等职责；
3. **状态与协议存在平行源风险**：Postgres / InMemory fallback、Controller 新旧 wire、Linear / Agent 发布流程均存在双实现或平行实现；
4. **GIS 能力尚未形成完整闭环**：已经可以算出 PostGIS 结果，但“分析结果 → GeoJSON → Browser Tool → 地图图层 → layer_ref → receipt”尚未形成统一原语。

本 PRD 的目的不是新增一批零散功能，而是先把 Agent 内核收敛成可长期演进的结构，再补足岗位目标中真正缺失的 GeoSQL / Text-to-SQL 能力。

---

# 2. 第一性原则

## 2.1 最终目标

GeoAI 的目标不是“拥有尽可能多的自研 Agent 代码”，而是：

> **让大模型负责语义决策，让成熟框架负责通用 Agent 编排，让 GeoAI 自研代码只维护不可替代的 GIS、RAG、安全执行和业务事实边界。**

最终主链应收敛为：

```text
User
  ↓
Application Boundary
  ↓
LangGraph Agent Orchestration
  ├─ Context Projection
  ├─ Controller / Planner
  ├─ Tool Selection
  ├─ interrupt / resume
  ├─ Answer
  └─ Review / Publish
  ↓
GeoAI Tool Boundary
  ├─ schema validation
  ├─ authorization
  ├─ timeout
  ├─ idempotency
  ├─ capability availability
  └─ receipt contract
  ↓
Domain Runtime
  ├─ RAG Retrieval
  ├─ PostGIS Spatial Runtime
  └─ Browser GIS Runtime
```

## 2.2 不可变约束

以下约束在重构中不得破坏：

1. **Evidence 是知识回答的事实来源**；
2. **知识型回答必须显式选 Evidence，并经过 Frozen Evidence**；
3. **Browser GIS 的真实地图状态以浏览器 Runtime Receipt / Snapshot 为准**；
4. **LLM 不直接操作数据库、OpenLayers、Cesium 对象或持久化层**；
5. **所有 Tool 调用必须经过统一 Tool Boundary**；
6. **工具是否可调用必须来自当前物理能力，而不是模型自由想象**；
7. **失败不得伪装成功**；
8. **PostGIS / Browser / KB 的副作用必须可追踪、可恢复、可审计**；
9. **不为了引入框架而破坏现有已验证的 RAG / GIS 领域能力**；
10. **不允许形成新的双状态源、平行协议或 shadow runtime**。

---

# 3. 当前能力审计结论

## 3.1 已有且应该保留的领域能力

### RAG

主要位置：

- `Backend/app/services/rag/postgres_adapter.py`
- `Backend/app/services/rag/query_planner.py`
- `Backend/app/services/agent/evidence.py`
- `Backend/app/services/agent/answer_generator.py`
- `Backend/app/services/agent/reviewer.py`

已有能力：

- 标准号精确检索；
- 关键词检索；
- pgvector；
- RRF 融合；
- rerank；
- metadata filter；
- spatial filter；
- Evidence Ledger；
- Frozen Evidence；
- Answer Generator；
- Reviewer。

**结论：保留。**

不得因为引入 LangChain / LangGraph 而用 LlamaIndex 重写现有 RAG。

## 3.2 已有且应该保留的 GIS 领域能力

主要位置：

- `Backend/app/services/spatial_service.py`
- `Backend/app/services/agent/tools.py`
- `Backend/app/services/agent/tool_runtime.py`
- `frontend/src/gis/*`
- `frontend/src/components/OpenLayersMap.tsx`
- `frontend/src/components/CesiumGlobe.tsx`

已有能力：

- `query_spatial_relation`
- `spatial_overlay`
- `locate_map`
- `import_vector_dataset`
- `set_layer_visibility`
- `set_vector_style`
- `fit_vector_layer`
- `inspect_layer_features`
- `get_feature_geometry`

并已有：

- stable `layer_ref`
- stable `feature_ref`
- browser execution receipt
- browser continuation
- runtime snapshot
- active runtime abstraction
- PostGIS 真实空间计算

**结论：保留。**

## 3.3 需要由成熟框架接管的通用能力

当前自研位置：

- `Backend/app/services/agent/controller_protocol.py`
- `Backend/app/services/agent/controller.py`
- `Backend/app/services/agent/structured_candidate.py`
- `Backend/app/services/agent/runtime.py`
- `Backend/app/services/agent/model_client.py`

当前自研内容包括：

- Controller wire；
- Tool Calling JSON；
- JSON Schema 拼装；
- legacy Tool Call 兼容；
- structured output retry；
- action dispatch；
- tool schema → prompt；
- interrupt / resume；
- Agent loop。

其中属于成熟通用 Agent 基础设施、优先复用的部分：

### LangChain Core

负责：

- `BaseTool` / Structured Tool；
- Pydantic schema → tool schema；
- model `bind_tools`；
- provider-neutral Tool Calling；
- structured output；
- tool call extraction。

### LangGraph

负责：

- State Graph；
- Node；
- Edge；
- Conditional Edge；
- interrupt / resume；
- checkpoint；
- durable execution 编排。

**原则：框架只接管“通用控制面”，不接管 GeoAI 的领域执行面。**

---

# 4. P0：AgentStore 单事实源收敛

## 4.1 当前问题

当前生产 Store 位于：

`Backend/app/services/agent/store.py`

存在：

```python
PostgresAgentStore(
    fallback=InMemoryAgentStore()
)
```

并且至少在以下位置各自实例化：

- `Backend/app/api/search_routes.py`
- `Backend/app/api/agent_routes.py`

Postgres 不可用时可能形成：

```text
/search
→ InMemory Store A

/agent/sessions
→ InMemory Store B
```

从而导致同一 session 的 execution / trace / pending state 在不同入口不可见。

## 4.2 目标

生产环境：

```text
Postgres
  ↓
唯一 AgentStore
```

Postgres 不可用时：

```text
fail closed
```

而不是切换到临时内存状态。

测试环境：

```text
显式注入 InMemoryAgentStore
```

## 4.3 实施要求

- [ ] App 生命周期创建唯一 AgentStore；
- [ ] `search_routes`、`agent_routes`、`AgentSessionService`、`AgentTraceService` 复用同一依赖；
- [ ] Production 默认不创建 InMemory fallback；
- [ ] InMemory 只通过 test fixture / dependency override 显式使用；
- [ ] 明确数据库不可用错误语义；
- [ ] pending browser execution、event、evidence、memory、snapshot 必须处于同一持久化边界。

## 4.4 验收

必须新增测试：

1. Postgres 不可用时生产 Store 不创建匿名 fallback；
2. Search route 与 Agent route 使用同一 Store 实例；
3. Session / Trace / Pending Execution 在同一事实源可见；
4. 数据库恢复后不会出现内存态“消失”。

---

# 5. Agent Runtime 物理拆分

## 5.1 当前问题

`Backend/app/services/agent/runtime.py` 当前约 2400+ 行。

`AgentRuntime.run()` 同时负责：

- session load；
- pending execution；
- browser resume；
- conversation memory；
- context projection；
- action state；
- Controller；
- Tool 调用；
- Evidence；
- compose；
- Answer Generator；
- Reviewer；
- repair；
- publish；
- persistence。

这属于典型巨型模块。

## 5.2 目标模块

建议拆为：

```text
agent/
├─ graph/
│  ├─ state.py
│  ├─ graph.py
│  ├─ nodes/
│  │  ├─ load_turn.py
│  │  ├─ project_context.py
│  │  ├─ plan.py
│  │  ├─ execute_tool.py
│  │  ├─ await_browser.py
│  │  ├─ compose.py
│  │  ├─ generate_answer.py
│  │  ├─ review.py
│  │  └─ publish.py
│  └─ transitions.py
│
├─ tools/
│  ├─ registry.py
│  ├─ adapters.py
│  ├─ policy.py
│  └─ runtime.py
│
├─ publication/
│  ├─ pipeline.py
│  └─ contracts.py
│
└─ persistence/
   └─ store.py
```

## 5.3 Runtime 应保留的职责

最终 `AgentRuntime` 只保留：

```text
start()
resume()
stream()
cancel()
```

它是 facade，不再包含全部业务细节。

## 5.4 迁移原则

第一阶段只做物理拆分，不改变行为；只有现有回归全部稳定后，才进入 LangGraph 迁移。

---

# 6. Tool Calling 标准化

## 6.1 当前问题

现在有自定义协议：

```json
{
  "action": "tool_call",
  "tool": "retrieve_kb",
  "arguments": {}
}
```

同时兼容：

```json
{
  "name": "retrieve_kb",
  "arguments": {}
}
```

还存在：

- `evidence_ids → selected_evidence_ids`
- `thought → reason`
- legacy Controller wire normalize

长期会形成协议债务。

## 6.2 目标

外部能力调用统一使用 LangChain 标准 Tool Calling。

示意：

```python
@tool(args_schema=RetrieveKbInput)
async def retrieve_kb(...):
    ...
```

模型：

```python
model.bind_tools(tools)
```

Tool call：

```text
AIMessage.tool_calls
```

适配关系：

```text
LangChain ToolCall
    ↓
GeoAIToolAdapter
    ↓
ToolRuntime.validate_call()
    ↓
ToolRuntime.execute()
```

## 6.3 Control Action 不等于 Tool

以下继续保持控制动作：

- `compose_answer`
- `direct_answer`
- `clarify`
- `limitation`

不得伪装成领域 Tool。

可以通过 LangGraph 的结构化 Controller Output 表达：

```python
class ControllerDecision(BaseModel):
    action: Literal[
        "call_tool",
        "compose_answer",
        "direct_answer",
        "clarify",
        "limitation",
    ]
```

## 6.4 验收

最终删除：

- legacy `name` wire；
- `tool_name` legacy；
- `thought → reason`；
- Controller Tool JSON 手工 normalize；
- 同一语义多个协议入口。

---

# 7. Prompt 规则代码化

## 7.1 当前问题

`Backend/app/services/agent/controller.py` 中存在大量流程性 Prompt：

- 第一次读要素；
- 第二次重复读取；
- offset 翻页；
- feature geometry 后再做 spatial relation；
- retrieve → import → style → fit → compose；
- 当前轮 observation 是否满足；
- failure receipt 后如何结束。

这些规则本质属于状态机，不应主要依赖 LLM 自觉遵守。

## 7.2 目标

Prompt 只保留：

- 目标；
- 工具语义；
- 当前事实；
- 当前 Action Surface；
- 用户约束。

确定性流程下沉到 Graph State / Node。

例如：

```text
get_feature_geometry succeeded
        ↓
state.geometry_available = true
        ↓
query_spatial_relation becomes available
```

而不是主要依靠 Prompt 叙述固定工作流。

---

# 8. GIS Tool 最小闭环

## 8.1 Buffer

当前 `SpatialService.create_buffer()` 已有 PostGIS 实现，但没有注册成 Agent Tool。

新增：

```text
create_buffer
```

最小输入：

```json
{
  "center": [104.0, 30.6],
  "distance_m": 500
}
```

后续可扩展 geometry buffer，但 V1 不同时增加多套输入协议。

输出：

```json
{
  "geometry": {},
  "evidence_id": "..."
}
```

必须直接复用 PostGIS `ST_Buffer`，不得再次实现 Buffer 算法。

## 8.2 通用分析结果上图

新增唯一通用 Browser Tool：

```text
render_geojson_layer
```

输入：

```json
{
  "geojson": {},
  "name": "缓冲区分析结果",
  "style": {}
}
```

输出：

```json
{
  "layer_ref": "ul_xxx",
  "feature_count": 1
}
```

所有未来能力统一复用：

```text
buffer
intersection
difference
union
GeoSQL
routing result
analysis result
```

不得为每种分析结果创建一个独立前端绘制 Tool。

---

# 9. GeoSQL / Text-to-SQL

## 9.1 当前缺口

目前项目已有确定性 PostGIS SQL，但没有完整：

```text
Natural Language
→ SQL / GeoSQL
```

能力。

## 9.2 原则

禁止：

```text
LLM
→ 任意 SQL 字符串
→ 直接执行数据库
```

第一阶段必须采用：

```text
LLM
→ GeoQueryPlan
→ Deterministic Compiler
→ Parameterized SQL
→ Read-only Executor
```

## 9.3 GeoQueryPlan

建议：

```python
class GeoQueryPlan(BaseModel):
    operation: Literal[
        "select",
        "spatial_filter",
        "aggregate",
        "distance",
        "within",
        "intersects",
        "nearest",
    ]

    target_table: str
    select_fields: list[str]
    filters: list[Filter]
    spatial: SpatialClause | None
    limit: int
```

模型不生成 SQL，只生成受控计划。

## 9.4 Compiler

新增：

```text
Backend/app/services/geosql/
├─ contracts.py
├─ schema_catalog.py
├─ compiler.py
├─ validator.py
└─ executor.py
```

Compiler 负责：

- table allowlist；
- column allowlist；
- operation allowlist；
- PostGIS function allowlist；
- 参数绑定；
- LIMIT；
- timeout；
- read-only transaction。

## 9.5 第二阶段才允许通用 SQL

只有 GeoQueryPlan 不能满足真实业务需求时，才评估真正 Text-to-SQL。

若开放通用 SQL，必须复用成熟 SQL AST 库，例如 SQLGlot 一类能力完成：

- AST parse；
- SELECT-only；
- 禁止 DDL；
- 禁止 DML；
- 禁止多语句；
- table allowlist；
- column allowlist；
- function allowlist；
- 强制 limit；
- parameterization；
- EXPLAIN cost guard。

禁止自己写 SQL parser。

---

# 10. 行政区事实源收敛

## 10.1 当前问题

空间计算使用：

```text
PostGIS spatial_regions
```

前端底图初始化使用：

```text
frontend/public/data/china-provinces.json
```

可能形成两个空间事实源。

## 10.2 目标

定义：

```text
PostGIS / canonical source
        ↓
versioned export
        ↓
china-provinces.json
```

前端 JSON 只能是派生 artifact / cache。

需要附带：

```text
dataset_version
generated_at
source_hash
```

## 10.3 验收

后端 region geometry 与前端 artifact hash / version 可追踪。

---

# 11. Linear / Agent 发布链统一

## 11.1 当前问题

Linear 模式独立执行：

```text
retrieve
→ Evidence
→ freeze
→ Answer
→ Reviewer
→ publish
```

Agent 模式又有一套。

## 11.2 目标

抽出：

```text
AnswerPublicationPipeline
```

输入：

```text
question
FrozenEvidence
reviewer_enabled
main_model
```

输出：

```text
PublishedResult
```

Linear：

```text
deterministic retrieval
→ AnswerPublicationPipeline
```

Agent：

```text
Controller selected evidence
→ AnswerPublicationPipeline
```

两条链共享：

- Answer Generator；
- Reviewer；
- Repair；
- fail-close；
- publication state。

---

# 12. 框架依赖策略

## 12.1 必选

### LangChain Core

只使用：

- Tool；
- schema；
- model tool binding；
- structured output。

### LangGraph

只使用：

- graph；
- state；
- conditional routing；
- interrupt/resume；
- checkpoint。

## 12.2 当前明确不引入

### LlamaIndex

原因：现有 Retrieval 已成熟，不需要第二套 RAG 数据层。

### AutoGen

原因：当前问题不是“缺多个自治 Agent”，而是单 Agent Runtime 边界失控。

### Multi-Agent

当前不做。

只有真实 E2E 证明：

```text
单 Controller 无法稳定处理
RAG + GIS + GeoSQL
```

才进入下一轮设计。

---

# 13. 状态模型

建议核心 Graph State：

```python
class GeoAIAgentState(TypedDict):
    principal_id: str
    session_id: str
    turn_id: str
    trace_id: str

    question: str

    context_snapshot_id: str | None

    evidence_catalog: list[EvidenceRef]
    selected_evidence_ids: list[str]
    frozen_evidence_snapshot_id: str | None

    available_tools: list[str]
    observations: list[ToolObservation]

    pending_browser_execution: PendingBrowserExecution | None

    controller_decision: ControllerDecision | None
    draft_answer: GeneratedAnswer | None
    review: ReviewResult | None

    publication_state: str | None
```

## 13.1 状态权威规则

- durable business state：Postgres；
- Graph checkpoint：不得成为第二业务事实源；
- Browser map state：browser receipt / snapshot；
- Evidence：Evidence Ledger；
- model context：derived projection；
- 前端 Zustand：UI projection，不是 Agent 事实源。

---

# 14. 分阶段实施计划

## Phase 0：事实源收敛

### 目标

先消除架构风险。

### 工作项

- [x] Production `PostgresAgentStore` fail closed
- [x] InMemory 仅测试显式注入
- [x] App 级 AgentStore 单例
- [x] Search / Agent routes 注入同一实例
- [x] DB outage consistency tests

### 2026-09-30 实施记录

- 新增 `Backend/app/services/agent/dependencies.py`，应用层只暴露一个共享 `AgentStore` 实例；
- `search_routes.py`、`agent_routes.py`、`AgentSessionService`、`AgentTraceService` 已统一复用该实例；
- `PostgresAgentStore` 不再默认创建 `InMemoryAgentStore`，数据库不可用且未显式注入 fallback 时抛出 `AgentStoreUnavailableError`；
- `InMemoryAgentStore` 仅可通过测试/显式依赖注入使用，不再是生产静默降级路径；
- 新增 `Backend/tests/test_agent_store_single_source.py`，覆盖 fail-closed、显式 fallback、API 入口共享 Store；
- `Backend/tests` 全量回归已通过；仅存在既有 Pydantic/legacy wire 等弃用告警，无本阶段新增测试失败。

### 完成标准

不得存在生产静默内存 fallback。

---

## Phase 1：物理拆 Runtime（已完成本阶段边界拆分）

### 工作项

- [x] SessionLoader
- [x] BrowserContinuationHandler
- [x] ContextProjector
- [x] ToolExecutionCoordinator
- [x] AnswerPublicationPipeline
- [x] ReviewerPipeline
- [x] Publisher

### 2026-09-30 第一批物理拆分记录

- 新增 `Backend/app/services/agent/orchestration/session_loader.py`：只负责 authoritative session / pending execution 装载，不承担语义判断；
- 新增 `Backend/app/services/agent/orchestration/browser_continuation.py`：集中 continuation token、browser receipt 匹配、claim-once、receipt observation/evidence 与 supersede 语义；
- 新增 `Backend/app/services/agent/orchestration/context_projector.py`：集中 Evidence Catalog、Map Context、Context Frame、动态 `ExecutableActionState` 与 Controller Projection 构造；
- 新增 `Backend/app/services/agent/orchestration/tool_execution.py`：集中 Tool 校验、执行、timeout / unavailable / fuse 异常分类和 tool lifecycle event 构造；
- 新增 `Backend/app/services/agent/orchestration/reviewer_pipeline.py`：集中 Reviewer #1 → 受限 repair → Reviewer #2 的固定闭环，并保持 Frozen Evidence 与 repair scope 不变；
- 新增 `Backend/app/services/agent/orchestration/answer_publication.py`：集中 Answer Generator → Reviewer Pipeline 的 grounded publication 前置链，供 Agent / Linear 后续共享；
- 新增 `Backend/app/services/agent/orchestration/publisher.py`：统一持久化 `publication_completed`、`assistant_message`、session / evidence，避免 Runtime 各分支重复维护发布副作用；
- `AgentRuntime.run()` 已改为消费上述边界，不再内联实现对应逻辑；
- 新增 `Backend/tests/test_agent_orchestration_boundaries.py`，覆盖 session load、动态 Action Surface、browser continuation receipt evidence；
- 本阶段拆分后 `AgentRuntime` 已由约 2400+ 行降至 1738 行；`Backend/tests` 全量回归通过，未改变 Controller / ToolRuntime / Evidence / Browser receipt 对外协议。
- **注意**：Phase 1 的目标是先形成物理边界且保持行为；`AgentRuntime` 收敛到纯 facade + lifecycle 属于 Phase 3 LangGraph 编排验收，不在本阶段提前伪装完成。

### 原则

先拆模块，不改变行为。

### 完成标准

现有回归测试与真实行为全部保持。

---

## Phase 2：LangChain Tool 标准化

### 工作项

- [x] Pydantic models → LangChain Tools
- [x] Controller 使用 bind_tools
- [x] 标准 ToolCall → GeoAI Tool Adapter
- [x] 保留 ToolRuntime Policy / Validation
- [x] 删除 legacy wire

### 2026-09-30 实施记录

- 依赖代际已统一到可同时支持 Python 3.12 / Pydantic 2 / LangChain / LangGraph 的组合；当前虚拟环境 `pip check` 无 broken requirements；
- 新增 `Backend/app/services/agent/langchain_tooling.py`：直接复用现有 `ToolRegistry + Pydantic input_model` 投影为 `StructuredTool`，不复制业务 Tool 实现；
- LangChain Tool 仅作为标准 schema / tool-call contract，直接执行会 fail closed；真实领域执行仍唯一进入 `ToolRuntime`；
- `ModelRequest / ModelResponse` 已增加标准 tools / tool_calls 通道，OpenAI-compatible provider ToolCall 被归一为标准 `{name,args,id,type}`；
- Controller 当前动态 Action Surface 会投影为 LangChain Tool schema，并通过 provider 原生 Tool Calling 通道发送；Control Action 继续使用独立结构化输出；
- 新增 `controller_decision_from_tool_call()` 薄适配层，标准 ToolCall 仍须经过当前 capability surface 与 `ToolRegistry.validate_arguments()`；
- 删除 Controller legacy wire normalize：不再接受 `name`、`tool_name`、`thought → reason`、`evidence_ids → selected_evidence_ids` 等模型输出兼容路径；文本编码的 `{"action":"tool_call"...}` 也会被拒绝，领域工具只有原生 ToolCall 一个入口；
- Controller Prompt 已移除重复的手写 `input_schema=`，参数 schema 唯一由 Pydantic → LangChain Tool → provider schema 生成；
- 删除未被生产代码引用的 `ComposeAnswerInput` 双字段兼容模型；
- 新增/更新 `test_agent_langchain_tooling.py`、Controller、协议、Runtime、审计与 stream/continuation 回归；按仓库正确 `PYTHONPATH=.;Backend` 执行 `Backend/tests` 全量回归通过；
- 新增 `langchain-openai==1.0.3`，与现有 `openai==1.109.1` / `langchain-core==1.6.5` 同代兼容，不升级 OpenAI SDK 主版本；
- Controller 的工具请求已真正改为 request-scoped `ChatOpenAI(...).bind_tools(...)`，动态 Action Surface 通过 LangChain 绑定到模型，模型输出从标准 `AIMessage.tool_calls` 进入 `controller_decision_from_tool_call()`；
- `tool_choice=auto` 且 `parallel_tool_calls=false`，保持 GeoAI 当前“一次 Planning Step 只允许一个 ToolCall”的既有控制语义；
- 删除 `LLMConfig.chat_completion_with_tools()` 自研 provider ToolCall 路径，避免 LangChain 与手写 OpenAI-compatible Tool Calling 两套实现并存；
- `test_agent_stage_policy.py` 已增加真实 `bind_tools → ainvoke → AIMessage.tool_calls` 合约测试；
- 完成上述切换后再次执行 `Backend/tests` 全量回归，100% 通过；Phase 2 至此达到“模型层不再手工维护通用 Tool Calling”的完成标准。

### 完成标准

模型层不再手工维护通用 tool-call JSON schema / legacy wire。

---

## Phase 3：LangGraph 编排

### Graph

```text
load_turn
   ↓
project_context
   ↓
plan
   ├─ direct_answer → publish
   ├─ clarify → publish
   ├─ limitation → publish
   ├─ tool_call → execute_tool
   │                   ├─ browser → interrupt
   │                   └─ server → project_context
   └─ compose → answer
                    ↓
                  review
                    ↓
                  publish
```

### 完成标准

Runtime 只剩 facade + lifecycle；图节点具备明确物理文件边界。

### 2026-09-30 第一批实施记录

- 新增 `Backend/app/services/agent/graph/`，建立 `state.py`、`transitions.py`、`graph.py` 与独立 `nodes/` 物理边界；
- 已编译最小 LangGraph 拓扑：`load_turn → project_context → plan → execute_tool / generate_answer / publish`，server Tool 回环 `project_context`，browser Tool 进入 `await_browser`，grounded answer 进入 `review → publish`；
- `AgentGraphState` 明确只保存 principal/session/turn/trace ID、当前路由决定、ToolCall 引用与 `selected_evidence_ids` 等瞬态编排信息；不保存 Session、Event Log、Evidence Ledger、Frozen Evidence、Map State、Browser Receipt，避免 Graph checkpoint 成为第二业务事实源；
- 新增 `Backend/tests/test_agent_langgraph_skeleton.py`，覆盖 Graph State 事实源边界、plan/tool 确定性路由和拓扑编译；
- 第二批新增 `graph/planning.py`，把真正需要先迁移的 Planning 子图收敛为 `project_context → plan → execute_tool → project_context`；Control Action、Browser handoff 与 terminal tool error 从该子图确定性退出，不再把尚未迁移的 Answer/Reviewer/Publish 节点伪装成已接管生产链；
- `PlanningGraphContext` 只注入 request-scoped 的投影、Controller 与 ToolExecution 回调；投影/Decision/ToolOutcome 只作为瞬态运行对象存在，不写入 Graph State/checkpoint，因此没有复制 Session、Evidence Ledger 或 Browser Receipt；
- 新增 `test_agent_langgraph_planning.py`，已验证 server tool 后重新投影再规划、browser handoff 终止、terminal tool error 终止三条真实控制流；
- **生产入口已切换 Planning 段**：`AgentRuntime.run()` 已通过 `build_planning_graph().ainvoke(...)` 执行 Context 投影 → Controller → server Tool → 重投影/再规划；原 Runtime 内部对应 Tool execution/replan 控制流已移除。Cancellation、ResourceFuse、RetrievalUnavailable 也已纳入图入口/出口检查。
- **Phase 3 当前状态**：已完成。LangGraph 已接管 Context → Controller → Tool → Observation → compose/freeze → Answer/Reviewer/Publish 及所有终态分发。

- 2026-09-30 第四批：已删除 LangGraph 返回后的第二套 Tool execution / Observation 兼容控制流；server Tool 现在只经 Planning Graph 执行。
- `compose_answer` 已进入 Graph `handle_control` 边界：Evidence budget 拒绝后回到再规划，通过后建立 Frozen Evidence 并以 `publication_kind=compose_answer` 交给既有 Answer Publication Pipeline。
- 新增 compose 控制边界回归，确认 control action 不进入 Tool execution；Runtime + cancellation + browser continuation + Planning 定向回归 30 项通过。
- 2026-09-30 第五批：Graph 新增唯一 `finalize_terminal` 节点；`compose_answer` 不再退出 Graph 后由 Runtime 继续发布，而是在 Graph 内调用既有 `AnswerPublicationPipeline`，继续复用原 Answer Generator → Reviewer → repair → Publisher，不复制任何发布实现。
- Evidence budget rejection 已改为 Graph 内部 `handle_control → project_context → plan` 重新规划，删除 Runtime 外层重新 `ainvoke()` 的补偿循环，Planning 控制流保持单轨。
- `direct_answer`、`clarify`、`limitation`、browser handoff、resource fuse、retrieval unavailable、cancelled 也统一经 `finalize_terminal` 分发；迁移中发现并修复“Controller 决策后、发布前取消”的竞态，统一在终态入口再次检查 durable cancellation。
- `Backend/tests` 全量回归已重新执行并 100% 通过（2026-09-30 当前工作树）；存在的告警均为既有 Pydantic / `datetime.utcnow()` 弃用告警。
- **Phase 3 收口（2026-09-30）**：新增 TurnLifecycleCoordinator 统一新 Turn / browser continuation / pending supersede / legacy history bootstrap / main model resolve；清理旧 no-op shadow graph，仅保留生产 planning.py + state.py 单一拓扑。

---

## Phase 4：GIS 闭环

- [x] expose `create_buffer`
- [x] add `render_geojson_layer`
- [x] overlay result → render
- [x] buffer result → render
- [x] receipt → updated map context

### 2026-09-30 实施记录

- `create_buffer` 直接复用既有 `SpatialService.create_buffer()` PostGIS 实现，仅补 Agent `ToolSpec + ToolRuntime` 薄适配；输入协议按 PRD 收敛为 `center + distance_m`，结果写入 Evidence Ledger。
- 新增唯一通用 Browser Tool `render_geojson_layer`，输入为校验后的 `geojson + name + optional style`；没有为 Buffer / Overlay 分别创建渲染工具。
- 2D OpenLayers Runtime 复用现有 `userVectorCapabilities + createUserVectorLayer` 注册结果图层，生成稳定 `layer_ref / feature_ref`；未新建第二套图层仓库。
- Browser capability 仍由 `map_context.supported_tools` 动态决定：2D 声明 `render_geojson_layer`，3D Cesium 未实现因此不暴露，避免 false capability。
- `spatial_overlay` 与 `create_buffer` 均已用回归验证可将返回 GeoJSON 接入同一个 `render_geojson_layer` Browser handoff。
- Browser receipt 在渲染后重新读取权威 Runtime snapshot，返回更新后的 `revision / user_layers / layer_ref`，下一步 Controller 从 receipt 获得新 map context。
- 前端 `test:unit`：10 个 Vitest 文件、52 个测试通过，附加 4 组 TSX 脚本测试通过；`npm run lint` 通过。
- Backend `tests` 全量回归 100% 通过；`git diff --check` 通过，仅保留既有 Pydantic / `datetime.utcnow()` 弃用告警。

---

## Phase 5：GeoSQL

- [x] schema catalog
- [x] GeoQueryPlan
- [x] compiler
- [x] validator
- [x] read-only executor
- [x] Agent tool
- [x] result → evidence
- [x] geometry result → `render_geojson_layer`

---


### GeoSQL V1 implementation record (2026-09-30)

- Added `Backend/app/services/geosql/`: contracts, explicit schema catalog, validator, deterministic compiler, read-only executor.
- V1 accepts `GeoQueryPlan`, never SQL text. Current catalog allowlists `spatial_regions` and approved columns.
- Identifiers enter SQL only after catalog validation; user values, geometry, distance and LIMIT are bound parameters; PostGIS functions come from fixed templates only.
- Executor enforces one SELECT statement, `SET TRANSACTION READ ONLY`, and statement timeout; direct DELETE / multi-statement input is rejected.
- Added Agent Tool `query_geospatial_data`; LangChain schema contains no `sql` field and provider health can remove it from the Action Surface.
- Tool results are written to Evidence Ledger. Geometry rows are normalized to one Geometry or GeometryCollection and require explicit `render_geojson_layer` for map side effects.
- Trace projection keeps plan metadata but redacts raw geometry coordinates and never exposes SQL text.
- Verification: GeoSQL + Agent targeted 58/58; Backend full suite 100%; frontend unit 52/52 plus TSX scripts; frontend lint passed; diff check passed.
- Verification boundary: code + automated verification only; real PostGIS data + real-model Tool Calling E2E is not yet claimed.

## Phase 6：事实源和发布链收口

- [x] region dataset version/hash
- [x] linear uses publication pipeline
- [x] delete duplicate paths
- [x] dead code audit
- [x] legacy protocol removal

### 2026-10-02 Phase 6 实施与收口记录

- **行政区事实源收敛**：
  - 新增 `Backend/app/services/spatial_region_export.py` 与 `test_spatial_region_export.py`（6 项单元测试全部通过）；
  - `compute_region_source_hash` 保证基于 adcode 排序的稳定 sha256 签名，生成版本号 `spatial-regions-v1-<hash[:12]>`；
  - `frontend/public/data/china-provinces.json` 补充 canonical `dataset_meta` 元数据，与后端 `spatial_regions` 事实源保持可追踪，禁止前端形成独立行政区事实源；
  - 提供 CLI 入口 `python -m app.services.spatial_region_export` 供同步与校验。
- **Linear / Agent 发布链统一**：
  - `SearchApplicationService.execute()` 的 linear 模式已接入 `agent_runtime.answer_publication_pipeline.run()`，统一复用 Answer Generator → Reviewer → repair → PublishedResult；
  - `SearchApplicationService.stream()` linear 分支直接复用 `execute()`，两条链路完全共享发布状态与审查策略；
  - `Backend/tests/test_search_agent_api.py` 覆盖 linear 模式使用 publication pipeline 与 reviewer 拦截。
- **协议与兼容层清理（legacy protocol removal & duplicate paths）**：
  - 彻底移除 `ControllerDecision.name` legacy wire 兼容属性，所有工具调用统一使用 `decision.tool` 与 `decision.action`；
  - `AgentRunResult` 生产实例化已全部收敛为唯一权威 `result=AgentPublicationResult`（`DirectAnswerResult`、`KnowledgeAnswerResult`、`ClarificationRequired`、`BrowserToolExecutionRequired`、`SafeLimitation`、`NoSafeAnswer`），移除旧式关键字传参；
  - `LangGraph` planning 节点工具名称提取对齐 `decision.tool`；
  - 清理根目录残留无用空文件。
- **全量自动化回归验证**：
  - 后端测试套件全量执行：100% 通过（无新增告警与失败）；
  - 前端 Vitest（10 个测试文件/52 个测试）+ 4 组 tsx 动态测试全量执行：100% 通过；
  - 前端代码检查（文本编码、API契约使用、TypeScript `tsc --noEmit`）：全量通过；
  - `git diff --check` 通过。

---

# 15. 禁止事项

实施过程中明确禁止：

1. 为了 LangGraph 再创建第二套 Evidence Ledger；
2. LangGraph checkpoint 取代 Postgres AgentStore；
3. LangChain Tool 直接访问 OpenLayers / Cesium；
4. LangChain Tool 绕过 ToolRuntime；
5. 保留旧 Tool wire 再新增第三套 wire；
6. 为 Buffer、Intersection、Difference 各写独立 render 工具；
7. 引入 LlamaIndex 重写现有 retrieval；
8. 引入 AutoGen 解决 Runtime 过大问题；
9. LLM 直接执行任意 SQL；
10. Production DB 失败后隐式切换 InMemory；
11. 前端 Zustand 成为 Browser Runtime 权威状态；
12. 为了兼容旧代码长期保留 shadow path。

---

# 16. 测试策略

## 16.1 单元测试

### Store

- Postgres unavailable fail closed；
- injected InMemory works in tests；
- store singleton。

### Tool

- Tool schema；
- invalid args；
- unavailable capability；
- timeout；
- policy deny；
- idempotency。

### GeoSQL

- allowlisted table；
- forbidden table；
- forbidden column；
- invalid operation；
- forced limit；
- parameterized value；
- read-only transaction。

## 16.2 Graph 测试

必须验证：

```text
knowledge question
→ retrieve
→ compose
→ answer
→ reviewer
→ publish
```

```text
GIS side effect
→ tool
→ interrupt
→ receipt
→ resume
→ continue
```

```text
tool failure
→ observation
→ controller
→ fail close / alternative
```

```text
no evidence
→ no knowledge compose
```

## 16.3 Browser E2E

### G01 Buffer

用户：

```text
以 104,30 为中心做 500m 缓冲并显示到地图
```

必须：

```text
create_buffer
→ PostGIS
→ render_geojson_layer
→ receipt
→ layer_ref
```

### G02 Overlay

```text
spatial_overlay
→ GeoJSON
→ render_geojson_layer
```

### G03 GeoSQL

```text
查询成都市范围内的监测点并显示
```

必须：

```text
GeoQueryPlan
→ SQL Compiler
→ PostGIS
→ evidence/result
→ map layer
```

---

# 17. 真实模型验收

不能只跑 mock。

必须使用真实 Controller 模型验证：

1. Knowledge Retrieval；
2. historical evidence reuse；
3. SHP import；
4. layer visibility；
5. vector style；
6. map locate；
7. feature inspection；
8. spatial relation；
9. overlay；
10. buffer；
11. analysis result rendering；
12. GeoSQL；
13. Browser interrupt/resume；
14. invalid layer_ref；
15. invalid feature_ref；
16. database unavailable；
17. reviewer pass；
18. reviewer reject；
19. long conversation context；
20. session reload after process restart。

---

# 18. 架构验收门槛

只有以下条件全部满足，PRD 才能标记 `IMPLEMENTED / VERIFIED`。

## A. 状态

- [x] Production 只有一个 AgentStore 事实源
- [x] Browser Map 只有一个当前 Runtime authority
- [x] Evidence 只有一个 Ledger authority
- [x] Graph checkpoint 不成为业务事实源

## B. 协议

- [x] Tool Calling 单协议
- [x] 无 legacy Controller wire
- [x] 无平行 Tool schema
- [x] Control Action 与 Tool 分离

## C. Runtime

- [x] AgentRuntime 不再是巨型业务实现
- [x] 各 Node 有物理文件边界
- [x] Tool execution 与 planning 分离
- [x] Answer publication 独立

## D. GIS

- [x] Buffer Agent Tool
- [x] PostGIS Overlay
- [x] `render_geojson_layer`
- [x] result → map 完整闭环

## E. GeoSQL

- [x] 受控 Plan
- [x] deterministic compiler
- [x] parameterized SQL
- [x] read-only
- [x] allowlist
- [x] limit
- [x] timeout

## F. 验证

- [x] Backend tests（全量回归 100% 通过）
- [x] Frontend unit tests（52 单元测试 + 4 组脚本 100% 通过）
- [x] lint / typecheck（文本编码、API 契约、TypeScript `tsc --noEmit` 全量通过）
- [ ] live cluster browser E2E（待部署集群联调验收）
- [ ] live cluster real-model E2E（待部署集群联调验收）
- [x] restart durability
- [x] failure-path E2E

---

# 19. 完成定义

本 PRD 的成功不以“已经引入 LangGraph”作为标准。

真正成功标准是：

> **GeoAI 的通用 Agent 基础设施减少，自研代码集中到 GIS / RAG / 安全执行等领域价值；Agent Runtime 物理拆分清晰；工具协议唯一；状态事实源唯一；PostGIS 分析结果可统一上图；GeoSQL 具备安全、可控、可验证的端到端链路。**

最终应达到：

```text
成熟框架
负责通用机制

GeoAI
负责领域能力

二者之间
只有一层薄适配
```

而不是：

```text
成熟框架一套
GeoAI 自研一套
旧兼容层一套
三套同时存在
```

---

# 20. 与岗位能力的最终映射

| 岗位要求 | PRD 完成后的 GeoAI 对应能力 |
|---|---|
| LangChain / Agent | LangChain Core Tool + structured output |
| Agent orchestration | LangGraph durable graph |
| Function Calling | 标准 Tool Calling |
| GIS Tools / Plugins | GeoAI Tool Boundary + Browser/PostGIS Tools |
| 缓冲区分析 | `create_buffer` |
| 叠置分析 | `spatial_overlay` |
| 路径规划 | 后续独立 provider，不在本轮硬造 |
| 地理编码 | 后续接权威 provider，不伪实现 |
| Text-to-SQL / GeoSQL | GeoQueryPlan + Compiler |
| PostGIS | SpatialService + GeoSQL Executor |
| RAG | 原有 hybrid retrieval + Evidence |
| 地图交互 | Browser Runtime + `render_geojson_layer` |
| GeoJSON | GIS Runtime 统一交换格式 |
| 工程化 | 单事实源、durable state、trace、receipt、failure semantics |

---

# 21. 实施优先级总结

```text
P0
AgentStore 单事实源

P1
Runtime 物理拆分

P1
LangChain Tool 标准化

P1
LangGraph 编排

P1
Buffer + render_geojson_layer

P1
GeoQueryPlan / GeoSQL

P2
Linear / Agent publication 收敛

P2
行政区数据版本化

P3
地理编码 provider

P3
路径规划 provider
```

**不应在 P0/P1 完成前继续扩充新的 Agent 特殊分支。**
