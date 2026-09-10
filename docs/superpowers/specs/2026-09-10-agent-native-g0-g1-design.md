# Agent-Native V3 G0-G1 设计

## 1. 目标

第一阶段交付 G0 与 G1：冻结 GeoAI 当前聊天、引用和 2D 地图控制行为，并在不切换前端主聊天链路的前提下，把 `agentic rag` 的完整 Agent Runtime 职责链从稳定版本选择性迁入 GeoAI，建立独立、可测试、可随 GeoAI 部署的内置运行时与 Adapter。

阶段出口是：不启动外部 `agentic rag` 服务时，经过现有 GeoAI 鉴权和访客配额控制后，调用方可以通过 GeoAI 的 `/api/agent/*` 接口完成纯知识问答、SSE 事件接收、引用读取和澄清恢复。GIS Tool、浏览器 Tool Resume、前端主链路切换及旧 RAG 下线均不属于本阶段。

## 2. 架构决策

采用“冻结上游 commit、选择性迁入、GeoAI 内部适配”的 Fork at Integration Boundary。两个上游仓库保持只读；GeoAI 拥有迁入副本并独立演进，不直接 import 本机外部路径，也不要求外部上游服务参与部署。

```text
GeoAI Client
  -> /api/agent/*
  -> Auth / Visitor Quota
  -> GeoAI Agent Adapter
  -> Embedded Agent Runtime
       -> Controller / Agent Loop
       -> Retrieval / Graph / Evidence / Reviewer
```

决策理由：

- GeoAI 保留产品级鉴权、访客配额、错误语义和 API Contract。
- 迁入的 Agent Runtime 继续作为唯一 Agent Controller 与知识事实真源，旧 GeoAI 链路不形成第二个 Agent Loop。
- GeoAI Adapter 隔离产品 API、鉴权、配额、配置和运行时内部接口，为 G2 前端迁移提供稳定契约。
- G4-G6 再引入 AG-UI、GIS Environment Tools 和浏览器回执恢复，避免首阶段同时承担跨语言异步状态机风险。
- 来源清单记录仓库、commit、迁入文件、依赖闭包和内部授权，后续上游更新只允许差异审查后的选择性同步。

## 3. 范围

### 3.1 G0：现状冻结

- 记录当前聊天链路：`App.tsx -> chatService -> /api/search/query -> SearchService`。
- 固定当前回答、引用、追问、访客配额及结构化 `map_action` 行为的回归测试。
- 记录当前 OpenLayers 根据行政区 `adcode` 定位和高亮的行为边界。
- 增加 `legacy | agent` 链路开关；本阶段默认保持 `legacy`，不得在 Agentic RAG 不可用时自动混用两套知识结果。
- 保存当前未提交成果的可恢复基线，但不得把无关用户改动重写或丢弃。
- 冻结 `agentic rag` commit `2eab8d5c479ba32c27b7c929a35c273edf0a2f64` 与 `gis-agent-core` commit `ee3d30667fbd0b970633d32265f97c6d147c35c1`。
- 记录两个上游仓库均由 `edjsh175` 控制并授权选择性迁入 GeoAI。
- 建立 `docs/upstream-sources/agent-native-v3.toml` source manifest；Python 3.12 使用标准库 `tomllib` 读取，无需增加解析依赖。每个迁入文件必须可追溯到来源 commit，并记录其依赖闭包。

### 3.2 G1：Agent Runtime 迁入与 GeoAI Adapter

- 在 `Backend/agent_runtime/` 建立由 GeoAI 拥有的 Agent Runtime 子系统，迁入 Stage 1、ConversationContext、Identity/SemanticTask、Controller、Agent Loop、Tool Registry、Retrieval、Graph、Evidence、Reviewer、Publication 及其实际依赖闭包。
- 迁入以职责完整为标准，不机械复制整个 `rag_knowledge`，也不只抽取 Retriever 或 `orchestration/` 目录。
- 新增独立 Agent API 路由与 Pydantic 模型，不继续扩展 `search_routes.py` 或 `SearchService`。
- 新增 GeoAI Agent Adapter，连接现有配置、存储、鉴权、访客配额和 Agent Runtime。
- 支持创建/绑定 GeoAI Agent session，并保留迁入运行时需要的会话字段。
- 支持纯知识查询 SSE、引用、澄清提交和健康检查。
- 生成并透传 `trace_id`；保留运行时事件中的 run/session 标识。
- 复用现有认证和 `DemoQuotaService`，保持登录用户与访客行为一致。

G1 按以下内部检查点实施，任何检查点失败都不继续扩大复制范围：

1. G1a：source manifest、授权、依赖扫描和上游一致性测试基线。
2. G1b：迁入 orchestration、conversation/identity/task 与 LLM 抽象，建立最小 Controller 启动测试。
3. G1c：迁入 retrieval、graph、evidence、reviewer、publication 及实际依赖闭包，接入 GeoAI 配置与存储。
4. G1d：实现 GeoAI Agent Adapter、session、SSE、引用、澄清、健康检查、鉴权与访客配额。

### 3.3 不在本阶段实施

- 前端聊天主入口切换、Agent Event Reducer 和 Agent UI。
- `MapContext`、`FeatureReferenceStore`、React GIS Adapter。
- `locate_features`、`highlight_features` 注册与执行。
- Browser Tool Call、receipt、resume、lease 和幂等恢复。
- 删除前端自然语言正则、`extract_map_action` 或旧 RAG 生成链路。
- 修改 `agentic rag` 或 `gis-agent-core` 上游仓库。
- 迁入 `gis-agent-core` 代码；它从 G4 开始按最小 GIS 闭包选择性迁入。

## 4. Backend 组件边界

### 4.1 配置

Agent Runtime 配置通过 GeoAI config adapter 接入现有环境、模型、知识存储和运行参数。迁入模块不得自行读取上游仓库路径或依赖上游目录布局；敏感值仅从环境读取，不写入日志或 API 响应。

链路模式定义：

- `legacy`：现有聊天入口维持原行为；新 `/api/agent/*` 接口仍可供验证。
- `agent`：供 G2 切换后的聊天入口使用，本阶段只建立配置与契约。

模式不表示失败回退策略。正式 Agent 请求失败时返回明确的 Agent Runtime Unavailable，不自动请求旧 RAG。

### 4.2 Embedded Agent Runtime

迁入后的运行时保持以下职责闭包：

- Stage 1、ConversationContext、Identity 与 SemanticTask；
- Main Controller、Agent Loop、Tool Registry；
- Knowledge Retrieval、Knowledge Graph 与 EvidencePool；
- Evidence Snapshot、Answer Generator、Grounding Reviewer 与 Publication；
- QA Trace、澄清快照与恢复。

`Backend/agent_runtime/` 不负责 GeoAI 路由鉴权、访客配额或 React/GIS 状态。GeoAI 专用逻辑必须经 Adapter 或后续 Environment Tool Provider 注入，不能散落到迁入核心中。

### 4.3 GeoAI Agent Adapter 与 API

首阶段提供以下 GeoAI 接口：

- `POST /api/agent/sessions`：创建或绑定 Gateway session。
- `POST /api/agent/query/stream`：提交纯知识查询并把内部执行事件适配为稳定 SSE。
- `POST /api/agent/clarifications`：提交澄清答案并恢复内置运行时流程。
- `GET /api/agent/health`：检查 Adapter、运行时与知识依赖可用性。

`tool-results` 与 `cancel` 留到需要真实 pending run 的 G6；不得用空实现制造已支持的假象。

## 5. SSE 事件契约

GeoAI 对外事件采用稳定 envelope：

```json
{
  "type": "thinking",
  "data": {},
  "trace_id": "trace_xxx",
  "session_id": "session_xxx",
  "run_id": "run_xxx"
}
```

第一阶段识别并适配：

- `status`
- `heartbeat`
- `thinking`
- `tool_start`
- `tool_end`
- `clarify`
- Evidence/引用相关事件
- Answer/finalization 相关事件
- `error`
- `done`

未知内部事件以兼容事件封装并记录安全日志，不应导致整个流崩溃。事件内容不得被解释为 GIS 指令；本阶段也不产生浏览器 pending tool call。

## 6. 数据流

### 6.1 查询

```text
Request
  -> require_authenticated_user
  -> DemoQuotaService 校验
  -> 创建 trace_id / 解析 session
  -> AgentRuntimeAdapter.stream_query
  -> 执行内置 Agent Runtime
  -> 适配 SSE envelope
  -> Client
```

只有请求被 Gateway 接受并实际进入 Agent 查询后才应用既有访客配额语义。配额行为与现有接口保持一致，并由契约测试固定。

### 6.2 澄清

```text
Clarification answer
  -> 校验当前用户与 session 绑定
  -> 调用内置 Agent Runtime clarification contract
  -> 返回恢复后的 SSE 或稳定响应
```

客户端不得为其他用户或 session 提交澄清。运行时快照过期或不匹配时返回明确冲突/失效错误。

## 7. 错误处理

- 未认证：沿用现有 `401/403` 语义。
- 访客额度不足：沿用现有配额响应，不调用 Agent Runtime。
- 运行时或知识依赖初始化失败：`503 Agent Runtime Unavailable`。
- 运行超时：`504` 或流内终止错误事件，取决于响应头是否已发送。
- 运行时参数或内部错误：映射为稳定的 4xx/5xx，不泄露凭据、路径或堆栈。
- 客户端取消连接：取消当前运行，不继续后台执行。
- 无效 SSE：发送可追踪错误并结束，不切换旧 RAG。

## 8. 测试设计

严格采用测试先行：每项生产行为先增加会因缺失功能而失败的测试，再写最小实现。

### 8.1 G0 回归

- 现有 `/api/search/query` 契约及引用行为。
- 前端仍使用旧聊天入口。
- 追问和结构化 `map_action` 的当前兼容行为。
- Auth、访客配额、OpenLayers 行政区定位/高亮边界。

### 8.2 G1 单元与契约测试

- source manifest 的 commit、文件哈希/路径、授权与迁入边界检查。
- import closure 检查，确保运行时不引用外部仓库路径。
- `AgentRuntimeAdapter` 会话、流式执行、超时与异常映射。
- SSE 事件适配，包括心跳、未知事件和异常终止。
- Agent 路由鉴权与访客配额。
- session 用户隔离与澄清绑定。
- Agent Runtime 不可用时不触发旧 RAG。
- 与冻结上游核心场景的迁入一致性测试。
- OpenAPI 包含新接口且旧接口保持兼容。

### 8.3 验证命令

- 后端目标测试：`pytest Backend/tests/<agent-tests> -v`
- 后端回归：`pytest`
- 前端回归：在 `frontend` 执行 `npm test`、`npm run lint`、`npm run build`

如果基线测试在任何 V3 改动前已经失败，应先报告并区分既有失败，不把它误判为本阶段回归。

## 9. 交付与验收

G0 + G1 完成必须同时满足：

1. 当前用户改动有可恢复基线，V3 改动在隔离分支/worktree 中完成。
2. 原聊天路径和前端行为未被切换或删除。
3. `/api/agent/*` 经过现有鉴权与访客配额。
4. 不启动外部上游服务时，GeoAI 可从内置 Agent Runtime 流式获得纯知识回答与引用。
5. 澄清请求可以在正确 session 中恢复，跨用户/session 请求被拒绝。
6. 内置运行时不可用时返回稳定错误，且不自动混用旧 RAG。
7. 新代码具备单元、契约和回归测试，Backend 与 Frontend 既有关键验证通过。
8. 本阶段没有注册 GIS Tool，没有无边界整仓复制，也没有引入第二个 Agent Controller。
9. 两个上游仓库保持原 commit 和干净工作树，GeoAI 不依赖外部仓库路径或进程。
10. source manifest 完整记录迁入来源、文件、依赖闭包和内部授权。

## 10. 后续阶段接口预留

G2 使用本阶段稳定的 Gateway SSE 契约实现 `agentService` 和事件 reducer。G4-G6 在独立设计中决定 AG-UI 映射、`MapContext` v2/v3 兼容、Feature Reference 产生方式、pending tool call、receipt correlation、lease、幂等与 Agent Resume。首阶段仅保留 run/session/trace 字段，不提前实现这些状态机。
