# GeoAI 对公司 RAG 通用 Agent 能力增量吸收与项目完成度收口 PRD

> 日期：2026-09-25  
> 类型：增量收口 PRD  
> 目标仓库：GeoAI（`D:\work\Project\ragAI知识库 (2)\ragAI知识库`）  
> 参考仓库：公司 RAG（`D:\work\Project\agentic rag`）  
> 核心原则：公司 RAG 是通用 Agent/RAG 能力参考实现；GeoAI 选择性吸收成熟通用能力，并保留/增强 GIS、Browser Runtime、真实地图状态闭环等自身能力。  
> 状态口径：本文严格区分“设计存在 / 代码实现 / 自动化测试 / 真实模型与真实浏览器 E2E”。任何一层未完成，不得用上一层代替。

---

## 1. 背景

GeoAI 当前已经不再是传统的“检索后直接让模型回答”的 RAG 项目。经过前序改造，项目已经具备以下主体能力：

- 独立 Agent Runtime；
- Main Controller；
- Tool Runtime；
- Working Evidence / Frozen Evidence；
- Answer Generator；
- 可选 Grounding Reviewer；
- 请求级 Stage Policy；
- PostgreSQL / pgvector 检索适配；
- Browser GIS Tool continuation；
- OpenLayers 真实地图状态、`layer_ref` / `feature_ref`、Tool Receipt；
- PostGIS / 地图联动；
- 文档解析、结构化 Chunking、上传与索引；
- GeoAI 36 条真实浏览器 E2E Harness。

前序后端适配设计的基本方向是正确的：

```text
公司 RAG
   │
   │ 提供通用 Agent/RAG 架构参考
   ▼
GeoAI
├── 通用 Agent 内核
│   ├── Controller
│   ├── Context
│   ├── Evidence
│   ├── Retrieval
│   ├── Answer Generator
│   ├── Reviewer
│   ├── Runtime / Publication
│   └── Observability
│
└── GeoAI 专属执行层
    ├── Browser Bridge
    ├── Active Map Runtime
    ├── OpenLayers / Cesium
    ├── layer_ref / feature_ref
    ├── Tool Receipt
    ├── PostGIS
    └── 真实地图状态闭环
```

但是，本次针对两个项目当前代码的逐项审计确认：

> GeoAI 主要吸收了公司 RAG 较早阶段的基础 Agent 架构；公司 RAG 在 2026-09-23 至 2026-09-24 继续完成了一批关键横切能力，而 GeoAI 尚未系统同步这些增量。

因此当前问题不是“还有几个 Bug”，而是：

> **GeoAI 的 GIS 执行层已经较强，但通用 Agent 智能层、上下文治理、动作契约、Reviewer 修复闭环、检索工程化、持久 Runtime、前端 Agent Process 等能力仍落后于参考仓库。**

本 PRD 的目的，是把这些差距正式收敛成一份增量实施标准，避免继续以零散补丁方式推进。

---

## 2. 项目关系重新确认

### 2.1 公司 RAG 的定位

公司 RAG 不是 GeoAI 的运行时依赖，也不是需要整体复制的代码库。

它的定位是：

> **通用 Agent / RAG 能力参考实现与契约来源。**

可复用的重点包括：

- ContextFrame / Context Projection；
- Controller 动作契约；
- 动态可执行动作面；
- Evidence 生命周期与历史 Evidence Memory；
- 请求级 Structured Output Schema；
- `direct_answer` / `clarify` / `compose_answer` 控制动作语义；
- Reviewer 修复闭环；
- Durable Runtime / Event Log / Replay 思路；
- Retrieval Candidate / Fusion / Rerank / Evaluation；
- 前端 Agent Process 投影与展示；
- 失败关闭与发布权威边界。

### 2.2 GeoAI 的定位

GeoAI 不是“公司 RAG + 地图页面”。

GeoAI 的终极目标是：

> **具备专业知识检索、上下文理解、任务规划、真实地图状态感知、GIS 工具执行、执行结果反馈和连续决策能力的 GIS Agent。**

其核心闭环必须是：

```text
用户目标
  ↓
结构化 Context
  ↓
Controller
  ↓
选择知识动作 / GIS 动作 / 控制动作
  ↓
Runtime 执行
  ↓
Evidence / Browser Receipt / MapContext / Runtime Facts
  ↓
重新进入 Controller
  ↓
直到任务完成
  ↓
Answer / Reviewer / Publication
```

GeoAI 必须拥有公司 RAG 不具备或不应具备的 GIS 专属能力：

- 浏览器是真实地图状态权威源；
- Active Map Runtime；
- 2D / 3D 地图执行；
- `layer_ref` / `feature_ref` 稳定对象身份；
- 浏览器工具 Receipt；
- 多步地图状态连续性；
- 数据导入、图层显隐、样式修改、定位、要素检查、空间分析；
- PostGIS 与浏览器地图协同。

### 2.3 明确禁止的错误方向

本次改造禁止采用以下方式：

1. 直接把公司 RAG 整套后端复制进 GeoAI；
2. 仅因为公司 RAG 有某能力，就强制 GeoAI 同步；
3. 把公司 RAG 的图谱能力作为 GeoAI 完成度前置条件；
4. 为了“代码一致”破坏 GeoAI 当前稳定的 Browser GIS Runtime；
5. 重做 GeoAI 已完成的 Evidence / Answer / Reviewer / GIS 基础链路；
6. 继续在前端用正则和字符串替换弥补后端 Context / Controller 的能力缺失；
7. 通过 Prompt 文字约定替代 Runtime Guard；
8. 用单元测试通过代替真实模型 + 数据库 + 浏览器 E2E。

---

## 3. 本次审计基线

本 PRD 基于 2026-09-25 对当前两个本地仓库的实际检查形成。

### 3.1 GeoAI 当前工作区

审计时确认：

- 当前主 checkout 存在未提交修改；
- `main` 当前相对 `origin/main` 为 `ahead 4`；
- 除主 checkout 外，当前还存在 2 个 detached DevSpace worktree，以及 1 个 `feature/v3-agent-native-g0-g1a` worktree；
- 因此“当前工作中的代码”和“main 稳定完成态”必须分开记录。

### 3.2 公司 RAG 当前参考状态

公司 RAG 当前已经存在并有测试覆盖的关键能力包括：

- `ContextFrame`；
- `ControllerContextFrameBuilder`；
- `previous_turn_runtime_facts`；
- 角色专用 Context Projection；
- 动态 `available_tool_names`；
- 动态 `available_control_actions`；
- `direct_answer`；
- IdentityResolution 门控 `clarify`；
- `knowledge_answer` 强制 `selected_evidence_ids`；
- 请求级 Controller JSON Schema；
- Controller clean protocol retry；
- Reviewer `REVISE` → Repair Scope → V2 → Reviewer #2；
- Durable Event Store / Runtime State / Replay；
- RRF / 多路候选 / Retrieval Planner / Reranker；
- Recall@K / MRR 等检索回归；
- Agent 前端步骤流 / Block Projector。

本次 fresh 定向测试抽查公司 RAG 的 Context / Evidence Memory / Main Controller / Publication Gate：

```text
45 passed
```

此结果只能证明对应定向自动化测试通过，不自动等价于公司 RAG 全量真实模型 E2E 已完成。

### 3.3 GeoAI 当前测试事实

本次审计确认：

- 前端 `test:gis`：2 / 2 通过；
- 前端 `test:geoai-harness`：3 / 3 通过；
- 前端 text encoding / API contract / TypeScript lint 通过；
- 前端 production build 通过；
- 当前仓库根 `venv` 中未安装 `pytest`，因此本轮无法使用仓库自带 Python 环境 fresh 复验 Backend 全量测试；
- `evals/results/latest/results.json` 不存在；
- GeoAI 真实 36/36 E2E 尚无本次可验证执行结果；
- 因此 Backend 自动化测试结果、真实 LLM + DB + Browser E2E 都不得引用旧报告冒充本轮验证。

因此当前项目不得标记为“整体完成”。

---

## 4. 当前已实现基线：不得重复开发

以下能力已经存在，后续实施必须在其上增量升级，不得重新造第二套。

### 4.1 Agent 主体

已有：

- `Backend/app/services/agent/runtime.py`
- `Backend/app/services/agent/controller.py`
- `Backend/app/services/agent/tool_runtime.py`
- `Backend/app/services/agent/tools.py`
- `Backend/app/services/agent/session.py`
- `Backend/app/services/agent/events.py`
- `Backend/app/services/agent/stage_policy.py`

不得重新创建平行 `agent_v2` / `new_runtime` / `planner_runtime`。

### 4.2 Evidence 生命周期

已有：

```text
Retrieval Candidate
  ↓
Working Evidence
  ↓
Controller 显式选择
  ↓
Frozen Evidence Snapshot
  ↓
Answer Generator
```

该方向正确。

后续只补：

- 历史 Evidence Memory；
- Context 投影；
- 更强的 evidence catalog；
- 可重建持久证据状态。

不得退回“检索结果全部自动进 Prompt”。

### 4.3 Answer Generator

已有 Frozen Evidence 边界和 Answer Unit 结构。

后续只补：

- Reviewer 修复契约；
- 请求级结构化输出约束；
- 与 ContextFrame 的角色投影对齐。

### 4.4 Reviewer 基础能力

已有：

- 请求级开关；
- 默认关闭；
- Answer Unit ↔ Evidence grounding 审查；
- Reviewer 不能重新检索。

不得重新引入“Reviewer → Controller 重新规划”的路径。

### 4.5 Stage Policy / Main Model Identity

已有请求级 Main model 解析与不同阶段 reasoning policy。

后续只需验证所有新阶段继续遵守同一模型身份，不创建 provider 特判。

### 4.6 Browser GIS 主闭环

已有：

```text
Controller
  ↓
Browser Tool
  ↓
Backend pending tool call
  ↓
Frontend Browser Bridge
  ↓
真实地图 Runtime
  ↓
BrowserToolReceipt
  ↓
Backend continuation
  ↓
Agent 继续决策
```

这是 GeoAI 已完成的核心差异化能力，必须保留。

### 4.7 OpenLayers GIS 对象身份

已有：

- `layer_ref`；
- `feature_ref`；
- user vector dataset；
- 样式修改；
- 图层显隐；
- 地图定位；
- feature inspection；
- geometry retrieval。

不得重新使用 `window`、组件内部对象或临时索引作为 Agent 对象身份。

### 4.8 文档解析与 Chunking

已有：

- Markdown；
- DOCX；
- XLSX；
- 标题层级；
- Markdown table；
- code fence 原子块；
- header path。

此能力当前不属于主要差距，不应优先重构。

### 4.9 Real E2E Harness

已有 36-task manifest、Playwright runner、preflight 和结果结构。

缺的是：

> **真实执行结果，而不是 Harness 本身。**

---

## 5. P0：Context / Memory 架构必须升级

### 5.1 当前问题

GeoAI 当前 `AgentContextBuilder` 本质仍是：

```text
prior user/assistant events
  ↓
拼接成文本
  ↓
按 max_characters 截取最近内容
  ↓
summary string
```

同时只额外附带：

```text
working_evidence
```

这存在以下问题：

1. 对话文本、证据、Runtime Fact 混为同一上下文层级；
2. 历史 Evidence 不能作为一等可选择对象投影给 Controller；
3. 上一轮 GIS Tool Receipt / Map Runtime Fact 不能稳定进入下一轮决策；
4. 上一轮成功/失败动作不能形成结构化执行事实；
5. 当前仅按字符预算，而不是语义角色与 token budget；
6. 不同模型阶段看到的上下文缺少职责隔离；
7. 前端不得不额外承担 follow-up 解析与 query rewrite。

### 5.2 目标

吸收公司 RAG 的 ContextFrame 思路，但不直接复制业务字段。

GeoAI 目标结构：

```text
GeoAIContextFrame
├── current_request
│   ├── original_question
│   ├── user_constraints
│   └── request_flags
│
├── conversation_memory
│   ├── recent_turns
│   ├── dialogue_focus
│   └── rolling_summary
│
├── evidence_memory
│   ├── current_working_evidence
│   ├── historical_citable_evidence
│   └── evidence_catalog
│
├── runtime_facts
│   ├── previous_turn
│   ├── previous_tool_outcomes
│   ├── publication_state
│   └── pending/resume facts
│
├── gis_runtime_facts
│   ├── active_map_context
│   ├── active_dimension
│   ├── supported_tools
│   ├── layer refs
│   └── bounded feature refs
│
├── identity_state
│   └── optional IdentityResolution
│
└── policy_state
    ├── available_capabilities
    ├── available_control_actions
    └── fuse / cancellation state
```

### 5.3 角色投影

必须建立：

```text
ContextFrame
├── for_controller()
├── for_retrieval()
├── for_answer()
└── for_reviewer()
```

规则：

- Controller 可以看任务状态、历史 Evidence catalog、Runtime facts、MapContext、动作面；
- Retrieval 只看查询目标和必要约束；
- Answer Generator 只看用户问题、Answer Requirements、Frozen Evidence 和必要非知识 Runtime Facts；
- Reviewer 只看用户目标、候选 Answer Units、Frozen Evidence 与必要引用信息；
- Reviewer 不得获得新的检索规划权；
- Answer Generator 不得直接看到整个历史 Evidence Pool。

### 5.4 历史 Evidence 使用规则

必须实现以下标准流程：

```text
新一轮用户问题
  ↓
Controller 查看历史 Evidence Catalog
  ↓
历史证据是否足够？
  ├── 是 → 显式 selected_evidence_ids
  │          ↓
  │        Answer Generator
  │
  └── 否 → 针对性 retrieve_kb
             ↓
           新 Evidence
             ↓
           显式选择
```

禁止：

- 当前 Evidence = 0 就强制检索；
- 自动冻结全部历史证据；
- 将历史 Evidence 文本直接拼入普通聊天 history；
- 由 Runtime 判断“语义上历史证据够不够”。

“够不够”属于 Controller 语义判断。

### 5.5 前端 history 的迁移

当前客户端仍会把完整聊天消息重新传给后端。

目标：

```text
Frontend
  └── session_id + current user request

Backend Session / Event Store
  └── authoritative conversation/runtime facts
```

迁移期可以继续接受 `history`，但：

- 标记为 compatibility input；
- 不得与 Session Event Store 长期形成“双真源”；
- 最终主链必须依赖 session state 重建上下文。

---

## 6. P0：Controller 从“工具选择器”升级为完整语义 Controller

### 6.1 当前问题

GeoAI 当前 Controller 主要协议是：

```json
{
  "name": "retrieve_kb",
  "arguments": {}
}
```

这使 Controller 事实上被限制成：

> 每一步必须调用一个工具。

这不符合实际 Agent 状态空间。

### 6.2 目标动作空间

必须明确分成两类。

#### Executable Capabilities

例如：

```text
retrieve_kb
reuse_evidence / evidence lookup
spatial_query
locate_map
set_layer_visibility
set_vector_style
inspect_layer_features
...
```

#### Control Actions

```text
compose_answer
direct_answer
clarify
```

二者不得混为“都是 Tool”。

### 6.3 `direct_answer`

必须吸收公司 RAG 当前语义：

> `direct_answer` 是 Controller 对非知识型场景的最终用户可见表达能力。

适用：

- 普通对话；
- Runtime 状态说明；
- 执行过程解释；
- 不依赖内部 KB Grounding 的请求；
- 会话控制说明。

不适用：

- 公司/项目内部知识事实；
- 规范条文；
- 检索结果解释；
- Evidence 支撑的业务结论。

必须满足：

```text
direct_answer.answer = 完整用户可见文本
```

不得把：

```text
"direct_answer"
```

本身当成回答正文。

`direct_answer`：

- 不是 Tool Result；
- 不计入 Tool Call；
- 不进入 Answer Generator；
- 不进入知识型 Reviewer；
- 直接走确定性的 publication contract。

### 6.4 `compose_answer`

知识型回答必须：

```text
compose_answer
  ├── answer_kind
  ├── answer_mode
  ├── selected_evidence_ids [required]
  └── answer_requirements
```

其中：

> `knowledge_answer` 必须显式提供非空 `selected_evidence_ids`。

禁止：

- 未选择证据时自动 freeze-all；
- Runtime 替 Controller 选择“最相关证据”；
- current evidence 非空就全部进入 Answer Generator。

### 6.5 `clarify`

`clarify` 只用于实体身份确认。

目标协议：

```text
clarify arguments = {}
```

候选项必须来自 Runtime 权威 `IdentityResolution`，不是 LLM。

只有同时满足：

```text
IdentityResolution exists
AND status in {ambiguous, unresolved}
AND candidates valid
```

时才向 Controller 暴露 `clarify`。

否则：

```text
clarify ∉ available_control_actions
```

禁止 LLM：

- 自主创建候选；
- 自主生成 entity_id；
- 自主扩展 options；
- 把 `clarify` 当通用自由追问能力。

---

## 7. P0：建立统一动态可执行动作面

### 7.1 问题

目前 GeoAI 仍存在“Registry 中注册过 = 模型可以看到”的倾向。

这对 GIS Agent 是错误的，因为 GIS 工具是否可执行取决于：

- 当前是否存在 active map runtime；
- 当前是 2D 还是 3D；
- 当前有哪些 layer_ref；
- 是否有 available file；
- 是否存在 user vector layer；
- 是否存在 feature_ref；
- Runtime 是否 ready；
- 是否处于 continuation；
- 当前动作是否被 execution constraint 禁止。

### 7.2 单一动作事实源

必须建立一个共享的：

```text
ExecutableActionState
```

它至少产出：

```text
available_capabilities
available_control_actions
capability_schemas
unavailable_reasons (runtime only / optional UI)
```

### 7.3 必须共同消费该状态的边界

同一个状态必须供：

1. Controller Prompt；
2. Controller JSON Schema；
3. Controller parser；
4. Runtime Guard；
5. Tool Runtime；
6. Browser Tool allowed set；
7. 前端 Agent Process 展示当前能力（如需要）。

不得各自维护一份字符串列表。

### 7.4 GIS 动态能力

应与当前 Active Map Runtime PRD 合并理解：

```text
Backend registered browser tools
INTERSECT
map_context.supported_tools
INTERSECT
runtime allowed actions
=
Controller 当前可执行 Browser Capabilities
```

例如：

#### 3D 当前只实现

```text
locate_map
set_layer_visibility
```

则 Controller 不应看到：

```text
import_vector_dataset
set_vector_style
inspect_layer_features
get_feature_geometry
```

#### 2D 无 user-vector layer

则不应看到需要 user-vector 的动作。

这不是 Prompt 优化，而是物理可执行性约束。

---

## 8. P0：Structured Output 协议升级

### 8.1 当前问题

GeoAI 已经有：

- structured candidate；
- JSON parsing；
- clean retry；
- retry 时 reasoning off；
- `reasoning_content` 不作为正式答案。

但 Controller 当前主要还是：

```text
response_format = json_object
+
本地 Pydantic / parser 校验
```

对于小模型，这仍然容易产生：

- action/name 错位；
- 参数字段缺失；
- 多余字段；
- tool_call_id 幻觉；
- 动作名与当前可执行动作不一致；
- reasoning 正确但最终 structured action 错误。

### 8.2 目标

参考公司 RAG：

```text
ExecutableActionState
  ↓
Request-scoped JSON Schema
  ↓
Endpoint capability check
  ↓
Provider structured output / JSON Schema
  ↓
Local validation
```

Schema 必须动态生成，而不是静态全工具 schema。

### 8.3 Controller Schema

要求：

- 当前不可执行工具不进入 enum；
- 每个工具拥有自己的 arguments schema；
- `compose_answer` 使用独立 branch；
- `direct_answer` 使用独立 branch；
- `clarify` 只在合法状态出现；
- unknown field = reject；
- required parameter = schema required；
- tool_call_id 继续由 Runtime 生成，不允许模型负责身份字段。

### 8.4 Provider 能力降级

必须 provider-neutral：

```text
支持 JSON Schema
  → 使用 request-scoped schema

只支持 json_object
  → json_object + local validation

都不支持
  → plain text JSON + local validation + bounded retry
```

禁止：

- 针对 DeepSeek 写业务协议特判；
- 针对 Ollama 写另一套 Controller；
- 使用模型名称决定业务 schema。

---

## 9. P0：Reviewer 修复闭环

### 9.1 当前状态

GeoAI 工作区已经新增：

```text
Answer V1
  ↓
Reviewer
  ├── supported → publish
  └── unsupported / overstated
       ↓
     build_answer_repair_scope
       ↓
     generate_repair
       ↓
     validate_answer_repair_draft
       ↓
     Reviewer #2
```

因此“Reviewer Repair 完全未吸收”的旧判断已经过时。

但当前仍不能标记完成，原因包括：

- repair scope 对 editable unit 当前允许使用整个 Frozen Snapshot 的 citations，尚未收紧到 finding-linked evidence；
- 本轮无法使用仓库自带 Python 环境 fresh 执行相关 Backend pytest；
- 尚无真实模型 Reviewer REVISE → V2 → Reviewer #2 E2E 结果；
- Publication Authority 本身仍存在状态契约冲突。

当前状态应记为：**PARTIAL / CODE_PRESENT / NOT_E2E_VERIFIED**。

### 9.2 目标流程

吸收公司 RAG 已实现模式：

```text
Answer Generator V1
        ↓
Reviewer #1
   ├── PASS
   │    ↓
   │  Publication
   │
   └── REVISE
        ↓
Deterministic Repair Scope
        ↓
Answer Generator V2
        ↓
Deterministic Repair Validation
        ↓
Reviewer #2
   ├── PASS → Publication
   └── REVISE / invalid → fail-close
```

### 9.3 Repair Scope 原则

Runtime / Finalizer 机械生成：

```text
answer_repair_scope_v1
```

要求：

- Frozen Evidence 不变；
- 不新增 Evidence；
- 不回 Controller；
- 不改变 answer_kind；
- 不改变不可编辑 unit；
- Reviewer finding 只授权对应 unit 修复；
- 不增加第三次 Answer Generation；
- 第二次仍失败则 fail-close。

### 9.4 Reviewer 权限边界

Reviewer 不得输出：

- evidence_gap；
- missing_fact；
- retrieval plan；
- new tool call；
- new evidence request。

Reviewer 只回答：

> 当前 Answer Unit 是否被当前 Frozen Evidence 支撑，以及应如何在既定证据范围内修正。

---

## 10. P1：RAG 检索工程能力升级

### 10.1 当前 GeoAI 检索

当前已有：

- exact standard code；
- keyword；
- vector；
- metadata filter；
- spatial filter；
- local deterministic rerank。

当前主要融合方式接近：

```text
exact results
keyword results
vector results
  ↓
按结果顺序 merge + dedupe
  ↓
规则加分 rerank
```

这属于可用基础版，不等于公司 RAG 当前检索能力。

### 10.2 应吸收能力

优先吸收“机制”，不要复制业务规则：

#### Candidate Pipeline

```text
multiple independent retrieval branches
  ↓
Candidate provenance
  ↓
RRF / weighted fusion
  ↓
candidate_k pool
  ↓
reranker
  ↓
quality / admission
  ↓
top_k evidence candidates
```

#### Query Planner

根据 Controller 提交的检索目标决定：

- query variants；
- candidate_k；
- top_k；
- rerank 是否开启；
- 可选 retrieval mode。

注意：

> Query Planner 只能服务 Controller 已决定的“需要检索”，不能重新抢占 Controller 的任务规划权。

### 10.3 Reranker

当前本地规则 reranker 可以保留作为 fallback。

目标抽象：

```text
RerankerPort
├── deterministic fallback
├── local model
└── remote HTTP reranker
```

### 10.4 检索评估

必须补充：

- Recall@K；
- MRR；
- hit rate；
- regression dataset；
- hybrid vs vector vs keyword vs rerank ablation。

没有检索质量回归时，不得声称“RAG 已完全吸收公司 RAG”。

---

## 11. P1：Durable Runtime / Replay

### 11.1 当前问题

GeoAI 工作区已经新增：

- `PostgresAgentStore`；
- `geoai_agent_sessions`；
- `geoai_agent_events`；
- `geoai_agent_evidence`；
- `geoai_context_snapshots`；
- `geoai_pending_browser_executions`；
- Browser pending continuation 的 DB save/load/clear 路径。

因此“完全依赖进程内状态”的旧判断已经不准确。

当前真正的问题是：**持久化骨架存在，但尚未形成完整 Durable Runtime。**

这意味着：

- Runtime event append 与 DB event append 仍不是统一原子提交边界；
- 尚未形成公司 RAG 同等级的 reducer / state projection / replay contract；
- 尚未看到 state_version / optimistic concurrency 等价闭环；
- 历史 Evidence 虽可持久化，但尚未真正投影进 Controller 的 Evidence Memory；
- Browser continuation 已有持久化代码，但必须通过后端重启 E2E 才能证明可恢复；
- 当前 Store 在 DB 不可用时可 fallback 内存，这种降级语义必须明确是否允许生产环境静默发生。

### 11.2 目标

吸收公司 RAG Durable Runtime 的原则：

```text
AgentEvent Store
  ↓
Reducer
  ↓
SessionAgentState
  ↓
Runtime Resume / Replay
```

持久事实至少覆盖：

- turn lifecycle；
- tool call started/completed/failed；
- browser tool requested/completed/cancelled；
- Evidence admitted/frozen；
- answer generated；
- review state；
- publication state；
- pending continuation；
- map/runtime acknowledgement；
- cancellation；
- execution fuse facts。

### 11.3 第一性原则

持久化的是：

> **事实与状态转换。**

不是：

- 序列化整份 Prompt；
- 保存私有 Chain-of-Thought；
- 保存一个不可解释的 Python checkpoint blob 作为唯一真源。

### 11.4 重建

必须支持：

```text
Event Log
  ↓
rebuild_state(session_id)
```

并能重建：

- previous_turn_runtime_facts；
- historical Evidence refs；
- publication state；
- pending browser continuation；
- 必要 GIS runtime reference state。

---

## 12. P1：前端 Agent Process 全流程可观测

该部分与：

`docs/superpowers/specs/2026-09-25-geoai-agent-execution-observability-prd.md`

联合实施，不重复设计。

### 12.1 当前问题

Backend 已有 Runtime events，但主 UI 当前仍主要使用非流式 `sendMessage()`。

前端尚未形成：

```text
AgentEvent
  ↓
Projector
  ↓
Turn Agent Process
```

因此用户无法稳定看到：

- Controller；
- Stage；
- Tool input；
- Tool output；
- Browser execution；
- Receipt；
- Evidence freeze；
- Answer Generation；
- Reviewer；
- Publication。

### 12.2 复用原则

优先吸收：

- 公司 RAG `AgentStepStream` / `agentBlockProjector` 的事件投影思想；
- DeepSeek Harness `DisclosureRow` / `ToolRow` / Generic fallback / Turn Process 的展示模式。

不要吸收：

- 与本项目无关的 Harness runtime；
- 第二套 Session Controller；
- 第二套 Tool 状态机。

### 12.3 唯一事实源

UI 必须只展示 Runtime 已确认事实。

禁止：

- 根据模型文字“已完成”推断工具成功；
- 根据前端请求发出推断 Tool Started；
- 将 UI 状态反向作为 Agent 业务状态真源。

---

## 13. P1：移除前端语义补丁

### 13.1 当前问题

当前 `frontend/src/App.tsx` 仍包含大量：

- region regex；
- province aliases；
- `CURRENT_REGION_QUERY_PATTERN`；
- `REGION_REFERENCE_PATTERN`；
- document follow-up cue；
- ordinal pattern；
- `resolveFollowUpContext()`；
- `buildRegionAwareQuery()`；
- 部分“当前区域是什么”由前端直接回答。

这些逻辑本质上是：

> 前端在替 Controller / Context Engine 做语义理解。

### 13.2 目标

迁移后：

```text
原始用户输入
+
Session Context
+
MapContext
+
Evidence Memory
  ↓
Controller
```

前端只负责提供：

- 用户原始文本；
- 显式 UI selection；
- 当前 MapContext；
- 用户明确的交互选择。

前端不得自行：

- 扩写用户问题；
- 用地区正则改写 query；
- 推断用户代词具体指哪个 Evidence；
- 替 Agent 回答 Runtime 事实。

### 13.3 例外

纯 UI 状态读取若完全确定，例如：

> “当前按钮是否打开”

可以由 UI 本地处理。

但涉及 Agent 语义连续性的：

> “这个标准”“刚才那个图层”“这里”“继续”

应进入结构化 Context，而不是 regex patch。

---

## 14. P0：Active Map Runtime 收口

当前 detached worktree 已在实施该方向。

本 PRD 不重做其设计，只将其纳入项目完成态要求。

关联文档：

`2026-09-25-geoai-active-map-runtime-alignment-prd.md`

### 必须完成

- active runtime registry；
- 2D/3D runtime ownership；
- `getBrowserMapContext()` 只读取 active runtime；
- Browser Tool 只执行 active runtime；
- `supported_tools` 动态反映真实能力；
- Backend Controller 动作面与 `supported_tools` 对齐；
- Runtime Guard 与 Controller 使用相同动作状态；
- 3D 至少真实支持已声明的最小能力；
- 流式 / 非流式 MapContext 一致。

### 不要求

本阶段不要求 Cesium 完整复制 OpenLayers 的全部 user-vector 能力。

“3D 功能少”不是错误；

“3D 没实现但模型仍能调用”才是错误。

---

## 15. 不要求从公司 RAG 迁移的能力

为了避免错误追求“一致性”，以下能力不作为本 PRD 的必迁项目。

### 15.1 知识图谱

GeoAI 当前目标不依赖公司 RAG 图谱链路。

因此：

- 不要求复制 `explore_knowledge_graph`；
- 不要求 GraphWorkingSet；
- 不要求 Entity Graph Admission；
- 不要求图谱 RRF。

除非后续 GeoAI 有明确 GIS 知识图谱产品需求，再单独立项。

### 15.2 公司 RAG 业务特定规则

不得复制：

- 公司内部文档类型优先规则；
- 特定 SDK / Cookbook 排序规则；
- 与 GeoAI 无关的 graph/entity heuristic；
- 公司产品特有的 knowledge taxonomy。

GeoAI 应复用：

> 架构机制、接口、状态模型和不变量。

而不是复用：

> 业务规则字符串。

---

## 16. Git / Worktree 收口要求

### 16.1 当前风险

审计时 GeoAI：

- main 非 clean；
- 本地 ahead；
- active-map worktree dirty；
- observability PRD 为未跟踪文件。

因此当前任何“完成”结论都必须先说明在哪个 worktree / commit 上成立。

### 16.2 实施规则

本 PRD 后续开发建议继续使用隔离 worktree。

每一阶段必须记录：

```text
worktree path
branch
base commit
implementation commit
test command
test result
merge commit
main status
```

### 16.3 完成定义

只有：

```text
功能代码完成
+
自动化测试完成
+
review/acceptance 完成
+
合并回 local main
+
main clean
```

才可标记“代码收口完成”。

`worktree 里改完` 不等于完成。

---

## 17. 测试与验收

### 17.1 Level 1：协议单测

至少覆盖：

- ContextFrame projection；
- historical Evidence selection；
- direct_answer；
- clarify exposure gate；
- compose_answer mandatory evidence IDs；
- dynamic executable actions；
- current action JSON Schema；
- parser/runtime guard consistency；
- Reviewer repair scope；
- Reviewer #2 fail-close；
- active map supported tools；
- durable state reducer。

### 17.2 Level 2：Backend 全量回归

当前 7 个失败必须先归零。

已知失败类别包括：

1. Answer Generator 已转向 Answer Units，但旧测试仍提交旧 `answer + citations` shape；
2. E2E GeoJSON fixtures 缺失；
3. Search Agent API stub 未同步 browser continuation 返回字段；
4. README / deployment contract 测试与当前文档状态不一致。

需要逐项判断：

- 测试过时 → 更新测试；
- 产品契约回归 → 修实现；
- fixture 缺失 → 补真实 fixture；
- 文档与代码不一致 → 明确以哪一个为权威后修复。

禁止简单删测试以获得绿色。

### 17.3 Level 3：Frontend 全量回归

必须区分：

- Vitest 单测；
- Playwright E2E；
- lint；
- typecheck；
- build。

当前不能简单执行 `vitest run` 扫整个目录，因为 Playwright spec 与部分脚本式测试不属于同一 runner。

应整理为明确 scripts，例如：

```text
npm run test:unit
npm run test:gis
npm run test:geoai-harness
npm run lint
npm run build
npm run e2e:geoai
```

### 17.4 Level 4：真实模型 E2E

必须使用真实：

- Backend；
- PostgreSQL / pgvector；
- 当前真实 LLM endpoint/model；
- Frontend；
- Browser；
- OpenLayers / Cesium；
- Browser Tool Receipt；
- Agent Runtime。

### 17.5 36 Task 完成态

最终必须产生：

```text
evals/results/<run>/results.json
```

并满足：

```text
36 / 36 completed
```

每个 `completed=true` 必须来自该任务全部 required assertions 真实通过。

禁止：

- 人工写 36 个 true；
- API-only 代替 GIS browser E2E；
- Mock browser tool 代替真实地图执行；
- 模型说“已修改地图”就视为成功。

---

## 18. 真实 E2E 必测场景

除 36-task 总账外，至少显式检查以下代表性链路。

### E2E-A：历史 Evidence 复用

```text
Turn 1：查询某标准核心要求
Turn 2：继续问“其中关于数据精度的要求呢？”
```

要求：

- Controller 能看到历史 evidence catalog；
- 若历史 Evidence 足够，不重新检索；
- 显式选择对应 historical evidence IDs；
- Answer Generator 只接收 selected Frozen Evidence。

### E2E-B：历史 Evidence 不足 → 定向检索

第二轮问题超出第一轮 Evidence 范围时：

- Controller 识别证据不足；
- 发起 targeted retrieval；
- 不 freeze-all 历史 Evidence。

### E2E-C：普通非知识请求

例如：

> “你刚才执行了哪些步骤？”

要求：

- Controller 使用 `direct_answer`；
- 不调用 Answer Generator；
- 不伪造 Tool Result。

### E2E-D：实体歧义

要求：

- 没有合法 IdentityResolution 时 `clarify` 不在动作面；
- 存在权威候选时才允许 clarify；
- LLM 不能增加候选。

### E2E-E：Reviewer REVISE

构造 V1 存在可修复 overstated claim：

- Reviewer #1 = REVISE；
- Repair Scope 生成；
- V2 只修改授权 unit；
- Reviewer #2 通过后才发布。

### E2E-F：2D GIS 多步

```text
导入数据
→ 改样式
→ 图层显隐
→ 定位
→ inspect feature
```

每一步必须：

- 使用稳定 ref；
- Browser Receipt 成功；
- MapContext 更新；
- 下一步 Controller 基于新状态决策。

### E2E-G：3D 能力约束

3D 模式下：

- 模型只能看到真实支持工具；
- 不支持动作无法通过 schema / runtime guard；
- 支持动作真实改变 Cesium 状态。

### E2E-H：后端重启/恢复

若本 PRD Durable Runtime 完成：

- 在可恢复点重启 backend；
- Session state 可重建；
- 历史 Evidence / Runtime facts 不依赖客户端重新发送完整 history。

---

## 19. 状态看板定义

以后每项能力必须使用以下状态之一，禁止只写“完成”。

### DESIGN_DONE

设计已确认，未编码。

### CODE_DONE

代码已实现，但测试未完全通过。

### TESTED

自动化测试通过，但尚未真实 E2E。

### E2E_VERIFIED

真实模型 / 数据库 / Browser 环境通过。

### MERGED

已合并回 local main，main clean。

### RELEASE_READY

满足目标分支要求，可提交 PR / push / release。

例：

```text
ContextFrame
Design: DONE
Code: DONE
Tests: PASS
Real E2E: NOT RUN
Merge: NOT MERGED
=> Overall: TESTED, not complete
```

---

## 20. 实施顺序

### Phase 0：先收口当前工作区

目标：建立可信基线。

任务：

1. 审查当前 main 未提交修改归属；
2. 审查当前 2 个 detached DevSpace worktree 与 `feature/v3-agent-native-g0-g1a` worktree；
3. 已完成内容提交/合并，未完成内容继续隔离；
4. 修复仓库 Python 测试环境，确保项目自带环境可直接执行 pytest；
5. fresh 执行 Backend 定向/全量测试并记录真实结果；
6. 建立明确测试命令矩阵。

出口：

```text
main clean
baseline tests known
working worktrees known
```

### Phase 1：先消灭动作双轨协议

同时完成：

- Control Action / Tool Capability 物理分离；
- 唯一 ExecutableActionState；
- direct_answer；
- clarify gate；
- compose_answer selected evidence；
- Publication Result 类型系统；
- Browser continuation 独立结果契约。

这些属于同一个语义闭环，不建议拆成互不兼容的小 PR。

### Phase 2：Context + Evidence Memory + Dynamic Action Surface

完成：

- ContextFrame 主链接线；
- role projection；
- historical Evidence Memory；
- unified evidence catalog；
- Active Map supported tools 接入；
- request-scoped JSON Schema；
- Provider 支持时原生 JSON Schema 下沉；
- schema / prompt / parser / runtime guard 同源。

### Phase 3：Reviewer Repair

完成：

- Reviewer `REVISE`；
- repair scope；
- Answer V2；
- deterministic authorization validation；
- Reviewer #2；
- fail-close。

### Phase 4：Retrieval Engineering

完成：

- candidate pipeline；
- RRF；
- query planner；
- reranker port；
- retrieval quality；
- Recall@K / MRR。

### Phase 5：Durable Runtime

完成：

- durable event store；
- reducer；
- rebuild；
- continuation persistence；
- historical runtime fact reconstruction。

### Phase 6：Frontend Agent Process + Semantic Cleanup

完成：

- SSE 进入主聊天链路；
- Agent Event Projector；
- unified Agent Process；
- Tool cards；
- Browser Receipt 展示；
- Reviewer / Publication 展示；
- 移除前端语义 regex 补丁。

### Phase 7：Real E2E Closure

完成：

- backend/frontend 启动；
- 真实 LLM；
- 真实 DB；
- 真实 Browser；
- 36-task 执行；
- 结果归档；
- Git 收口。

---

## 21. 复用策略

每个 Phase 开始前必须先回答：

```text
公司 RAG 是否已经存在经过测试的同类机制？
```

如果存在：

1. 先读参考实现；
2. 提取不变量和接口；
3. 对照 GeoAI 当前实现；
4. 最小适配；
5. 不复制无关依赖闭包。

优先复用顺序：

```text
契约 / 数据模型
>
纯函数 / reducer / validator
>
阶段编排模式
>
测试用例思想
>
具体业务实现代码
```

原因：

GeoAI 与公司 RAG 数据源、前端技术栈、GIS Runtime、业务模型不同，最有价值的是：

> **稳定架构不变量，而不是文件逐行相同。**

---

## 22. 代码审查标准

每一阶段完成后必须做局部 + 整体审查。

### 局部

- schema 是否唯一；
- parser 是否同源；
- runtime guard 是否同源；
- 失败是否 fail-close；
- 是否增加硬编码 provider/model 分支；
- 是否产生重复事实源；
- 是否引入 dead compatibility path。

### 整体

- Controller 是否仍是唯一语义规划权威；
- Runtime 是否保持确定性；
- Answer Generator 是否只使用选定 Frozen Evidence；
- Reviewer 是否只做 grounding audit；
- Browser 是否仍是地图状态权威源；
- 前端是否仅展示 Runtime Facts；
- 是否出现第二套会话 / Tool / Evidence / Map State 系统。

### 必须搜索的残留

每阶段结束后搜索：

- retired action names；
- legacy schema fields；
- freeze-all fallback；
- static tool lists；
- duplicate browser tool sets；
- old Reviewer gap fields；
- front-end semantic regex；
- old answer shape；
- duplicate context builders。

---

## 23. 完成态标准

只有同时满足以下条件，才能认为：

> **“GeoAI 已完成对公司 RAG 通用 Agent 能力的必要吸收，并达到当前阶段项目完成态。”**

### 架构

- [ ] 公司 RAG 与 GeoAI 职责关系清晰，无整库复制；
- [ ] Controller / Runtime / Answer / Reviewer 权限边界明确；
- [ ] GIS Runtime 保持 GeoAI 自有权威。

### Context

- [ ] ContextFrame 已实现；
- [ ] 历史 Evidence 是一等上下文；
- [ ] previous-turn Runtime Facts 可投影；
- [ ] role-specific projection 已实现；
- [ ] 客户端 full history 不再是主真源。

### Controller

- [ ] direct_answer 完整实现；
- [ ] clarify 只做 IdentityResolution 确认；
- [ ] knowledge_answer 强制 selected_evidence_ids；
- [ ] capability / control actions 分离。

### Dynamic Action Surface

- [ ] 当前可执行动作只有一个共享真源；
- [ ] Controller schema / parser / runtime guard 一致；
- [ ] Browser supported tools 与 active runtime 一致。

### Structured Output

- [ ] 支持 request-scoped JSON Schema；
- [ ] endpoint 不支持时有通用降级；
- [ ] bounded clean retry；
- [ ] 不读取 reasoning_content 作为正式协议结果。

### Reviewer

- [ ] V1 → Reviewer #1；
- [ ] REVISE → deterministic repair scope；
- [ ] V2 → deterministic validation；
- [ ] Reviewer #2；
- [ ] 二次失败 fail-close；
- [ ] 不回 Controller。

### RAG

- [ ] 多路 Candidate；
- [ ] Fusion / RRF；
- [ ] Query Planner；
- [ ] Reranker 抽象；
- [ ] Retrieval Quality；
- [ ] Recall@K / MRR regression。

### Runtime

- [ ] Event facts durable；
- [ ] Session state 可重建；
- [ ] Browser continuation 可恢复；
- [ ] Evidence memory 可重建；
- [ ] 进程内存不是唯一状态来源。

### GIS

- [ ] 2D Active Runtime；
- [ ] 3D Active Runtime；
- [ ] supported_tools 动态；
- [ ] layer_ref / feature_ref 稳定；
- [ ] Receipt 驱动连续决策；
- [ ] 不存在隐藏 2D runtime 冒充当前 3D 状态。

### Frontend

- [ ] Agent Process 实时展示；
- [ ] Tool Input / Output / Browser / Receipt 可观察；
- [ ] Answer / Reviewer / Publication 边界可观察；
- [ ] 不展示私有 Chain-of-Thought；
- [ ] 前端语义 regex 补丁已移除或降为纯 UI 辅助。

### Tests / E2E

- [ ] Backend 全量测试通过；
- [ ] Frontend unit/GIS/contract/lint/build 通过；
- [ ] Playwright real browser E2E 通过；
- [ ] 真实 LLM + DB + Browser 已执行；
- [ ] 36 / 36 task completed；
- [ ] 结果文件归档；
- [ ] trace / session / model / commit 信息可追踪。

### Git

- [ ] 所有相关 worktree 已审查；
- [ ] 完成内容已提交；
- [ ] 已合并 local main；
- [ ] local main clean；
- [ ] 无未解释 dirty worktree；
- [ ] 再决定是否 push / PR。

---

## 24. P0：消灭“双轨协议”与伪完成态

### 24.1 为什么这是当前最高优先级

本次继续审计确认，GeoAI 当前最危险的问题不是某个单独功能缺失，而是：

> **新一代 Controller / Context / Store 契约已经写入工作区，但旧 ToolRuntime / Publication / Registry 语义仍在主运行链中继续生效。**

这会制造一种非常危险的假象：

```text
看文件：能力已经有了
看类型：协议已经升级
看 Prompt：模型已经知道新动作
看单测：局部组件可以通过

但真正串起来运行：协议互相不兼容
```

因此，从本 PRD 起，任何能力只有同时满足以下条件才能称为“已吸收”：

1. 数据结构存在；
2. 主运行链真实消费；
3. Schema / Parser / Runtime Guard 使用同一事实源；
4. Publication / Persistence / Frontend 能正确承接；
5. 自动化测试覆盖；
6. 真实模型 / 数据库 / 浏览器 E2E 通过。

只满足前 1～2 项，一律只能记为 **PARTIAL / SCAFFOLDED**。

### 24.2 当前已确认的协议撕裂

#### A. Control Action 与 Tool Registry 双重存在

当前新协议已经把：

- `compose_answer`
- `direct_answer`
- `clarify`

定义为 Control Action。

但旧 `build_default_tool_registry()` 仍注册：

- `compose_answer`
- `clarify`
- `limitation`

并且 `executable_tool_names()` 会把所有非 Browser Tool 默认视为可执行能力。

结果是同一个语义可能同时以：

```text
Control Action
Tool Capability
```

两种身份出现在 Controller 动作面。

**验收要求：**

- Control Action 与 Tool Capability 必须在 Registry 层物理分离；
- Controller 不得看到两个语义等价入口；
- Runtime 不得再通过 ToolRuntime 执行 Control Action。

#### B. `clarify` 新旧协议不兼容

新协议：

```json
{"action":"clarify","arguments":{}}
```

旧 Tool Registry：

```text
ClarifyInput.question = required
```

并且当前 Runtime 投影出的 `available_control_actions` 只有：

```text
compose_answer
direct_answer
```

也就是说当前 `clarify` 同时存在两个问题：

1. 正确 Control Action 默认没有被主 Runtime 暴露；
2. 如果误走旧 Tool 路径，`{}` 会被旧输入模型直接拒绝。

**结论：当前 clarify 不能算已吸收。**

#### C. `direct_answer` 生命周期仍未闭环

当前 Runtime 已增加 `direct_answer` bypass，但仍存在契约不一致：

- `AgentRunResult.answer` 类型声明仍为 `GeneratedAnswer | None`；
- Runtime 实际向该字段写入纯 `str`；
- Runtime 使用 `publication_state="grounded"`；
- `PublishedResult` 并不认可 `grounded` 为合法发布态；
- `published_result` 仍按 `GeneratedAnswer.answer` / `map_action` 读取。

因此当前 direct answer 属于：

> **分支代码存在，但 Publication Contract 尚未闭环。**

必须将 direct answer 建模为一等结果类型，而不是把字符串塞进知识答案类型。

#### D. Browser continuation 发布态不一致

`AgentRunResult.published_result` 允许：

```text
publication_state = tool_execution_required
```

但 `PublishedResult.publish()` 的 `_PUBLISHABLE_STATES` 当前不包含该状态。

因此 Browser continuation 在 Publication Authority 上仍存在直接冲突。

**要求：** Browser Tool Pending 不是“已发布最终答案”，必须定义独立的 continuation response contract，不得硬塞进最终 Publication 枚举。

#### E. 请求级 JSON Schema 已生成，但 Provider Adapter 未真正消费

Controller 当前已经构造 request-scoped `response_schema`，但是 `LLMConfigStageModelClient.complete()` 仍只发送：

```json
{"response_format":{"type":"json_object"}}
```

没有把 `request.response_schema` 下沉给支持 JSON Schema 的 Provider。

因此当前状态只能写：

> **应用侧 schema validation 已存在；Provider-native schema enforcement 尚未真正吸收。**

不能把“构造了 schema”写成“模型已被 schema 约束”。

---

## 25. 公司 RAG → GeoAI 全能力吸收矩阵

状态统一使用：

- **DONE**：主链已完成，且有本轮可复验测试；
- **PARTIAL**：有实现，但接线、契约、持久化、测试或 E2E 至少一层未闭环；
- **MISSING**：尚未形成有效实现；
- **GEOAI-OWNED**：GeoAI 自身能力，不应从公司 RAG 复制；
- **NOT-REQUIRED**：公司 RAG 有，但 GeoAI 当前目标无需吸收。

| 能力面 | 公司 RAG 参考能力 | GeoAI 当前 | 审计结论 | 优先级 |
|---|---|---|---|---|
| Agent Runtime 职责边界 | Runtime 只负责执行事实与物理限制 | 基础 Runtime 已形成，但仍混有 Control Action/Tool 旧语义 | PARTIAL | P0 |
| 结构化 ContextFrame | 多事实域、角色投影 | 已新增 Context package | PARTIAL | P0 |
| Controller Context Projection | task / identity / evidence / runtime facts / capabilities 分域 | 目前投影域明显更少 | PARTIAL | P0 |
| 历史会话语义 | Event/Context 重建 | 仍保留 legacy history seed 与前端整段 history | PARTIAL | P0 |
| Evidence Memory | 历史 Evidence 可先选择再定向检索 | ContextEngine 有字段，但 Runtime 未把历史 Evidence 注入 build_frame | MISSING 主链 | P0 |
| Evidence Catalog | 稳定 ID、可选择性、来源边界 | 已有初版 catalog | PARTIAL | P0 |
| 显式证据选择 | `selected_evidence_ids` 必填 | 新协议已实现兼容映射 | PARTIAL，需 E2E | P0 |
| Frozen Evidence | 生成器只看冻结快照 | 已有 | DONE/需全链复验 | P0 |
| Evidence provenance | DIRECT / DERIVED、来源关系可追踪 | 当前元数据较基础 | PARTIAL | P1 |
| Main Controller | 唯一语义规划者 | 新协议正在形成 | PARTIAL | P0 |
| `direct_answer` | 一等 Control Action | bypass 已写，但结果类型/发布态冲突 | PARTIAL/BROKEN | P0 |
| `clarify` | 仅合法 IdentityResolution 时暴露 | 未形成权威候选门控；旧 Tool 契约仍存 | MISSING 主链 | P0 |
| `compose_answer` | Control Action，不是 Tool | 新旧身份并存 | PARTIAL/DUAL | P0 |
| 动态动作面 | Schema/Prompt/Parser/Guard 单一事实源 | Browser Tool 已部分动态；Control Action 不统一 | PARTIAL | P0 |
| 物理能力门控 | 不向模型暴露不可执行动作 | 2D/3D supported_tools 已开始实现 | PARTIAL | P0 |
| 请求级 Structured Schema | Provider 可用时原生 schema 约束 | schema 已构造，adapter 未下沉 | PARTIAL | P0 |
| Clean protocol retry | 非 reasoning、低温、同一 validator | 已有 shared structured retry | PARTIAL/需全链测试 | P0 |
| Main model request identity | Controller + Answer 同请求共享 Main | 已有 main model resolve 机制 | PARTIAL/需 E2E | P1 |
| Stage Policy | Controller/Answer/Reviewer 分阶段策略 | 已有 | PARTIAL/需 provider 复验 | P1 |
| Answer Generator | 只消费冻结证据 | 已有 | PARTIAL/需最终协议复验 | P0 |
| Reviewer | 只审查 Frozen Evidence 支撑性 | 已有基础实现 | PARTIAL | P0 |
| Reviewer Repair | V1→Scope→V2→Reviewer#2 | 工作区已出现实现 | PARTIAL，且 repair scope 仍过宽 | P0 |
| Repair Scope 精确性 | finding-linked editable scope | 当前 editable unit 可使用全部 snapshot citations | PARTIAL | P0 |
| Publication Authority | 单一发布权威 + fail-close | 已有类，但状态契约与 Runtime 冲突 | PARTIAL/BROKEN | P0 |
| Logical Turn 生命周期 | pause/resume/publish 一致 | Browser continuation 有雏形；Clarify 未闭环 | PARTIAL | P0 |
| Event Log | append-only / 可重建 | Postgres Store 已新增 | PARTIAL | P1 |
| Replay / Projection | 状态可从 Event 重建 | 尚未形成公司 RAG 同等级 reducer/projection 闭环 | MISSING/PARTIAL | P1 |
| 乐观并发控制 | state_version / conflict guard | 未看到等价闭环 | MISSING | P1 |
| Browser Pending 持久化 | 跨请求 continuation 可恢复 | 已新增 DB 表与 store | PARTIAL | P0 |
| Tool 幂等 | tool_call_id 稳定、重复调用不重复副作用 | 2D executor 已实现 runId+toolCallId 去重 | GEOAI-OWNED / DONE(2D) | P0 |
| 3D Tool 幂等 | 与 2D 同等幂等契约 | Cesium runtime 当前未体现同等级 call cache | PARTIAL | P0 |
| Retrieval Port | Agent 与存储解耦 | 已有 | DONE/需回归 | P1 |
| Exact/Keyword/Vector | 多通道退化 | 已有 | PARTIAL | P1 |
| Fusion | RRF/等价稳定融合 | 当前主要 merge/dedupe + rerank | PARTIAL | P1 |
| Query Planning | 针对性查询与约束规划 | Controller 可决定 query，但缺少系统化候选规划/评测 | PARTIAL | P1 |
| Reranker | 明确候选重排 | 已有基础 RagReranker | PARTIAL | P1 |
| Recall@K / MRR | 检索离线回归 | 未看到同等级正式指标闭环 | MISSING | P1 |
| 文档摄取/Chunk | 业务文档处理 | GeoAI 已有自己的成熟链路 | GEOAI-OWNED | 保留 |
| 知识图谱 | 图谱证据与探索 | 公司 RAG 有更多能力 | NOT-REQUIRED | - |
| Browser MapContext | 浏览器真实地图状态 | GeoAI 自有 | GEOAI-OWNED | 核心 |
| Active Map Runtime | 当前 2D/3D 权威执行环境 | 已开始统一 | PARTIAL | P0 |
| `layer_ref` | 稳定图层身份 | 2D 已有 | GEOAI-OWNED / PARTIAL(跨2D/3D) | P0 |
| `feature_ref` | 稳定要素身份 | 2D 已有 | GEOAI-OWNED | P0 |
| Browser Receipt | 副作用真实回执 | 已有 | GEOAI-OWNED / PARTIAL | P0 |
| PostGIS | 确定性空间分析 | 已有 | GEOAI-OWNED | P1 |
| Agent Process UI | reasoning/stage/tool/reviewer/publication 统一投影 | 当前主前端未发现等价 Block Projector | MISSING | P1 |
| SSE Process 消费 | 前端按事件类型构建执行过程 | chatService 主要只特殊处理 `result` | MISSING/PARTIAL | P1 |
| 前端语义补丁 | 不应替代 Agent Context | 仍有区域/文档 follow-up regex | PARTIAL/需下沉 | P1 |
| Evaluation Harness | 系统级任务清单 | 已有 36-task manifest | PARTIAL | P0 |
| 真实结果归档 | results + trace + commit | 当前 latest results 不存在 | MISSING | P0 |
| 可复现测试环境 | 一条命令可执行后端测试 | 当前根 venv 无 pytest | MISSING | P0 |
| Git 收口 | clean main + 可解释 worktree | main dirty，ahead 4，多 worktree | MISSING | P0 |

---

## 26. 横切工程能力：原 PRD 覆盖不足的部分

### 26.1 发布权威与结果类型系统

必须建立明确的结果代数，而不是靠字符串状态散落判断：

```text
DirectAnswerResult
KnowledgeAnswerResult
ClarificationRequired
BrowserToolExecutionRequired
SafeLimitation
NoSafeAnswer
```

每种结果必须明确：

- 是否用户可见；
- 是否算 Logical Turn 完成；
- 是否需要继续同一 Run；
- 是否可带 MapAction；
- 是否可带 Frozen Evidence；
- 是否进入 Reviewer；
- 是否能被前端当最终答案渲染。

禁止继续用一个 `publication_state: str` 同时承担所有语义。

### 26.2 并发、一致性与幂等

GeoAI 是存在真实副作用的 Agent，要求比普通 RAG 更严格：

1. 同一 `tool_call_id` 重放不得重复导入/修改图层；
2. 同一 Browser Receipt 不得被消费两次；
3. continuation token 必须单次消费或显式幂等；
4. 同一 session 的并发请求必须定义序列化或版本冲突策略；
5. DB Event、PendingExecution、Evidence 状态不得出现半提交；
6. 服务重启后不得把旧 pending 当新任务再次执行。

公司 RAG 的 Event Store / state version 思想应吸收，但实现必须适配 GeoAI Browser 副作用。

### 26.3 模型与 Provider 适配

必须区分：

```text
应用层协议
Provider 原生结构化输出能力
Provider reasoning 能力
模型选择
Embedding Provider
```

禁止：

- 根据某个模型名写特殊业务分支；
- `response_schema` 在 Controller 构造后被 Adapter 丢弃；
- Controller/Answer 在同一请求中静默切换 Main 模型；
- 把 `reasoning_content` 当用户答案；
- structured retry 使用与首轮不同的验证规则。

### 26.4 安全边界

本项目至少需要覆盖：

- Prompt Injection 不得修改 Runtime Facts；
- 文档文本不得直接变成 Tool 参数而绕过 Controller/Schema；
- Browser Receipt 只能作为事实输入，不能携带可执行脚本；
- `file_ref / layer_ref / feature_ref` 必须经过作用域校验；
- principal/session 隔离必须在 Store、Evidence、PendingExecution 三层一致；
- 任何模型输出都不得直接获得数据库 SQL 或浏览器任意 JS 执行权。

当前这些能力有部分天然边界，但尚未形成系统化验收项，新增为 P1。

### 26.5 性能与上下文预算

Context Budget 不能只看 token 数，还要定义：

- Controller 最大上下文预算；
- Evidence Catalog 截断策略；
- MapContext 大图层树压缩策略；
- Feature 属性分页；
- Browser continuation 最大轮数；
- 单 Run 总 wall-clock budget；
- 检索、模型、Browser Tool 分阶段耗时指标。

当前前端 build 还存在超大 bundle warning；这不是 Agent P0，但属于交付性能债务，应记录为 P2。

### 26.6 运维与可诊断性

必须能从一个 `trace_id` 回答：

```text
用户问了什么
Controller 看到了什么动作面
选了什么动作
模型/Provider/attempt 是什么
工具输入是什么
工具真实结果是什么
Evidence 如何产生/选择/冻结
Reviewer 为什么通过/拒绝
最终谁拥有发布权
Browser continuation 是否发生
是否经历重试/降级/超时
```

如果只能通过 grep 多个日志文件拼答案，不能视为可观测闭环。

### 26.7 数据迁移与兼容层退出

当前项目存在明显迁移期代码：

- `legacy_history`；
- legacy Controller wire normalization；
- 旧 Tool control actions；
- 新旧 Context module 并存迁移痕迹。

每个兼容层都必须有：

1. 引入原因；
2. 允许读取的旧格式；
3. 禁止新写入旧格式；
4. 删除条件；
5. 删除测试。

禁止无限期保留“兼容”导致协议永久双轨。

---

## 27. 六层完成度判定模型

今后每个能力必须按下面六层记录，禁止只写一个“完成/未完成”。

| 层级 | 判定问题 | 示例 |
|---|---|---|
| L1 Design | 契约是否定义清楚 | `direct_answer` 语义已定义 |
| L2 Code | 代码是否存在 | ControllerProtocol 已实现 |
| L3 Integrated | 主链是否真实使用 | Runtime 是否按 Control Action 分支 |
| L4 Deterministic Test | 自动化测试是否证明契约 | protocol/runtime/publication 测试 |
| L5 Real E2E | 真实模型/DB/浏览器是否跑通 | 36-task 中对应任务完成 |
| L6 Delivery | Git/环境/文档是否可复现 | clean main + 一键测试 + 结果归档 |

状态计算规则：

```text
最终完成度 = min(L1, L2, L3, L4, L5, L6)
```

不是平均分。

原因很简单：

> 一个 Agent 能力只要其中任一关键层为 0，用户就可能完全用不到它。

例如当前 `direct_answer`：

```text
L1 Design       = 有
L2 Code         = 有
L3 Integrated   = 部分
L4 Test         = 未 fresh 证明
L5 Real E2E     = 无
L6 Delivery     = 无
```

因此只能标记 **PARTIAL**，不能标记“已完成”。

---

## 28. 当前必须先修的 P0 顺序

不得按“哪个文件好改”推进，应按因果依赖顺序：

```text
P0-1 统一动作类型系统
  ↓
移除 Control Action 的 Tool 双重身份
  ↓
P0-2 ExecutableActionState 成为唯一动作事实源
  ↓
Schema / Prompt / Parser / Runtime Guard 共用
  ↓
P0-3 direct_answer / clarify / compose_answer 生命周期闭环
  ↓
P0-4 Publication Result 类型系统闭环
  ↓
P0-5 Evidence Memory 真正接入 Controller
  ↓
P0-6 Reviewer Repair Contract 收紧并验证
  ↓
P0-7 Browser continuation + durable pending 一致性
  ↓
P0-8 Backend 可复现测试环境
  ↓
P0-9 36-task 真实 E2E
  ↓
P0-10 Git/worktree 收口
```

在 P0-1 ～ P0-4 完成前，不建议继续增加新 GIS Tool。否则只会让错误动作面越来越大。

---

## 29. 最终判断

本 PRD 不将当前 GeoAI 视为“失败项目”或“需要推倒重来”。

当前更准确的状态是：

```text
GIS 执行闭环          → 主体已形成
基础 Agent Runtime    → 已形成
Evidence / Answer     → 已形成
基础 Reviewer         → 已形成
文档摄取              → 已形成

Context Governance    → 新骨架已出现，但历史 Evidence 尚未接入主链
Controller Contract   → 新协议已出现，但与旧 Tool 语义双轨
Dynamic Action        → Browser 部分动态，Control Action 尚未统一
Structured Output     → 应用层校验已做，Provider-native Schema 未闭环
Reviewer Repair       → 工作区已有实现，但契约精度和 fresh 验证不足
Retrieval Engineering → 基础版
Durable Runtime       → Store/迁移/Browser Pending 已出现，但非完整 Event-sourced Runtime
Agent Process UI      → 未实现
Real 36/36 E2E        → 未验证
Git/Tests Closure     → 当前未完成
```

最关键的审查结论不是“GeoAI 落后公司 RAG 很多”，而是：

> **GeoAI 已经吸收了相当一部分通用 Agent 设计，但目前很多能力停在 L1/L2，尚未完成 L3～L6；同时 GIS 执行层反而已经形成了公司 RAG 不具备的独立价值。**

所以真正的收口目标不是代码数量对齐，而是：

```text
公司 RAG 的成熟通用能力
        ↓ 只吸收契约与机制
GeoAI Agent Core
        +
GeoAI Browser / GIS Runtime
        ↓
同一个可恢复、可观察、可验证的执行闭环
```

因此下一阶段的正确目标不是继续堆 GIS Tool，也不是再造新的 Agent 框架，而是：

> **把公司 RAG 已经验证的通用 Agent 能力增量吸收到 GeoAI 的正确架构位置，同时保护 GeoAI 已经形成的 Browser GIS Runtime 与真实地图状态闭环。**

完成后，GeoAI 才真正从：

```text
RAG + Agent Tools + WebGIS
```

进入：

```text
结构化上下文
+ 证据编排
+ 动态动作面
+ 可靠结构化协议
+ 可修复 Grounding
+ Durable Runtime
+ 真实 GIS 执行闭环
+ 全流程可观测
```

也就是本项目真正目标中的：

> **通用 Agent 大脑 + GIS 世界执行系统。**
