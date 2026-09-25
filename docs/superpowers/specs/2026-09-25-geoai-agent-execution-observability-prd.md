# GeoAI Agent 全流程可观测展示与 DeepSeek Harness 前端模式吸收 PRD

## 1. 文档定位

- 类型：增量 PRD
- 日期：2026-09-25
- 目标仓库：当前 GeoAI / RAG 项目
- 关联能力：Agent Runtime、SSE、Browser GIS Continuation、Evidence、Answer Generator、Reviewer、Chat UI
- 参考实现：`deepseek-harness` 的 `DisclosureRow`、`ReasoningRow`、`ToolRow`、Generic Tool fallback、Turn Process 展示模式

本 PRD 不要求引入 DeepSeek Harness 的 Cordis、Slot、Conversation、Session Controller 等基础设施，只吸收其已经验证过的展示原则，并适配到本项目现有 Agent Runtime 与前端技术栈。

## 2. 背景

当前项目后端已经能产生一组结构化 Agent 运行事件，包括：

- `user_message`
- `controller_decision`
- `tool_started`
- `tool_completed`
- `evidence_frozen`
- `browser_tool_requested`
- `browser_tool_completed`
- `browser_tool_cancelled`
- `answer_generated`
- `publication_completed`
- `assistant_message`

`SearchApplicationService.stream()` 已经把同一条真实 Agent Runtime 执行路径产生的 `AgentEvent` 通过 SSE 发送给前端，因此不需要再造第二条“专门用于展示”的 Agent 执行链路。

当前主要问题在前端：SSE 中除 `result` 外的事件基本被当作普通字符串转交，缺少稳定的事件投影层和 Agent Process 展示模型。因此用户当前主要只能看到最终回答、引用和 Loading 状态，无法直观看到：

```text
用户请求
→ Controller 做了什么决策
→ 调用了什么工具
→ 工具收到什么关键输入
→ 工具执行结果如何
→ Browser GIS 是否进入浏览器执行
→ Receipt 是否返回成功
→ 哪些 Evidence 被冻结
→ Answer Generator 是否完成
→ Reviewer 是否执行、结论是什么
→ 最终为什么能够或不能发布
```

DeepSeek Harness 在这一点上的可复用价值，不是其整套插件框架，而是它把 Runtime 事实投影为纯展示模型，再通过统一的折叠行、工具卡片和 Turn Process 展示给用户。

## 3. 问题定义

### 3.1 运行事实存在，但没有形成用户可理解的执行时间线

后端已经发送 `controller_decision / tool_started / tool_completed / publication_completed` 等事件，但前端没有统一地把它们聚合成一个 Turn 内的生命周期对象。

### 3.2 Tool Call 与 Tool Result 展示信息不足

当前 `tool_started` 主要包含：

```text
tool_name
tool_call_id
```

当前 `tool_completed` 主要包含：

```text
tool_name
tool_call_id
status
```

这足以 Debug “调用过什么”，但不足以实现稳定的：

```text
工具名称 · 一行摘要

INPUT
关键调用参数

OUTPUT
关键执行结果 / 错误 / Receipt
```

### 3.3 Browser GIS 与 Backend Tool 的执行位置不同，但展示语义未统一

Backend Tool 在服务端完成，而 GIS Browser Tool 会经历：

```text
Controller
→ ToolRuntime
→ browser_execution_required
→ Browser Bridge
→ Active Map Runtime
→ Receipt
→ Backend Resume
```

用户应该看到这是同一个 Tool Call 的生命周期，而不是两组互不相关的技术事件。

### 3.4 Answer Generator / Reviewer / Publication 的边界没有形成完整 UI 事实

当前已有 `answer_generated` 与 `publication_completed`，但 Reviewer 运行本身没有独立的开始/完成事件，因此用户无法明确区分：

```text
答案已经生成
≠
答案已经通过审查并发布
```

### 3.5 “Reasoning 展示”容易与私有 Chain-of-Thought 混淆

本项目需要让用户看见 Agent 在做什么，但不能把模型私有 Chain-of-Thought 当作产品协议直接暴露。

因此本 PRD 中的“Reasoning”特指：

- 用户可见的阶段摘要；
- 当前动作目的；
- Controller 已提交的结构化决策；
- Runtime 已确认的事实；
- 可选的模型生成短摘要，如果该摘要本身就是明确设计的用户可见输出。

不包括隐藏推理原文。

## 4. 产品目标

用户发送一条 GeoAI 指令后，应能看到一条完整、实时更新、可折叠的 Agent Process。

目标体验示例：

```text
用户
“查一下相关规范，然后把成都滑坡点定位到地图上”

Agent Process                                  5 steps
│
├─ 判断下一步 · 需要先获取知识证据
│
├─ 🔍 检索知识库 · 成都 滑坡 规划规范          ✓
│    INPUT
│    query: 成都 滑坡 规划规范
│
│    OUTPUT
│    返回 5 条候选证据
│
├─ 📌 冻结证据 · 选择 3 条证据                 ✓
│
├─ ⌖ 地图定位 · 成都                           ✓
│    INPUT
│    longitude: ...
│    latitude: ...
│
│    BROWSER
│    Active Runtime: Cesium 3D
│    Receipt: succeeded
│
├─ ✦ 生成答案                                  ✓
│
└─ ✓ 发布                                     published

────────────────────────────────────
最终回答……
```

如果 Reviewer 开启：

```text
✦ 生成答案              ✓
✓ 证据审查              PASS
✓ 发布                  published
```

如果失败：

```text
⌖ 地图定位              ✕
  UNKNOWN_LAYER

发布                    未发布
  原因：工具执行失败
```

## 5. 非目标

本轮明确不做：

- 不重写 Agent Runtime；
- 不替换现有 Controller / Answer Generator / Reviewer；
- 不引入 Cordis；
- 不引入 DeepSeek Harness 的 Slot Registry；
- 不引入其 Session Controller；
- 不重做 Browser Bridge / Active Map Runtime；
- 不为了 UI 再造第二套 Tool 状态机；
- 不把私有 Chain-of-Thought 暴露给用户；
- 不要求所有工具一开始就有专用卡片；
- 不通过前端猜测工具是否成功；
- 不让 UI 状态反向成为 Runtime 的业务真源。

## 6. 第一性原则

### 6.1 Runtime Facts 是唯一执行事实源

前端只展示 Runtime 已经产生的事实。

例如：

```text
tool_started
tool_completed
browser_tool_requested
browser_tool_completed
evidence_frozen
answer_generated
publication_completed
```

前端不得通过“最终回答里写了已完成”推断工具成功。

### 6.2 展示模型不是第二套 Runtime

前端新增的 `AgentEventProjector` 只能做：

- 配对；
- 排序；
- 状态投影；
- 展示摘要派生；
- Generic / specialized renderer 分发。

不能决定：

- 下一步该调用什么；
- Tool 是否合法；
- Evidence 是否可用；
- 是否允许发布。

### 6.3 一个 Tool Call 只有一个稳定生命周期

所有 Tool UI 必须围绕 `tool_call_id` 聚合。

```text
tool_started
        │
        ├── backend execution ──→ tool_completed
        │
        └── browser execution
             → browser_tool_requested
             → browser_tool_completed / cancelled
```

不能把 Browser Receipt 当成另一张独立 Tool Card。

### 6.4 “完整流程”表示完整生命周期，不表示展示全部内部数据

完整流程至少要回答：

1. 当前处于哪个阶段；
2. 为什么进入这个阶段；
3. 调用了什么动作；
4. 动作关键输入是什么；
5. 执行发生在哪里；
6. 成功还是失败；
7. 产生了什么关键事实；
8. 最终是否发布。

大体积 Evidence、长文档、完整模型原始响应等仍应通过摘要、ID、详情页或 Trace 查看，不应直接塞进聊天流。

### 6.5 Generic fallback 必须优先于“一工具一组件”

新增后端 Tool 不应因为前端尚未实现专用 Card 就无法展示。

任何未知 Tool 至少能够展示：

```text
Tool · <tool_name>
状态
输入 JSON
结果摘要 / 错误
```

### 6.6 展示层必须复用统一 Primitive

Reasoning、Tool、Stage、Evidence、Reviewer 不应各自造一套折叠交互。

统一基于一个轻量 `DisclosureRow`。

## 7. 从 DeepSeek Harness 吸收什么

### 7.1 直接吸收：DisclosureRow 模式

参考：

```text
packages/client/ui-primitives/src/DisclosureRow.tsx
```

本项目新增本地轻量实现：

```text
frontend/src/components/agent/DisclosureRow.tsx
```

职责：

- 图标；
- 标题；
- 单行摘要；
- running / success / failed 状态；
- 展开/收起；
- 键盘可访问性；
- reduced-motion 兼容。

不复制 DeepSeek Harness 的 UI token 系统，视觉上适配当前 GeoAI 设计系统。

### 7.2 直接吸收模式：ToolRow

参考：

```text
packages/client/ui-tool/src/client/tool/components/ToolRow.tsx
```

本项目目标：

```text
frontend/src/components/agent/ToolRow.tsx
```

统一支持：

- `running`
- `waiting_browser`
- `succeeded`
- `failed`
- `cancelled`
- INPUT
- OUTPUT
- ERROR
- Browser Receipt 摘要
- 专用 Tool Card 插槽

### 7.3 吸收模式：Generic fallback + keyed renderer

DeepSeek Harness 使用 Slot keyed renderer；本项目不引入 Slot 系统，只保留 keyed dispatch 思想。

建议：

```ts
const toolRenderers = {
  retrieve_kb: KnowledgeSearchToolView,
  import_vector_dataset: ImportVectorToolView,
  locate_map: LocateMapToolView,
  set_layer_visibility: LayerVisibilityToolView,
  set_vector_style: VectorStyleToolView,
  inspect_layer_features: FeatureInspectToolView,
  get_feature_geometry: FeatureGeometryToolView,
  query_spatial_relation: SpatialRelationToolView,
  spatial_overlay: SpatialOverlayToolView,
}
```

未命中时：

```text
GenericToolView
```

### 7.4 吸收模式：ReasoningRow

参考：

```text
packages/client/ui-chat/src/client/chat/ReasoningRow.tsx
```

仅复用：

- running 时显示最新阶段摘要；
- settled 后显示稳定摘要；
- shimmer / running 状态；
- 折叠展开交互。

数据来源必须是本项目明确的用户可见摘要事件或结构化 Runtime Fact，不能读取隐藏 Chain-of-Thought。

### 7.5 强烈吸收：Turn Process

参考：

```text
TurnProcessNodeView
```

当 Turn 正在执行时默认展开。

Turn 完成后自动折叠为：

```text
Agent Process · 3 tools · 1 evidence freeze · reviewer pass
```

用户仍可重新展开查看完整过程。

### 7.6 不吸收的部分

不引入：

- Cordis plugin lifecycle；
- `ctx.slots`；
- ConversationNodeAssembler；
- DeepSeek Session Journal；
- Client Module Graph；
- DeepSeek Tool Runtime；
- PTC nested dispatch。

这些机制服务于 DeepSeek Harness 的通用插件产品形态，本项目当前没有足够收益支持这一复杂度。

## 8. 目标前端架构

```text
Backend Agent Runtime
        │
        │ AgentEvent SSE
        ▼
chatService / contractClient
        │
        ▼
AgentEventProjector
        │
        ▼
AgentTurnViewModel
        │
        ├─ AgentProcessItem[]
        │    ├─ DecisionItem
        │    ├─ ToolItem
        │    ├─ EvidenceItem
        │    ├─ StageItem
        │    ├─ ReviewItem
        │    └─ PublicationItem
        │
        ▼
AgentProcess
        │
        ├─ DisclosureRow
        ├─ ToolRow
        ├─ GenericToolView
        └─ specialized Tool Views
        │
        ▼
Assistant Final Answer
```

## 9. 前端展示模型

### 9.1 AgentTurnViewModel

建议：

```ts
interface AgentTurnViewModel {
  sessionId: string;
  turnId: string;
  traceId: string;
  status: 'running' | 'published' | 'clarification' | 'limited' | 'failed';
  items: AgentProcessItem[];
  startedAt?: string;
  completedAt?: string;
  publicationState?: string;
}
```

### 9.2 AgentProcessItem

```ts
type AgentProcessItem =
  | AgentDecisionItem
  | AgentToolItem
  | AgentEvidenceItem
  | AgentStageItem
  | AgentReviewItem
  | AgentPublicationItem;
```

### 9.3 AgentToolItem

```ts
interface AgentToolItem {
  kind: 'tool';
  callId: string;
  toolName: string;
  status:
    | 'running'
    | 'waiting_browser'
    | 'succeeded'
    | 'failed'
    | 'cancelled';
  arguments?: unknown;
  output?: unknown;
  error?: {
    code?: string;
    message?: string;
  };
  executionSite?: 'backend' | 'browser';
  browserReceipt?: {
    status: string;
    runtimeDimension?: '2d' | '3d';
    stateRevision?: number;
  };
  startedAt?: string;
  completedAt?: string;
}
```

前端使用 `callId` 原地更新同一对象，不生成重复 Tool Card。

## 10. AgentEvent 协议增量

### 10.1 保留现有 Envelope

继续沿用：

```json
{
  "session_id": "...",
  "turn_id": "...",
  "trace_id": "...",
  "payload": {},
  "created_at": "..."
}
```

SSE `event:` 继续直接使用 `event_type`。

不新增第二套 `/agent/events` 协议。

### 10.2 controller_decision

当前已有：

```json
{
  "tool_name": "retrieve_kb",
  "tool_call_id": "..."
}
```

建议增量增加可选字段：

```json
{
  "tool_name": "retrieve_kb",
  "tool_call_id": "...",
  "decision_summary": "需要先检索相关规范证据"
}
```

`decision_summary` 只能是专门设计为用户可见的简短摘要，不得直接复用隐藏 reasoning。

若当前 Controller 没有该能力，本字段可先不实现，UI 直接展示：

```text
下一步 · retrieve_kb
```

### 10.3 tool_started

目标 payload：

```json
{
  "tool_name": "retrieve_kb",
  "tool_call_id": "...",
  "arguments": {
    "query": "..."
  }
}
```

`arguments` 来自已经通过 Tool schema / Runtime 校验并准备执行的 canonical arguments。

前端不得通过解析 Controller 自然语言重建参数。

### 10.4 tool_completed

目标 payload：

```json
{
  "tool_name": "retrieve_kb",
  "tool_call_id": "...",
  "status": "ok",
  "result_summary": {
    "evidence_count": 5
  },
  "error": null
}
```

原则：

- UI 所需的结果事实应来自真实 `ToolObservation`；
- 不要求把完整 Evidence 文本塞进事件；
- 大结果只发送摘要、稳定 ID、数量、状态；
- 详细 Evidence 仍由 Evidence / citation 体系负责。

### 10.5 browser_tool_requested

继续包含：

```text
tool_name
tool_call_id
arguments
```

前端将同一 `ToolItem` 从：

```text
running
```

切换为：

```text
waiting_browser
```

不得创建第二条 Browser Tool。

### 10.6 browser_tool_completed

目标至少包含：

```json
{
  "tool_name": "locate_map",
  "tool_call_id": "...",
  "status": "succeeded",
  "receipt": {
    "effect_status": "applied",
    "state_revision": 12,
    "map_dimension": "3d"
  }
}
```

失败/取消同理进入同一 ToolItem。

### 10.7 evidence_frozen

当前已有：

```text
snapshot_id
evidence_ids
```

前端展示：

```text
冻结证据 · 3 条
snapshot: ...
E1, E4, E7
```

如当前事件后续可安全提供 title / source 摘要，可作为增量 metadata；不要求复制完整文档内容。

### 10.8 answer_generated

当前已有：

```text
kind
citations
```

前端展示：

```text
生成答案 · 3 citations                  ✓
```

最终正文仍只由最终 publication response / assistant message 展示，不能提前把候选 answer 当成已经发布的最终回答。

### 10.9 Reviewer 事件

新增：

```text
review_started
review_completed
```

建议：

```json
{
  "event": "review_completed",
  "payload": {
    "verdict": "PASS",
    "finding_count": 0
  }
}
```

如果 Reviewer 默认关闭，则前端不渲染 Reviewer 行，而不是显示一个虚假的 `SKIPPED` 阶段。

Reviewer 只展示审查事实，不把 Reviewer 重新包装为 Agent Planner。

### 10.10 publication_completed

这是整个 Turn 是否成功发布的最终权威事件。

展示状态示例：

```text
published
clarification
limitation
review_failed
review_rejected
resource_fuse
model_output_failure
```

具体枚举以现有 Runtime 实际状态为准，不由前端自造。

## 11. AgentEventProjector

新增建议位置：

```text
frontend/src/agent/AgentEventProjector.ts
```

职责只有：

```text
event stream
→ stable turn state
```

### 11.1 投影规则

```text
controller_decision
→ append/update DecisionItem

tool_started(call_id)
→ create ToolItem(running)

browser_tool_requested(call_id)
→ ToolItem(waiting_browser)

browser_tool_completed(call_id)
→ attach Receipt
→ ToolItem(succeeded/failed)

tool_completed(call_id)
→ attach backend observation
→ ToolItem(succeeded/failed)

evidence_frozen
→ append EvidenceItem

answer_generated
→ append StageItem(answer_generator, succeeded)

review_started
→ append ReviewItem(running)

review_completed
→ update ReviewItem

publication_completed
→ append PublicationItem
→ settle Turn
```

### 11.2 幂等与乱序要求

Projector 必须以：

```text
session_id + turn_id + tool_call_id
```

作为 Tool identity。

重复 SSE 事件不能产生重复 Tool Row。

收到 result 后不得通过删除过程数据来“简化”状态。

## 12. UI 组件规划

建议新增：

```text
frontend/src/components/agent/
├─ AgentProcess.tsx
├─ AgentProcessSummary.tsx
├─ DisclosureRow.tsx
├─ DecisionRow.tsx
├─ EvidenceRow.tsx
├─ StageRow.tsx
├─ ReviewRow.tsx
├─ PublicationRow.tsx
├─ ToolRow.tsx
└─ tools/
   ├─ GenericToolView.tsx
   ├─ KnowledgeSearchToolView.tsx
   ├─ LocateMapToolView.tsx
   ├─ LayerVisibilityToolView.tsx
   ├─ VectorStyleToolView.tsx
   └─ ...
```

实际实施时应先完成 `GenericToolView`，再按价值逐步增加专用 Tool Card，不能反过来等待所有 Tool Card 完成后才上线。

## 13. Tool 展示优先级

第一阶段专用展示建议只覆盖高价值 Tool：

### P0

- `retrieve_kb`
- `import_vector_dataset`
- `set_layer_visibility`
- `set_vector_style`
- `fit_vector_layer`
- `locate_map`
- `inspect_layer_features`
- `get_feature_geometry`
- `query_spatial_relation`
- `spatial_overlay`

### P1

- `compose_answer`
- 其他后续新增工具

`clarify / limitation` 更适合表现为 Control / Publication 行，不应伪装成普通 Tool Card。

## 14. Chat 数据模型改造

当前 `ChatMessage` 只需要承担最终用户/Assistant 消息，不应该把所有 Agent Process 序列硬塞进 `message.content`。

建议增加独立 Turn 展示状态：

```ts
interface ChatTurn {
  userMessage: ChatMessage;
  process?: AgentTurnViewModel;
  assistantMessage?: ChatMessage;
}
```

如果当前 App 状态改造成本过高，第一阶段可临时在 assistant message metadata 中挂：

```ts
metadata.agent_process
```

但最终推荐 `ChatTurn`，因为 Agent Process 属于 Turn，不属于最终 Assistant Message。

## 15. 实时交互规则

### 15.1 Turn 执行中

Agent Process 默认展开。

当前 running item 应始终保持可见。

新事件到达时，如果用户仍处于自动滚动状态，则跟随到底部；如果用户已经向上阅读，不强制抢回滚动位置。

### 15.2 Turn 完成

满足：

```text
publication_completed
```

后 Agent Process 自动进入“可折叠完成态”。

默认策略：

- 当前刚完成的 Turn 保持短暂可见；
- 最终回答稳定出现后折叠过程；
- 用户手动展开后不再自动收起。

实际动画时长不是业务契约，可在实现阶段根据现有 UI 节奏确定。

### 15.3 错误 Turn

出现失败时默认保持展开，直到用户主动折叠。

不能自动隐藏失败过程。

## 16. “看见全部流程”的最低展示要求

一个 Agent Turn 在 UI 上至少必须可恢复以下事实：

| 阶段 | 必须展示 |
|---|---|
| User input | 用户原始请求 |
| Controller | 结构化下一步动作；可选用户可见摘要 |
| Tool start | Tool 名、稳定 call id、关键参数 |
| Tool finish | 成功/失败、结果摘要、错误 |
| Browser handoff | 是否进入浏览器执行 |
| Browser receipt | succeeded/failed、Active Runtime 维度、revision（如有） |
| Evidence | snapshot id、selected evidence ids/count |
| Answer Generator | 已运行、候选类型、citation count |
| Reviewer | 是否开启、PASS/REVISE/FAIL 类事实 |
| Publication | 最终 publication_state |
| Final answer | 仅展示真正 published / fail-close 后的用户可见结果 |

## 17. 安全与数据边界

不得把以下内容无条件发送到前端：

- 私有 Chain-of-Thought；
- 系统 Prompt 全文；
- API Key；
- Provider credential；
- 未脱敏内部异常栈；
- 超大原始 Evidence 内容；
- 后端对象 repr；
- 非 JSON 安全对象。

Tool input/output 的前端可见字段应在 Runtime/事件生成处明确限定。

## 18. 性能要求

Agent UI 不应每来一个事件就重新构建完整聊天历史。

要求：

- 按 Turn 增量更新；
- 按 `tool_call_id` O(1) 或接近 O(1) 定位 ToolItem；
- Tool body 默认折叠；
- 大 JSON 延迟格式化到展开时；
- UI 展示结果设置长度上限；
- 完整数据需要时通过现有 Trace / detail 机制查看。

不引入 DeepSeek Harness 的完整 Conversation assembler，仅为未来大量历史回放而预先复杂化。

## 19. 测试要求

### 19.1 Projector 单测

必须覆盖：

- `tool_started → tool_completed`；
- `tool_started → browser_tool_requested → browser_tool_completed → continuation`；
- Browser failure；
- duplicate event；
- unknown Tool fallback；
- evidence freeze；
- reviewer on/off；
- publication success；
- publication failure；
- 同一 Turn 多个 Tool；
- 多 Turn 不串状态。

### 19.2 UI 单测

必须覆盖：

- running row；
- succeeded row；
- failed row；
- Generic Tool fallback；
- specialized renderer；
- Process 展开/折叠；
- error Turn 默认展开；
- reduced motion；
- keyboard disclosure。

### 19.3 后端事件契约测试

必须覆盖：

- `tool_started.arguments` 来自实际 canonical ToolCall；
- `tool_completed` 与同一 call id 配对；
- browser receipt 事件保留原 call id；
- Reviewer event 只在 Reviewer 实际开启时产生；
- publication event 最终只产生一个权威完成状态；
- SSE event 顺序与 Runtime 实际执行路径一致。

### 19.4 真实 E2E

至少验证以下场景：

1. 纯知识检索；
2. 2D Browser GIS Tool；
3. 3D Browser GIS Tool；
4. RAG → GIS 连续多步；
5. Browser Tool failure；
6. Reviewer 开启；
7. Reviewer 关闭；
8. fail-close。

验收时不仅验证最终回答，还应验证 Agent Process 中的 Tool、Receipt、Evidence、Publication 与真实 Trace 一致。

## 20. 实施阶段

### Phase 0：冻结现状

- 记录当前 AgentEvent 列表；
- 记录现有 SSE envelope；
- 记录当前 ChatMessage / chatService 行为；
- 不改 Runtime 业务控制流。

### Phase 1：事件协议补全

- `tool_started` 增加 canonical arguments；
- `tool_completed` 增加 UI-safe result summary/error；
- Browser completion 增加 Receipt 摘要；
- 增加 Reviewer start/completed 事件；
- 保持现有 SSE endpoint。

### Phase 2：前端 AgentEventProjector

- 新增 `AgentTurnViewModel`；
- 按 stable IDs 投影；
- 接入 `sendMessageStream()`；
- 不再把结构化 Agent Event 降级为普通 chunk string。

### Phase 3：通用展示基础

- `DisclosureRow`；
- `AgentProcess`；
- `ToolRow`；
- `GenericToolView`；
- Decision / Evidence / Stage / Reviewer / Publication rows。

### Phase 4：GeoAI 专用 Tool Views

优先 GIS + RAG P0 工具。

专用 View 只消费 `AgentToolItem`，不得直接调用 ToolRuntime 或 Browser Bridge。

### Phase 5：Turn Process 折叠

- executing：展开；
- success：默认折叠；
- failed：默认展开；
- 手动状态优先于自动状态。

### Phase 6：真实 E2E 与视觉验收

与现有 GeoAI Real E2E Harness 对齐，验证真实 Browser GIS / RAG / Reviewer / Publication 流程。

## 21. 验收标准

本 PRD 只有同时满足以下条件才可宣称完成：

### 代码层

- 后端事件协议补全；
- 前端 Projector 完成；
- AgentProcess UI 完成；
- Generic Tool fallback 完成；
- P0 Tool 专用展示完成；
- Turn Process 折叠完成。

### 测试层

- 后端 AgentEvent contract tests 通过；
- 前端 projector tests 通过；
- UI tests 通过；
- build/typecheck 通过。

### 真实验收层

至少有一次真实：

```text
用户输入
→ Controller
→ RAG Tool
→ Evidence Freeze
→ Browser GIS Tool
→ Browser Receipt
→ Backend Resume
→ Answer Generator
→ Reviewer（开启场景）
→ Publication
→ Final Answer
```

在浏览器 Agent Process 中完整可见，并能与后端 Trace / Receipt 对齐。

仅“页面看起来像 DeepSeek Harness”不算完成。

## 22. 与现有架构的职责边界

改造后仍保持：

```text
Agent Runtime
    = 执行事实与生命周期权威

Controller
    = 动作与证据编排

Evidence / Frozen Snapshot
    = 知识依据权威

Browser Bridge / Active Map Runtime
    = 浏览器地图执行事实权威

Answer Generator
    = 基于冻结证据生成候选答案

Reviewer
    = 可选发布前审查

Publication
    = 最终用户可见结果权威

AgentEventProjector
    = 把以上事实投影成前端展示状态

AgentProcess UI
    = 只负责呈现
```

## 23. 最终原则总结

本轮不是“把 DeepSeek Harness 前端搬过来”，而是吸收其最有价值的三个原则：

1. **统一 Disclosure Row**：Reasoning、Stage、Tool 都使用一致的交互语言；
2. **Tool Lifecycle + Generic fallback + keyed renderer**：所有 Tool 默认可展示，高价值 Tool 再逐步专用化；
3. **Turn Process**：把完整执行过程作为 Turn 的一等展示对象，并与最终回答严格分离。

最终必须形成：

```text
真实 Runtime Facts
      ↓
稳定 Event Contract
      ↓
轻量 Frontend Projector
      ↓
Agent Process
      ↓
最终回答
```

而不是：

```text
后端字符串日志
      ↓
前端硬编码判断
      ↓
看起来像 Agent 的 UI
```

这保证展示层能够吸收 DeepSeek Harness 的成熟 UX，同时继续服从本项目现有 Agent Runtime、Evidence、Browser Receipt、Active Map Runtime、Answer Generator、Reviewer 和 Publication 的职责边界。
