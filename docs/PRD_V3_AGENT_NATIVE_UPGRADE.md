# GeoAI Agent-Native V3 全面升级 PRD

## 文档信息

- 版本：V3.0
- 日期：2026-09-10
- 项目路径：`D:\work\Project\ragAI知识库 (2)\ragAI知识库`
- 关联成熟知识上游：`D:\work\Project\agentic rag`，冻结基线 `2eab8d5c479ba32c27b7c929a35c273edf0a2f64`
- 关联 GIS 能力上游：`D:\work\Project\gis-agent-core`，冻结基线 `ee3d30667fbd0b970633d32265f97c6d147c35c1`
- 代码迁移授权：两个上游仓库与 GeoAI 均由 `edjsh175` 本人控制，允许按本 PRD 选择性迁入
- 文档性质：架构升级与分阶段迁移 PRD

---

# 1. 项目背景

当前 GeoAI 项目已经具备标准规范检索、AI 问答、引用展示、OpenLayers 2D 地图、Cesium 3D 地图、PostGIS 空间能力、认证与访客体验等基础功能。

但现有知识问答链路仍主要由 GeoAI 自身的 `SearchService`、检索器、重排序器、LLM 生成逻辑以及前端部分正则解析共同完成。这套实现可以支撑传统 RAG 问答，但随着项目目标从“标准查询 + 地图展示”升级为“Agent 驱动的 GeoAI 应用”，原架构存在以下核心问题：

1. GeoAI 自身维护了一套独立 RAG 与生成逻辑，与成熟的 `agentic rag` 能力重复。
2. 前端存在自然语言意图识别和追问解析逻辑，例如“这个标准”“该地区”“第一个”等，不符合 UI 只负责状态与交互的职责边界。
3. 地图控制仍部分依赖后端从模型文本中解析 `map_action`，本质是文本协议而非正式 Tool Calling。
4. 如果后续直接将 `gis-agent-core` 中的 DeepSeek Harness 也接入，则会形成第二套 Agent Loop 与第二个 Controller，导致职责和状态来源冲突。
5. 知识事实、Agent 决策和地图状态目前缺乏明确的唯一真源定义。

因此，本轮升级不再以“替换一个 Retriever”作为目标，而是重新定义整个系统的 Agent 原生架构。

---

# 2. 产品目标

本轮 V3 升级的核心目标是：

> 将当前 GeoAI 从“RAG + 地图展示型系统”升级为“由单一 Agent Controller 统一规划知识查询与最小 GIS 操作的 Agent-Native GeoAI 系统”。

用户通过一个统一对话入口，可以完成：

1. 查询测绘、国土空间规划、GIS 标准与相关规范资料；
2. 获得基于证据的回答与可追溯引用；
3. 进行多轮追问、消歧与上下文理解；
4. 根据自然语言要求，让 Agent 控制当前地图进行定位/移动；
5. 根据自然语言要求，让 Agent 选中并高亮已存在于地图中的目标要素；
6. 在 GIS 操作后，Agent 能重新观察真实地图状态，再决定是否继续操作或结束回答。

本阶段明确不追求完整 GIS Agent 能力，只验证最小可用闭环。

---

# 3. 第一性原则与架构约束

## 3.1 单一 Agent Controller

系统中只能存在一个负责下一步决策的 Agent Controller。

本项目正式使用从 `agentic rag` 冻结版本选择性迁入 GeoAI 的 Main Controller / Agent Loop，作为唯一 Agent 决策真源。运行时由 GeoAI 仓库拥有和部署，不依赖外部源仓库进程。

`gis-agent-core` 中现有的 DeepSeek Harness 只保留为 GIS Core 自身的开发与端到端测试 Harness，不进入 GeoAI 正式生产架构。

禁止形成以下结构：

```text
GeoAI Agent
    +
GIS Harness Agent
    +
RAG Agent
```

正式结构必须是：

```text
Agentic RAG Controller
        |
        +-- Knowledge Tools
        |
        +-- GIS Environment Tools
```

## 3.2 单一知识事实真源

标准、规范、文档、图谱关系和知识问答证据统一由 GeoAI 内置 Agent Runtime 管理。该 Runtime 的成熟基线来自 `agentic rag` 冻结版本。

GeoAI 原有的 RAG Retriever、Reranker、Prompt、生成器和引用判定不再作为正式知识真源。

迁移完成后，同一个问题不得同时访问两套独立 RAG 并拼接结果。

## 3.3 单一地图状态真源

用户当前真实地图状态以浏览器中的 GIS Runtime 为唯一真源。

Agent 不允许根据历史文本或自身推测判断当前地图是否移动、是否已高亮、当前视口位置等。

每次需要 GIS 决策时，应读取当前 `MapContext`；每次 GIS Tool 执行后，应再次读取最新 `MapContext`。

## 3.4 Tool Calling 优先于文本协议

不再允许 LLM 通过回答正文中的 JSON、Markdown 或特殊字符串隐式控制地图。

旧的：

```text
LLM -> Markdown JSON -> extract_map_action() -> 地图
```

必须替换为：

```text
Controller -> GIS Tool Call -> GIS Capability -> 地图 -> Tool Result
```

## 3.5 UI 不负责自然语言理解

前端不再自行解析：

- “这个标准”
- “该地区”
- “这里”
- “第一个”
- “上面那个”
- “当前省份”

上述理解统一交由 `agentic rag` 的 Stage 1、ConversationContext、Identity 与 SemanticTask 处理。

前端只负责：

- 显示；
- 交互；
- 传递历史消息；
- 提供真实地图状态；
- 执行浏览器 GIS Tool；
- 返回执行回执。

## 3.6 Observation 优先于模型猜测

Agent GIS 操作必须遵循：

```text
Observe -> Decide -> Act -> Observe
```

而不是：

```text
Decide -> 假设执行成功 -> 回答
```

## 3.7 证据类型隔离

系统必须严格区分：

### Knowledge Evidence

标准文档、Chunk、已审核图谱关系等。

可进入 EvidencePool / Evidence Snapshot，可作为最终回答引用。

### Spatial Data Evidence

服务端空间数据查询结果，例如 PostGIS 或 GeoServer 返回的对象。

本阶段只在后续需要时保留扩展位，不作为本轮重点。

### Runtime Observation

MapContext、当前高亮对象、当前视口、GIS Tool 执行成功/失败等。

只能证明运行状态，不能作为标准规范知识引用。

---

# 4. 本轮范围

## 4.1 In Scope

本轮必须完成：

1. 从 `agentic rag` 冻结版本选择性迁入完整 Agent Runtime 子系统，作为 GeoAI 唯一知识问答与 Agent 编排后端；
2. GeoAI 后端增加面向 Agent 的 Gateway / Adapter；
3. GeoAI 前端聊天链路改接内置 Agent Runtime；
4. 支持内置 Agent Runtime 的 SSE 运行事件；
5. 支持引用、Evidence Snapshot 对应的来源展示；
6. 支持 Agent 澄清卡片与澄清恢复；
7. 接入 `gis-agent-core` 的最小 GIS Capability；
8. 支持浏览器权威 MapContext；
9. 支持“地图移动/定位”；
10. 支持“选中并高亮地图中已有目标要素”；
11. 支持 GIS Tool Call -> 浏览器执行 -> Tool Result -> Agent Resume；
12. 删除或停用旧的基于文本 `map_action` 的主链路；
13. 删除或停用前端自然语言正则追问解析主链路；
14. 保留现有认证、访客配额、PostGIS、地图页面与文档资产能力。

## 4.2 Explicitly Out of Scope

本阶段明确不做：

1. SHP 导入；
2. GeoJSON 文件导入；
3. 用户文件引用管理；
4. 用户矢量图层创建；
5. 用户矢量图层样式设置；
6. fit_vector_layer；
7. 用户图层显隐控制；
8. 删除用户图层；
9. 业务卡片生成；
10. 业务卡片刷新；
11. 业务卡片持久化；
12. 业务卡片归档与删除；
13. 自动修改前端页面代码；
14. Agent 驱动重新打包部署；
15. Cesium 3D Agent 工具执行；
16. 大规模空间分析工具扩展；
17. 本轮同时重构 Chroma、pgvector、MySQL、SQLite 等底层存储；
18. 将所有 GIS 能力一次性迁入 Agent。

这些能力只保留后续扩展接口，不进入本轮验收。

---

# 5. 本轮 GIS Capability 精确定义

本轮只暴露两类业务能力。

## 5.1 地图移动 / 定位

目标：Agent 能根据已经确认的目标对象，让当前 OpenLayers 地图视图移动到对应目标。

推荐正式工具名：

```text
locate_features
```

输入应使用稳定 Feature Reference，而不是直接传入完整 Geometry。

示例：

```json
{
  "feature_ref": {
    "resultId": "result_xxx",
    "indices": [0]
  }
}
```

执行语义：

1. 根据 `feature_ref` 解析到当前有效 Feature；
2. 计算目标 extent；
3. 调用 OpenLayers View 完成移动或 fit；
4. 等待视图动作完成或进入稳定状态；
5. 返回 Tool Result；
6. 重新读取 MapContext；
7. 将最新状态反馈给 Controller。

## 5.2 选中 / 高亮

目标：Agent 能把当前地图中已经存在的目标要素设置为选中/高亮状态。

推荐正式工具名：

```text
highlight_features
```

输入同样只接受稳定 Feature Reference。

示例：

```json
{
  "feature_ref": {
    "resultId": "result_xxx",
    "indices": [0]
  },
  "group": "selection",
  "mode": "replace",
  "effect": "persistent"
}
```

本轮默认行为：

- group：`selection`
- mode：`replace`
- effect：`persistent`

即一次 Agent 选中操作默认替换上一次选中结果，并保持高亮，直到用户、前端逻辑或下一次 Agent 操作改变它。

## 5.3 本轮不暴露的 GIS Core 工具

即便 `gis-agent-core` 已经存在以下工具，本轮 GeoAI 正式 Agent Registry 也不得向 Controller 暴露：

```text
import_vector_dataset
set_vector_style
fit_vector_layer
set_user_layer_visibility
remove_user_layer
list_user_layers
get_user_layer_info
```

如果 Core 中还存在更多数据加载或业务卡片类 Tool，也同样不注册到本轮 Environment Tool Provider。

---

# 6. Feature Reference 策略

## 6.1 原则

LLM 不直接接收和回传完整 GeoJSON Feature。

不允许：

```text
LLM Context
  <- 几百或几千个 FeatureCollection
```

必须采用：

```text
查询/匹配结果
    |
    v
FeatureReferenceStore
    |
    v
resultId + indices
    |
    v
Controller
```

## 6.2 本轮 Feature 来源

由于本阶段不做用户数据导入，Feature 只来自 GeoAI 当前已经存在的地图业务数据。

第一阶段优先支持当前最稳定的行政区划 Feature，例如省级行政区。

例如用户问：

```text
“定位到四川省并选中它”
```

系统链路可以是：

```text
Stage 1 确认四川省
    |
GIS 目标解析
    |
生成/取得 Feature Reference
    |
locate_features
    |
highlight_features
```

不要求模型知道 `Feature` 对象内部结构。

---

# 7. MapContext 设计

## 7.1 浏览器权威

`MapContext` 由浏览器当前真实 OpenLayers Runtime 即时读取。

它至少应包含：

```json
{
  "schemaVersion": 3,
  "dimension": "2d",
  "ready": true,
  "revision": 12,
  "viewport": {},
  "visibleLayers": [],
  "selection": {},
  "highlight": {},
  "supportedTools": [
    "locate_features",
    "highlight_features"
  ]
}
```

本阶段不要求：

```text
userLayers
availableFiles
businessCards
```

## 7.2 注入方式

每轮 Agent 执行开始时，前端将最新 `MapContext` 作为 Environment Context 传入。

GIS Tool 执行后，再次读取最新 MapContext，并随 Tool Result 一起反馈。

## 7.3 MapContext 不得进入知识证据引用

MapContext 应作为 runtime observation / environment context 进入 Agent 上下文。

它可以支持：

```text
“地图当前已经定位到四川省。”
```

但不能支持：

```text
“四川省应当执行某规范。”
```

后者必须来自 Knowledge Evidence。

---

# 8. 目标系统架构

```text
+----------------------------------------------------+
|                GeoAI React Frontend                |
|                                                    |
|  Chat UI      Citation UI      Clarify UI          |
|                                                    |
|  OpenLayers Map                                    |
|      |                                             |
|      +-- GeoAI GIS React Adapter                   |
|              |                                     |
|              +-- MapRuntime                        |
|              +-- MapContext                        |
|              +-- FeatureReferenceStore             |
|              +-- OpenLayers Adapter                |
|              +-- Browser GIS Tool Executor         |
+---------------------------+------------------------+
                            |
                 SSE / Tool Call / Receipt
                            |
                            v
+----------------------------------------------------+
|                 GeoAI Backend                      |
|                                                    |
| Auth / Visitor Quota / Agent API                   |
| Agent Session / GeoAI Adapter                      |
| Spatial API / Document Assets                      |
|                                                    |
| Embedded Agent Runtime                             |
|   -> Stage 1 / ConversationContext                 |
|   -> Identity / SemanticTask                       |
|   -> Main Controller / Agent Loop                  |
|   -> Knowledge + GIS Environment Tool Registry     |
|   -> EvidencePool / Snapshot                       |
|   -> Answer Generator / Grounding Reviewer         |
|   -> Publication                                   |
+----------------------------------------------------+
```

---

# 9. 三个仓库的正式职责与迁入边界

## 9.0 Fork at Integration Boundary

`agentic rag` 与 `gis-agent-core` 是成熟上游参考实现和代码源。两个源仓库保持只读、可独立运行和可独立测试；GeoAI 记录选定 commit、来源文件、授权与依赖闭包，按职责选择性迁入，并从迁入后开始拥有自己的集成版本。

禁止直接从 GeoAI import 本机外部仓库路径。后续同步必须以新上游 commit 为输入，经过差异审查、测试和选择性合并，不允许直接修改源仓库或无边界整仓覆盖。

## 9.1 `agentic rag`

定位：通用 Agentic Knowledge Runtime 的只读成熟上游。

GeoAI 从冻结版本迁入完整 Agent Runtime 职责链：

- Stage 1；
- ConversationContext；
- Identity；
- SemanticTask；
- Main Controller；
- Agent Loop；
- Tool Registry；
- Knowledge Retrieval；
- Knowledge Graph；
- EvidencePool；
- Evidence Snapshot；
- Answer Generator；
- Grounding Reviewer；
- Reviewer Resume；
- Publication；
- QA Trace；
- Environment Tool Extension。

上游源仓库不负责：

- 直接访问 OpenLayers 实例；
- 持有浏览器地图对象；
- React UI 状态。

## 9.2 `gis-agent-core`

定位：通用 GIS Agent Capability / Runtime SDK 的只读成熟上游。

本阶段选择性迁入：

- GIS Tool Contract；
- MapRuntime；
- MapContext；
- FeatureReferenceStore；
- OpenLayers Adapter；
- locate/highlight 相关 Client Capability；
- 浏览器 Tool Call / Tool Result 协议思想。

`application.js` 的 Vue/23dmaps 边界不迁入；OpenLayers Adapter 只有在其依赖的高亮 helper 闭包同时明确时才迁入，否则由 GeoAI 基于迁入 contract 实现专用 adapter。

本阶段不进入生产主链路：

- DeepSeek Harness Agent Loop；
- User Vector 导入链；
- Business Artifact / Card；
- Dataset Import；
- Style Editing。

## 9.3 GeoAI 主项目

定位：最终完整产品仓库，以及迁入代码的集成版本所有者。

负责：

- React UI；
- Chat UI；
- Citation UI；
- Clarification UI；
- OpenLayers / Cesium 页面；
- GeoAI GIS React Adapter；
- Auth；
- Visitor Quota；
- PostGIS；
- Spatial API；
- Document Assets；
- Agent Gateway；
- 内置 Agent Runtime；
- 上游来源清单与选择性同步流程；
- Browser Tool Executor。

迁移完成后，旧 GeoAI 实现不再负责：

- 第二套或平行的 Agent Controller；
- 绕过内置 Agent Runtime 的 RAG Answer；
- 绕过内置 Agent Runtime 的 Evidence Governance；
- 前端自然语言意图解析。

---

# 10. GeoAI Agent Runtime GIS Environment Tool 扩展

`agentic rag` 冻结版本中的 `build_agent_registry()` 已经支持 `environment_tools` 扩展口。该能力随 Agent Runtime 依赖闭包迁入 GeoAI 后，在 GeoAI 集成版本中扩展。

本轮必须将该扩展能力正式接入 `_run_agent_turn()`。

目标形式：

```python
build_agent_registry(
    allow_web_search=...,
    environment_tools=environment_tools,
)
```

本阶段 Environment Tool Provider 只提供：

```text
locate_features
highlight_features
```

每个 Tool 必须具备：

- name；
- description；
- input_schema；
- side_effect；
- permission；
- handler；
- timeout；
- ToolObservation 映射。

浏览器执行类工具的 handler 不直接执行 OpenLayers，而是产生 Pending Tool Call，等待浏览器回执后恢复 Agent Loop。

---

# 11. Agent Session 与浏览器 Tool Resume

## 11.1 为什么需要会话恢复机制

`locate_features` 和 `highlight_features` 必须在浏览器内执行。

GeoAI Backend 内置 Agent Runtime 不能同步直接访问用户页面中的 OpenLayers。

因此一次 Agent Run 可能出现：

```text
Controller
  -> Tool Call
  -> 暂停
  -> 浏览器执行
  -> Tool Result
  -> Resume
  -> Controller 继续
```

## 11.2 状态绑定

至少使用以下绑定字段：

```text
session_id
run_id
call_id
browser_session_id
```

Tool Result 必须和 pending call 严格关联。

禁止客户端随意提交一个与当前 Agent Tool Call 无关的 GIS Result。

## 11.3 Tool Result

建议结构：

```json
{
  "call_id": "call_001",
  "tool": "locate_features",
  "result": {
    "ok": true,
    "data": {
      "featureCount": 1
    }
  },
  "map_context": {
    "revision": 13
  }
}
```

Agent Resume 后，应将 MapContext 作为 Runtime Observation，而不是 Knowledge Evidence。

---

# 12. GeoAI Backend 改造目标

GeoAI Backend 不删除，而是转型为 Agent Runtime Host + BFF / Gateway。它必须可以随 GeoAI 独立部署，不要求同时启动两个上游源仓库。

## 12.1 保留

- `/api/auth/*`
- Visitor Session / Quota
- `/api/spatial/*`
- `/api/documents/*`
- 系统健康检查
- PostGIS
- 文档下载与资产接口

## 12.2 新增

建议增加：

```text
POST /api/agent/sessions
POST /api/agent/query/stream
POST /api/agent/tool-results
POST /api/agent/clarifications
POST /api/agent/cancel
```

实际命名可在实现计划阶段结合现有 API 风格调整。

## 12.3 逐步退役

以下能力迁移完成后退役：

- `SearchService.generate_answer`
- `SearchService.generate_stream_answer`
- GeoAI 自有意图分类
- GeoAI 自有 RAG Retriever 主链路
- GeoAI 自有 Reranker 主链路
- `extract_map_action`
- 通过 Markdown JSON 控制地图的方式

`/api/search/*` 后续只保留纯搜索业务接口时，可以继续存在；但聊天入口不再借用 `/api/search/query` 作为 Agent 对话接口。

---

# 13. GeoAI Frontend 改造目标

## 13.1 Chat

当前：

```text
chatService
  -> /api/search/query
```

升级后：

```text
agentService
  -> /api/agent/query/stream
```

前端必须支持：

- Agent reasoning/activity 展示；
- Tool Start；
- Tool End；
- Clarify；
- Citation；
- Final Answer；
- Browser GIS Tool Pending；
- Browser GIS Tool Result；
- Cancel。

## 13.2 删除前端 NLP 职责

当前 `App.tsx` 内存在地区引用、文档追问、序号追问等正则逻辑。

升级完成后，这些逻辑应从主聊天路径删除。

包括但不限于：

- `REGION_REFERENCE_PATTERN`
- `CURRENT_REGION_QUERY_PATTERN`
- `DOCUMENT_REFERENCE_PATTERN`
- `ORDINAL_PATTERNS`
- `resolveFollowUpContext`
- 其他依赖 UI 正则理解自然语言的逻辑

如果某些正则仍被纯 UI 功能使用，应重新评估后保留，但不得参与 Agent 意图与事实解析。

---

# 14. GIS React Adapter

`gis-agent-core/src/gis/application.js` 当前直接依赖 23dmaps Vue Store，因此不能直接作为 GeoAI React 应用入口。

应新增 GeoAI React Adapter，负责把 GeoAI 的：

```text
React
Zustand
OpenLayersMap
```

接入 GIS Core 底层能力。

Adapter 只负责框架边界，不重复发明已经选择性迁入的：

- MapRuntime；
- Feature Reference；
- MapContext；
- locate/highlight；
- OpenLayers Adapter 逻辑。

原则：

> 冻结成熟上游实现，按职责选择性迁入 GeoAI；不修改上游仓库，不做无边界整仓复制。

---

# 15. 用户场景

## 15.1 标准问答

用户：

```text
四川省有哪些测绘相关标准？
```

链路：

```text
Stage 1
 -> retrieve_kb
 -> EvidencePool
 -> compose_answer
 -> Answer Generator
 -> Reviewer
 -> Citation Answer
```

不发生 GIS Tool Call 也完全合法。

## 15.2 标准问答 + 地图定位

用户：

```text
四川省有哪些相关测绘标准？顺便定位到四川省。
```

链路：

```text
Stage 1
 -> retrieve_kb
 -> Knowledge Evidence
 -> GIS target resolution
 -> locate_features
 -> Browser Tool Result
 -> latest MapContext
 -> compose_answer
 -> Reviewer
 -> Final Answer
```

## 15.3 地图定位 + 高亮

用户：

```text
定位到四川省并选中它。
```

链路：

```text
Stage 1
 -> 确认四川省
 -> Feature Reference
 -> locate_features
 -> Observation
 -> highlight_features
 -> Observation
 -> direct/compose final response
```

这里不要求执行 RAG 检索，因为用户问题本质是地图控制任务。

## 15.4 多轮追问

用户第一轮：

```text
定位到四川省。
```

第二轮：

```text
再把它选中。
```

应由 ConversationContext 解析“它”的指代，并结合当前 MapContext 判断当前目标。

前端不得通过正则自行替换“它”。

---

# 16. 失败与降级规则

## 16.1 地图未就绪

如果：

```text
MapContext.ready = false
```

则 GIS Tool 不应执行。

返回明确 ToolObservation：

```text
MAP_NOT_READY
```

Controller 可选择说明地图尚未就绪，而不是假装执行成功。

## 16.2 Feature Reference 失效

如果 Feature Reference 已过期或无法解析：

```text
FEATURE_REF_EXPIRED
```

Controller 应重新获取合法目标引用或向用户说明当前对象已失效。

## 16.3 工具执行失败

Browser Tool 执行失败必须：

- 返回结构化错误；
- 不更新为成功状态；
- 不允许最终答案声称“已定位/已高亮”。

## 16.4 Agentic RAG 不可用

GeoAI Gateway 应返回清晰的 Agent Service Unavailable 状态。

本阶段不要求自动切回旧 RAG，因为长期双真源会制造架构债务。

迁移测试阶段可以通过 feature flag 临时保留旧链路用于对照，但正式切换后不再自动混用。

---

# 17. 数据与存储策略

本轮不同时重构底层知识存储。

GeoAI 内置 Agent Runtime 首先沿用 `agentic rag` 冻结版本中已经成熟的：

- Chroma；
- RelationalDB；
- ingestion；
- Knowledge Graph；
- Evidence / Trace 存储。

GeoAI 原 PostgreSQL 继续负责：

- PostGIS；
- 空间业务数据；
- GeoAI 自身业务数据。

GeoAI 原 pgvector RAG 数据在迁移完成后停止作为聊天知识真源。

是否未来统一为 PostgreSQL/pgvector，应作为独立 PRD，不与本轮 Agent 架构迁移捆绑。

---

# 18. 分阶段实施计划

## G0：现状冻结与基线

目标：确保升级前已有行为可回归。

完成项：

- 记录旧聊天主链路；
- 记录引用行为；
- 记录当前 2D 地图定位与选中行为；
- 建立最小 E2E 测试集合；
- 建立 feature flag，允许新旧链路测试期间切换；
- 记录两个上游仓库 URL、commit、工作树状态与迁入文件清单；
- 记录仓库所有者对 GeoAI 选择性迁入的内部授权；
- 建立 source manifest 与上游差异审查规则。

## G1：Agent Runtime 迁入与 GeoAI Adapter

目标：GeoAI 从 `agentic rag` 冻结版本迁入完整 Agent Runtime 职责链，并能在不启动上游仓库服务的情况下独立运行。

完成项：

- Agent Runtime source manifest；
- 模块与 import dependency closure；
- GeoAI config / storage / API adapter；
- Agent Session；
- SSE Event Adapter；
- 错误映射；
- Auth / Visitor Quota 对接；
- 最小健康检查。

验收：

```text
GeoAI API -> Embedded Agent Runtime -> RAG Answer -> Citation
```

闭环成功。

## G2：前端 Agent Chat 替换

目标：Chat 不再依赖 `/api/search/query` 生成回答。

完成项：

- agentService；
- SSE Event Reducer；
- Final Answer；
- Citation；
- Clarification Card；
- Cancel；
- Trace ID。

验收：

用户可在原 GeoAI 页面完成 Agentic RAG 标准问答和澄清。

## G3：旧知识问答链路下线

目标：建立单一知识真源。

完成项：

- 停止 `SearchService` 负责生成回答；
- 停止前端自行 follow-up 语义解析；
- 聊天路径只走 Agentic RAG；
- 旧纯搜索 API 可暂时保留。

## G4：GIS Core 最小接入

目标：把 GeoAI OpenLayers 接入 GIS Core Runtime。

只接入：

```text
MapRuntime
MapContext
FeatureReference
locate_features
highlight_features
```

明确不接入 User Vector 与 Business Card。

验收：

浏览器本地调用 Capability 可以：

- 定位到一个现有行政区 Feature；
- 高亮一个现有行政区 Feature；
- MapContext 正确反映执行后的状态。

## G5：Agent GIS Environment Tools

目标：Agentic RAG Controller 能看到且调用两个 GIS 工具。

完成项：

```text
EnvironmentToolProvider
 -> locate_features
 -> highlight_features
```

其他 GIS Tool 不暴露。

验收：

Controller 在需要地图动作时能自主选择正确工具。

## G6：Browser Tool Call / Receipt / Resume

目标：完成最小 Agent-GIS 闭环。

链路：

```text
用户
 -> Agent Controller
 -> locate/highlight Tool Call
 -> Browser
 -> OpenLayers
 -> Tool Result
 -> MapContext
 -> Agent Resume
 -> Final Answer
```

G6 为本轮核心里程碑。

## G7：旧 map_action 与重复 GIS 逻辑清理

完成项：

- 删除/停用 `extract_map_action` 主链路；
- 删除回答文本 JSON 控图；
- 清理前端重复地图控制桥接；
- 保证 GIS Runtime 成为唯一地图 Agent 操作入口。

## G8：最终回归与架构审计

完成项：

- 单元测试；
- Agentic RAG 集成测试；
- Browser E2E；
- GeoAI Full E2E；
- 安全边界审查；
- 双真源检查；
- 旧代码清理检查；
- 文档同步。

---

# 19. 验收标准

## 19.1 架构验收

必须满足：

1. 只有一个 Agent Controller；
2. 知识问答只由 GeoAI 内置 Agent Runtime 生成与审核；
3. 地图状态只由浏览器 GIS Runtime 提供；
4. GIS 操作通过 Tool Call 而不是文本解析；
5. MapContext 不进入 Knowledge Evidence；
6. GeoAI 前端不再负责自然语言追问理解；
7. `gis-agent-core` DeepSeek Harness 不进入正式生产 Agent Loop；
8. 本轮 Agent Registry 只暴露 `locate_features` 与 `highlight_features` 两个 GIS 工具。

## 19.2 功能验收

### Case A：纯知识问答

```text
“什么是国土空间规划？”
```

预期：

- Agentic RAG 完成检索；
- 输出基于证据的回答；
- 引用可查看；
- 不触发 GIS Tool。

### Case B：地图定位

```text
“定位到四川省。”
```

预期：

- Agent 调用 `locate_features`；
- 浏览器 OpenLayers 真实移动；
- Tool Result 返回成功；
- 新 MapContext revision 增加；
- Agent 最终回答只在成功回执后声明已定位。

### Case C：地图高亮

```text
“选中四川省。”
```

预期：

- Agent 调用 `highlight_features`；
- 四川省真实高亮；
- MapContext 中 highlight/selection 状态更新；
- Agent 在回执成功后结束。

### Case D：连续地图操作

```text
“定位到四川省并选中它。”
```

预期：

```text
locate_features
 -> receipt
 -> MapContext
 -> highlight_features
 -> receipt
 -> MapContext
 -> final
```

不允许一次性假设两个动作均成功。

### Case E：知识 + 地图

```text
“四川省有哪些测绘标准？然后定位到四川省。”
```

预期：

- 知识检索和 GIS Tool 均由同一个 Controller 规划；
- Knowledge Evidence 用于标准回答；
- Runtime Observation 用于描述地图动作；
- 两者不会混淆为同一种证据。

### Case F：地图未就绪

预期：

- GIS Tool 被拒绝或失败；
- Agent 不声称地图已经移动/高亮；
- 返回清晰可理解的失败说明。

---

# 20. 非功能要求

## 20.1 可测试性

每一层必须独立测试：

- AgentRuntimeAdapter 与迁入一致性测试；
- Environment Tool Registry；
- Browser Tool Broker；
- MapRuntime；
- MapContext；
- Feature Reference；
- locate；
- highlight；
- Tool Resume；
- Full E2E。

## 20.2 可观测性

至少记录：

```text
session_id
run_id
trace_id
call_id
tool_name
tool_status
map_context_revision
agent_terminal_status
```

但日志不得泄露不必要的凭据与敏感配置。

## 20.3 幂等与关联

同一 `call_id` 的 Tool Result 不得被重复应用为两次地图操作。

错误 `call_id` 不得恢复其他 Agent Run。

## 20.4 超时

浏览器 Tool 等待必须有明确 lease / timeout。

超时后 Tool Observation 必须为失败，不允许无限阻塞 Agent Run。

---

# 21. 迁移红线

本轮实施过程中禁止：

1. 直接修改 `agentic rag` 或 `gis-agent-core` 上游源仓库；
2. 同时运行两个生产 Agent Controller；
3. 把 DSH Harness 作为正式 GeoAI GIS Agent；
4. 继续新增 Markdown JSON 控地图逻辑；
5. 继续新增 React 正则意图理解；
6. 把完整 FeatureCollection 注入 LLM；
7. 把 MapContext 当作标准知识引用；
8. 把 User Vector 能力顺手接入；
9. 把业务卡片顺手接入；
10. 在本轮同时替换所有数据库技术栈；
11. 为了兼容旧代码而长期保留双 RAG 真源；
12. GIS Tool 未收到成功回执时向用户声明执行成功；
13. 无边界复制整个上游仓库或引入本轮范围外模块；
14. 从 GeoAI 运行时直接 import 本机外部仓库路径；
15. 未记录来源 commit、迁入文件和授权就复制代码；
16. 未经差异审查和测试直接覆盖式同步上游更新。

---

# 22. 本轮完成定义 Definition of Done

当且仅当以下条件全部满足时，本轮 V3 升级可判定完成：

1. GeoAI 聊天主链路已切换到内置 Agent Runtime；
2. 从 `agentic rag` 成熟基线迁入的 Agent Runtime 是唯一知识问答与 Agent Controller；
3. 原 GeoAI RAG 生成主链路已退出聊天路径；
4. `gis-agent-core` 的最小 Capability 已适配进 GeoAI React/OpenLayers；
5. 只注册 `locate_features` 和 `highlight_features` 两个 GIS Environment Tools；
6. Agent 可以自主调用这两个 GIS Tool；
7. 浏览器能执行真实 OpenLayers 操作；
8. Tool Result 能恢复原 Agent Run；
9. Tool 执行后 MapContext 能重新反馈给 Controller；
10. “定位四川省并选中它”完成端到端闭环；
11. 知识证据与 Runtime Observation 没有混用；
12. 旧 `map_action` 主链路已退出；
13. 前端 NLP 正则不再承担 Agent 语义解析职责；
14. 未接入数据导入、样式设置和业务卡片；
15. 全量关键回归与新架构 E2E 通过；
16. 架构文档、API Contract 与代码实现一致；
17. GeoAI 可独立部署，不要求相邻启动 `agentic rag` 或 `gis-agent-core`；
18. 两个上游源仓库的 commit 和工作树未被 GeoAI 定制修改；
19. 来源、迁入清单与内部授权记录完整。

---

# 23. 后续阶段预留，但本轮不实现

本轮完成后，可独立立项：

## V3.1 GIS Query Tools

- list_layers
- query_features
- PostGIS spatial query
- GeoServer WFS/WMS

## V3.2 User Vector

- SHP
- GeoJSON
- file_ref
- import_vector_dataset
- style
- fit
- visibility

## V3.3 Business Artifact

- 动态业务卡片
- 持久化
- 刷新
- 删除
- 归档

## V3.4 3D Agent

- Cesium Adapter
- 2D/3D 统一 Capability

## V3.5 Storage Consolidation

- Chroma / pgvector 统一评估
- RelationalDB -> PostgreSQL 评估
- 统一知识资产生命周期

这些均不得阻塞当前 V3.0 最小闭环。

---

# 24. 最终架构原则摘要

```text
Single Controller
Single Knowledge Truth
Single Map Truth
Capability over Hardcoding
Tool Calling over Text Protocol
Observation over Assumption
Evidence over Generation
Curated Upstream Extraction
Minimal GIS Scope First
```

中文解释：

- 一个 Agent 控制器；
- 一个知识事实真源；
- 一个真实地图状态真源；
- 使用能力抽象，而不是业务硬编码；
- 使用正式 Tool Calling，而不是回答文本暗号；
- 使用真实观察，而不是模型猜测；
- 使用证据约束回答；
- 冻结成熟上游版本，按职责选择性迁入 GeoAI，并由 GeoAI 在集成边界内适配和演进；
- GIS 本阶段只做最小闭环：定位与高亮。

本 PRD 是 GeoAI V3.0 实施与验收的架构基线。后续代码变更若与本 PRD 冲突，应优先重新审查架构，而不是通过兼容代码绕过边界。
