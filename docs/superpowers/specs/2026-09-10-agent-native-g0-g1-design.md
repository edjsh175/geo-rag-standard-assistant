# Agent-Native V3 G0-G1 设计

## 1. 目标

第一阶段交付 G0 与 G1：冻结 GeoAI 当前聊天、引用和 2D 地图控制行为，并在不切换前端主聊天链路的前提下，为 Agentic RAG 建立独立、可测试的 GeoAI Backend Gateway。

阶段出口是：经过现有 GeoAI 鉴权和访客配额控制后，调用方可以通过 GeoAI 的 `/api/agent/*` 接口完成 Agentic RAG 纯知识问答、SSE 事件接收、引用读取和澄清恢复。GIS Tool、浏览器 Tool Resume、前端主链路切换及旧 RAG 下线均不属于本阶段。

## 2. 架构决策

采用 GeoAI 稳定 Gateway，而不是让前端直接依赖 Agentic RAG 内部接口，也不在本阶段把两边协议整体改造成 AG-UI。

```text
GeoAI Client
  -> /api/agent/*
  -> Auth / Visitor Quota
  -> Agent Gateway
  -> AgenticRagClient
  -> Agentic RAG /query/*
```

决策理由：

- GeoAI 保留产品级鉴权、访客配额、错误语义和 API Contract。
- Agentic RAG 继续作为唯一 Agent Controller 与知识事实真源，GeoAI 不新增 Agent Loop。
- Gateway 隔离上游路径、字段和 SSE 事件的变化，为 G2 前端迁移提供稳定接口。
- G4-G6 再引入 AG-UI、GIS Environment Tools 和浏览器回执恢复，避免首阶段同时承担跨语言异步状态机风险。

## 3. 范围

### 3.1 G0：现状冻结

- 记录当前聊天链路：`App.tsx -> chatService -> /api/search/query -> SearchService`。
- 固定当前回答、引用、追问、访客配额及结构化 `map_action` 行为的回归测试。
- 记录当前 OpenLayers 根据行政区 `adcode` 定位和高亮的行为边界。
- 增加 `legacy | agent` 链路开关；本阶段默认保持 `legacy`，不得在 Agentic RAG 不可用时自动混用两套知识结果。
- 保存当前未提交成果的可恢复基线，但不得把无关用户改动重写或丢弃。

### 3.2 G1：Agentic RAG Gateway

- 新增 `AgenticRagClient`，封装上游连接、超时、请求头、普通 JSON 请求和 SSE 流。
- 新增独立 Agent API 路由与 Pydantic 模型，不继续扩展 `search_routes.py` 或 `SearchService`。
- 支持创建/绑定 GeoAI Agent session，并映射 Agentic RAG 所需的设备指纹或会话字段。
- 支持纯知识查询 SSE、引用、澄清提交和健康检查。
- 生成并透传 `trace_id`；保留上游事件中的 run/session 标识。
- 复用现有认证和 `DemoQuotaService`，保持登录用户与访客行为一致。

### 3.3 不在本阶段实施

- 前端聊天主入口切换、Agent Event Reducer 和 Agent UI。
- `MapContext`、`FeatureReferenceStore`、React GIS Adapter。
- `locate_features`、`highlight_features` 注册与执行。
- Browser Tool Call、receipt、resume、lease 和幂等恢复。
- 删除前端自然语言正则、`extract_map_action` 或旧 RAG 生成链路。
- 修改 `agentic rag` 或 `gis-agent-core` 仓库。

## 4. Backend 组件边界

### 4.1 配置

Agent Gateway 配置包含：上游 base URL、连接/读取超时、链路模式和健康检查设置。敏感值仅从环境读取，不写入日志或 API 响应。

链路模式定义：

- `legacy`：现有聊天入口维持原行为；新 `/api/agent/*` 接口仍可供验证。
- `agent`：供 G2 切换后的聊天入口使用，本阶段只建立配置与契约。

模式不表示失败回退策略。正式 Agent 请求失败时返回明确的 Service Unavailable，不自动请求旧 RAG。

### 4.2 AgenticRagClient

客户端只负责传输与上游协议适配：

- 构造 `/query/stream`、澄清和健康检查请求；
- 转发允许的会话/设备标识，不转发任意客户端头；
- 使用流式 HTTP API，避免缓冲完整 SSE 响应；
- 将连接失败、超时、非成功状态和无效 SSE 映射为稳定异常；
- 在客户端断开时关闭上游流。

客户端不负责业务鉴权、配额扣减、回答生成或 Agent 决策。

### 4.3 Agent API

首阶段提供以下 GeoAI 接口：

- `POST /api/agent/sessions`：创建或绑定 Gateway session。
- `POST /api/agent/query/stream`：提交纯知识查询并代理规范化 SSE。
- `POST /api/agent/clarifications`：提交澄清答案并恢复上游流程。
- `GET /api/agent/health`：检查 Gateway 配置与上游可用性。

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

第一阶段识别并转发：

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

未知上游事件以兼容事件转发并记录安全日志，不应导致整个流崩溃。事件内容不得被解释为 GIS 指令；本阶段也不产生浏览器 pending tool call。

## 6. 数据流

### 6.1 查询

```text
Request
  -> require_authenticated_user
  -> DemoQuotaService 校验
  -> 创建 trace_id / 解析 session
  -> AgenticRagClient.stream_query
  -> 规范化 SSE envelope
  -> Client
```

只有请求被 Gateway 接受并实际进入 Agent 查询后才应用既有访客配额语义。配额行为与现有接口保持一致，并由契约测试固定。

### 6.2 澄清

```text
Clarification answer
  -> 校验当前用户与 session 绑定
  -> 转发 Agentic RAG clarification contract
  -> 返回恢复后的 SSE 或稳定响应
```

客户端不得为其他用户或 session 提交澄清。上游快照过期或不匹配时返回明确冲突/失效错误。

## 7. 错误处理

- 未认证：沿用现有 `401/403` 语义。
- 访客额度不足：沿用现有配额响应，不调用上游。
- 上游连接失败或健康检查失败：`503 Agent Service Unavailable`。
- 上游超时：`504` 或流内终止错误事件，取决于响应头是否已发送。
- 上游拒绝或参数错误：映射为稳定的 4xx/5xx，不泄露内部 URL、凭据或堆栈。
- 客户端取消连接：关闭上游流，不继续后台消费。
- 无效 SSE：发送可追踪错误并结束，不切换旧 RAG。

## 8. 测试设计

严格采用测试先行：每项生产行为先增加会因缺失功能而失败的测试，再写最小实现。

### 8.1 G0 回归

- 现有 `/api/search/query` 契约及引用行为。
- 前端仍使用旧聊天入口。
- 追问和结构化 `map_action` 的当前兼容行为。
- Auth、访客配额、OpenLayers 行政区定位/高亮边界。

### 8.2 G1 单元与契约测试

- `AgenticRagClient` 请求路径、头白名单、超时与异常映射。
- SSE 分块解析，包括跨 chunk 行、心跳、未知事件和异常终止。
- Agent 路由鉴权与访客配额。
- session 用户隔离与澄清绑定。
- `503` 不触发旧 RAG。
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
4. GeoAI 可流式获得 Agentic RAG 的纯知识回答与引用。
5. 澄清请求可以在正确 session 中恢复，跨用户/session 请求被拒绝。
6. 上游不可用时返回稳定错误，且不自动混用旧 RAG。
7. 新代码具备单元、契约和回归测试，Backend 与 Frontend 既有关键验证通过。
8. 本阶段没有注册 GIS Tool，没有复制上游仓库核心代码，也没有引入第二个 Agent Controller。

## 10. 后续阶段接口预留

G2 使用本阶段稳定的 Gateway SSE 契约实现 `agentService` 和事件 reducer。G4-G6 在独立设计中决定 AG-UI 映射、`MapContext` v2/v3 兼容、Feature Reference 产生方式、pending tool call、receipt correlation、lease、幂等与 Agent Resume。首阶段仅保留 run/session/trace 字段，不提前实现这些状态机。
