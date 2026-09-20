# GeoRAG 后端 RAG / Agent 内核适配升级设计

> 日期：2026-09-20  
> 状态：代码实施与自动化验收已完成；真实 PostgreSQL + LLM + Frontend E2E 按用户要求暂跳过
> 目标仓库：`geo-rag-standard-assistant`  
> 能力来源参考：`rag_cy/rag`  

## 1. 背景

`geo-rag-standard-assistant` 已经具备相对完整的产品外壳和 GIS/数据资产能力，包括：

- FastAPI 主应用与 `/api/*` 公共接口；
- 管理员认证、访客 Demo 身份与额度控制；
- PostgreSQL、pgvector、PostGIS；
- MySQL 标准元数据；
- Redis 可选缓存；
- 文档上传、MinIO、解析、切块、向量化、重建索引等文档生命周期；
- 空间查询/省级 GeoJSON 等 GIS 能力；
- React 前端现有搜索、问答、地图联动契约。

但当前知识问答核心的职责边界不清晰。尤其 `SearchService` 同时承担数据库检索、精确标准号规则、关键词检索、向量检索、重排、意图判断、对话管理、历史截断、Prompt 构建、答案生成、SSE、地图动作解析等职责，导致：

1. 检索与生成耦合；
2. 语义决策散落在 API Route 与 Service 中；
3. 会话状态只是请求携带的短历史，不是真正的会话级 Runtime；
4. 缺少统一 Evidence 生命周期，生成答案与证据之间的契约较弱；
5. 模型阶段职责不清楚，难以独立控制 Controller、Answer Generator、Reviewer 的 reasoning 行为；
6. 地图动作依赖答案尾部 Markdown JSON，结构化契约不足；
7. 继续在现有 `SearchService` 上追加 Agent 功能会进一步扩大单体服务并制造双重语义权威。

因此，本次不是把 `rag_cy/rag` 整套复制进 GeoRAG，也不是替换整个后端，而是：

> **保留 GeoRAG 的产品外壳、数据资产、GIS 能力和稳定 API；抽取并适配 `rag_cy/rag` 中已经验证过的通用 RAG / Agent 架构能力，替换 GeoRAG 较弱的问答内核。**

---

## 2. 第一性原则目标

### 2.1 目标

最终系统应满足以下职责划分：

```text
用户 / 前端
   │
   ▼
GeoRAG API Contract
   │
   ├── Auth / Demo Quota
   ├── Document Lifecycle
   ├── Spatial / GIS
   └── Search / Chat API
           │
           ▼
Knowledge Application Core
   ├── Deterministic Search Pipeline
   └── Agent Runtime
           ├── Main Controller
           ├── Tool Runtime
           ├── Evidence Ledger
           ├── Answer Generator
           ├── Reviewer（显式开关，默认关闭）
           └── Context / Stage Policy / Observability
                   │
                   ▼
Retrieval Port
   │
   ▼
GeoRAG PostgreSQL / pgvector / metadata / spatial adapters
```

核心原则：

1. **产品契约与内部实现解耦。** 前端无需因为内核升级而整体重写。
2. **存储只有一个知识真源。** 保留 PostgreSQL/pgvector，不引入第二套 Chroma 主索引。
3. **Runtime 管事实和执行边界，不替 Main Controller 做语义裁决。**
4. **检索候选、工作证据、冻结证据、最终 Claim 分层。**
5. **生成必须基于冻结 Evidence；通用知识默认关闭。**
6. **Reviewer 只做 Claim ↔ Evidence 支撑审查，不重新解释用户意图。**
7. **图谱不属于本次目标。** 不复制、不注册、不保留“默认关闭但仍存在”的图谱残留。
8. **对旧行为的兼容只能存在于明确的边界层，不能污染新核心。**

### 2.2 非目标

本次不处理：

- 知识图谱、实体图遍历、GraphWorkingSet、图谱管理后台；
- 把 PostgreSQL/pgvector 迁移到 Chroma；
- 全量替换 GeoRAG 前端；
- 一次性重写全部 GIS 空间分析 TODO；
- 一次性取消 MySQL 标准元数据；
- 复制 `rag_cy/rag` 的博客、Vue 前端、目录扫描器；
- 为兼容旧实现长期维护两套 RAG/Agent 核心。

---

## 3. 已确认架构决策

### 3.1 存储：保留 PostgreSQL + pgvector

#### 选择

不引入 Chroma。`rag_cy/rag` 中与 Chroma 强绑定的 `VectorStore`、私有 `_retrieve_vector`、`get_chunks_by_metadata` 等实现不直接迁移。

#### 原因

- GeoRAG 已经以 PostgreSQL/pgvector/PostGIS 承担文档、向量、空间数据生命周期；
- 再引入 Chroma 会制造双索引同步、部署、回滚、孤儿数据和一致性问题；
- 本次真正需要迁移的是 Agent/Evidence/阶段职责，而不是具体向量数据库品牌。

#### 约束

所有 Agent 检索逻辑必须依赖公开 `RetrievalPort`，禁止依赖 pgvector SQL 细节或源项目 Chroma 私有方法。

### 3.2 生成模式

保留 `use_generation` 现有语义：

- `use_generation=false`：确定性搜索链路，不进入 Agent Loop；
- `use_generation=true`：默认进入 Agent 模式；
- Linear 模式保留为可选低成本/调试路径，但不作为默认生成模式。

这样可以保留“搜索”和“问答”两类产品行为，而不是所有请求都强制走 LLM Agent。

### 3.3 图谱完全排除

目标 Tool Registry 不注册：

- `expand_graph_scope`；
- 图谱实体审核工具；
- GraphWorkingSet / GraphBudget；
- graph extraction / graph governance / graph admin。

Controller Prompt、Context Projection、Runtime 状态和测试中也不得留下无效图谱字段作为长期兼容层。

### 3.4 通用知识默认关闭

GeoRAG 主要回答规划、测绘、GIS 标准与政策知识。知识型回答默认必须来自系统检索 Evidence。

允许的最终输出类型应至少区分：

- `knowledge_answer`：必须包含冻结证据；
- `clarification`：证据不足且需要用户补充；
- `limitation`：当前库无法支持结论；
- 产品元信息/纯交互性响应：仅在明确、窄范围的系统交互路径允许，不得伪装为知识回答。

禁止 Controller 以“direct answer”绕过知识证据与最终生成协议。

---

## 4. 保留 / 替换 / 适配矩阵

| 现有能力 | 决策 | 说明 |
|---|---|---|
| `Backend/main.py` 生命周期 | 保留 | 继续作为 GeoRAG 后端入口 |
| `/api/auth/*` | 保留 | 管理员、访客 JWT、Demo 配额均属于产品能力 |
| `/api/documents/*` | 保留并增强内部 | 文档 API 与生命周期保留，解析/切块内核可升级 |
| `/api/spatial/*` / PostGIS | 保留 | GIS 产品能力，不与 RAG 内核绑定 |
| PostgreSQL / pgvector | 保留 | 目标唯一向量/文档知识存储 |
| MySQL 标准元数据 | 第一阶段保留 | 暂不扩大迁移范围，后续单独评估归并 |
| MinIO / 索引任务生命周期 | 保留 | 继续承载上传与索引流程 |
| `SearchService` 数据访问原语 | 拆出复用 | 精确标准号、SQL keyword、metadata/spatial filter 等转为 Adapter |
| `SearchService` 意图/生成/编排 | 替换 | 由 Agent Runtime / Controller / Answer Generator 接管 |
| 当前硬编码 greeting / intent 分支 | 删除 | 不继续作为知识语义权威 |
| 当前 history 最近 6 条策略 | 替换 | 改为会话级 Context + token budget |
| Markdown JSON `adcode` | 过渡兼容 | 内部结构化 `MapAction`，第一阶段保留旧输出适配 |
| 当前 SSE Route | 适配 | 统一到新 Runtime 事件，不强制第一阶段前端改为流式 |
| `rag_cy/rag` Agent Runtime | 抽取适配 | 迁移职责和协议，不复制存储绑定 |
| Evidence Ledger / Frozen Snapshot | 迁移 | 成为答案证据契约核心 |
| Reviewer | 迁移 | 请求级显式开关，默认关闭 |
| LLM Stage Policy | 迁移 | Controller/Answer/Reviewer reasoning 分离 |
| Chroma / Graph / 博客 / Vue | 不迁移 | 与目标系统无关或产生双重基础设施 |

---

## 5. 目标模块边界

实施时优先沿现有 `Backend/app/services/` 组织，不把整个 `rag_knowledge` 包复制进来。最终精确目录可在实施计划中依据现有 import 关系微调，但职责必须保持如下边界。

### 5.1 Retrieval Port

定义存储无关的检索协议，例如：

```text
RetrievalQuery
  query_text
  top_k
  threshold
  search_mode
  metadata_filter
  spatial_filter
  focus / retrieval hints

RetrievalCandidate
  chunk_id
  document_id
  text
  title/source
  score
  metadata
  provenance
```

端口职责：

- 检索候选；
- 根据 ID 获取已有 chunk；
- 返回稳定 provenance；
- 不负责用户意图分类；
- 不负责答案生成；
- 不负责 Evidence 是否足以支持 Claim 的最终语义判断。

### 5.2 PostgreSQL Retrieval Adapter

Adapter 复用 GeoRAG 已有领域能力：

1. 标准号精确匹配；
2. PostgreSQL keyword / full-text 类能力；
3. pgvector semantic retrieval；
4. metadata filter；
5. spatial filter；
6. rerank；
7. 文档来源与可下载信息。

第一阶段不强行移植源项目内存 BM25。现有 SQL keyword + vector + rerank 已经形成稳定链路，应先把边界抽干净；只有离线评测证明召回质量不足，才增加 BM25，且仍通过同一 Retrieval Port 暴露。

### 5.3 Main Controller

Controller 是 Agent 模式的唯一语义规划者，负责：

- 理解用户当前问题；
- 判断需要检索、复用已有 Evidence、澄清还是生成；
- 决定每次工具调用的语义缺口；
- 基于工具 Observation 决定下一步。

Runtime 不预先把请求分类成固定知识意图状态机，也不以隐藏检索次数预算替代 Controller 决策。

### 5.4 Tool Runtime

第一阶段工具集：

- `retrieve_kb`：从 Retrieval Port 获取候选并写入 Working Evidence；
- `reuse_evidence`：读取同会话可访问的历史 Evidence；
- `compose_answer`：选择 Evidence 并冻结最终生成快照；
- `clarify`：显式结束为澄清。

工具 schema 只描述事实能力、结构约束和物理限制，不在描述中强行要求“某类问题必须调用某工具”。

### 5.5 Evidence Lifecycle

采用明确生命周期：

```text
Retrieval Candidates
      │
      ▼
Working Evidence
      │ Controller 选择
      ▼
Frozen Evidence Snapshot
      │
      ├── Answer Generator
      └── Reviewer（可选）
```

规则：

- 候选进入 Working Evidence 的准入应尽量是结构性/确定性的，不恢复逐 chunk Helper LLM 准入；
- 只有 Frozen Snapshot 可以用于本轮最终引用；
- 历史 Evidence 可以保留在会话中，但跨 scope 后不能自动继续作为当前引用；
- Reviewer 验证 Claim 是否被 Frozen Evidence 支撑，不重新决定检索意图。

### 5.6 Answer Generator

Answer Generator 只接收：

- 用户问题；
- 必要上下文；
- Frozen Evidence；
- 输出协议。

不重新调用检索，不决定是否应该查库，不从 Controller reasoning 中抢救答案。

### 5.7 Reviewer

Reviewer 为请求级显式能力：

- `reviewer_enabled=false` 默认关闭；
- 开启时位于 Answer Generator 之后、最终发布之前；
- 只验证 grounding、引用和 claim 支撑；
- 不成为第二个 Main Controller；
- 不使用通用知识填补 Evidence 缺口。

### 5.8 LLM Stage Policy

迁移源项目已经形成的阶段策略思想：

- Controller：可依据用户 thinking 与 endpoint capability 开 reasoning；
- Answer Generator：默认 reasoning OFF；
- Reviewer：默认 reasoning OFF；
- 结构化输出失败允许明确、有限、可观测的阶段级重试，但禁止从 `reasoning_content` 提取隐藏思考作为答案。

---

## 6. API 兼容设计

### 6.1 `/api/search/query`

保留当前公共端点与主要字段，避免前端整体重写。

现有字段继续生效：

- `query`
- `top_k`
- `threshold`
- `search_mode`
- `metadata_filter`
- `spatial_filter`
- `use_rerank`
- `use_generation`
- `history`
- `follow_up_context`

增加的字段全部为可选，保证旧客户端仍可调用：

- `session_id?: string`
- `mode?: "agent" | "linear"`
- `reviewer_enabled?: bool`，默认 `false`
- `thinking?: bool | compatible value`

默认规则：

- `use_generation=false` 时忽略 `mode`，走确定性搜索；
- `use_generation=true && mode 未传` 时使用 `agent`；
- `session_id` 未传时允许创建临时 session，但响应必须返回实际 session id；
- 前端正式接入后，应稳定发送自身 `conversation_id` 作为 `session_id`。

### 6.2 Response

现有字段保持兼容，同时逐步扩展：

- `session_id`
- `trace_id`
- `final_mode`
- `publication_state`
- `map_action?: structured object`

第一阶段仍可在 `generated_answer` 中保留旧 Markdown JSON `adcode/name` 兼容输出，但该逻辑只能存在于 Response Compatibility Adapter，不允许继续写进核心 Answer Prompt 作为长期协议。

---

## 7. 会话与上下文

当前前端已经维护本地 `conversation_id`，但没有发给后端。迁移后：

```text
frontend conversation_id
      │
      ▼
SearchRequest.session_id
      │
      ▼
Agent Runtime Session
      ├── history projection
      ├── evidence memory
      ├── turn/run events
      └── observability
```

### 规则

1. 后端 Session ID 是 Runtime 状态主键，而非仅用于日志展示；
2. 不再依赖“最近 6 条消息”作为主要历史策略；
3. Context Builder 按 token budget 投影必要历史；
4. Evidence Memory 与对话文本分开建模；
5. 请求传来的 `history` 在迁移期作为兼容输入，不与 Runtime session 形成两个长期事实源；
6. 当前端稳定传递 `session_id` 后，应逐步收缩客户端全量 history 回传职责。

---

## 8. 地图动作兼容与演进

当前答案通过 Markdown JSON：

```json
{"adcode": "...", "name": "..."}
```

驱动前端地图。这种设计把 UI action 混入自然语言文本。

目标内部协议改为：

```text
MapAction
  type
  target
  adcode
  name
  optional payload
```

迁移分两步：

1. 新核心产生结构化 `map_action`；Response Adapter 同时生成旧 Markdown JSON，保证现有前端不立即断裂；
2. 前端改为直接读取 `map_action` 后，删除答案文本 JSON 解析与兼容输出。

地图动作属于应用动作协议，不属于 Evidence 本身。模型若从文档证据推导行政区，应仍满足知识证据规则。

---

## 9. 文档摄取链路

保留当前文档生命周期：

```text
Upload / Presigned URL
  → MinIO
  → parsing
  → chunking
  → embedding
  → document_chunks / pgvector
  → indexed / failed
```

适配源项目中更强的解析/结构保留能力，包括：

- 文档结构感知切块；
- 表格/代码块边界保护；
- Word 字段清洗；
- Excel → Markdown 表达；
- 更明确的解析 fallback。

但这些能力必须作为 GeoRAG `DocumentIndexingService` 内部组件接入，最终仍写入现有 PostgreSQL 文档/Chunk 生命周期。不得引入第二套目录扫描式主摄取流程。

---

## 10. 错误处理与资源保险丝

### 10.1 语义失败与资源失败分离

明确区分：

- `NO_EVIDENCE` / `INSUFFICIENT_EVIDENCE`
- `CLARIFICATION_REQUIRED`
- `MODEL_OUTPUT_INVALID`
- `RETRIEVAL_UNAVAILABLE`
- `RESOURCE_FUSE`
- 基础设施连接错误

资源保险丝只防止无限循环或资源失控，例如 Controller 最大物理步数、工具超时，不得通过“最多检索两次”之类业务门禁提前替 Controller 决策。

### 10.2 降级

- pgvector 不可用：不能假装语义检索成功；根据请求允许 keyword/exact 检索时显式降级并记录；
- LLM 不可用：`use_generation=false` 的纯搜索仍应可用；生成请求返回明确错误/降级，不伪造答案；
- Reviewer 失败：当 Reviewer 显式开启时，不得静默当作通过；应返回可观察的 review failure 状态。

---

## 11. 依赖与配置策略

禁止把两个项目的 `requirements` 直接合并。

迁移原则：

1. 以 GeoRAG Python `>=3.12` 为目标运行时；
2. 仅引入目标能力实际需要的依赖；
3. 优先抽取纯 Python 协议与 Runtime 代码，减少 LangChain/Chroma 传染性依赖；
4. 任何 FastAPI/Pydantic/httpx/OpenAI SDK 升级都必须独立验证 API contract 和现有测试；
5. 配置只保留目标后端实际使用的模型、Agent、Reviewer、Context、资源保险丝字段；
6. 不复制 graph 配置或 Chroma 配置作为“暂时不用”的死配置。

---

## 12. 迁移阶段

### Phase 0：基线与隔离

- 创建独立 Git worktree；
- 建立正确 Python 3.12 项目环境；
- 冻结当前 OpenAPI 与关键接口契约；
- 跑通现有 `Backend/tests` 基线；
- 记录无法通过的既有测试，不把环境问题误判为代码问题。

### Phase 1：Retrieval Boundary

- 定义 `RetrievalPort` 与 neutral contracts；
- 从 `SearchService` 抽离 PostgreSQL/pgvector/metadata/spatial/exact-standard retrieval；
- 保证原纯搜索行为和测试不退化；
- 此阶段不引入 Agent。

### Phase 2：Agent / Evidence Core

- 适配 Main Controller；
- Tool Runtime：`retrieve_kb/reuse_evidence/compose_answer/clarify`；
- Evidence Working Set / Ledger / Frozen Snapshot；
- Answer Generator；
- Stage Policy；
- Reviewer 显式开关默认 OFF。

### Phase 3：API 与 Session 接线

- `/api/search/query` 适配到新核心；
- 新增可选 `session_id/mode/reviewer_enabled/thinking`；
- 前端传递 `conversation_id -> session_id`；
- 兼容旧 `history`；
- 添加 trace/session response metadata。

### Phase 4：文档解析升级

- 将结构化 parser/chunker 适配进现有 DocumentIndexingService；
- 保持 MinIO → PostgreSQL/pgvector 生命周期；
- 验证历史文档、重建索引、失败重试。

### Phase 5：MapAction 与 Streaming

- 增加结构化 `map_action`；
- 保留旧 Markdown JSON Compatibility Adapter；
- 将 SSE 接入 Runtime 事件流；
- 前端正式消费结构化 map action 后删除旧文本解析。

### Phase 6：旧核心退场

- 删除 `SearchService` 中已被替代的意图判断/LLM 生成/对话管理/历史策略；
- 删除重复 `detect_intent`、旧 Prompt、旧地图 JSON 生成逻辑；
- 删除无引用配置、辅助函数和旧测试桩；
- 确认不存在两套 Agent/RAG 核心并行。

---

## 13. 测试与验收

### 13.1 单元/契约测试

必须覆盖：

- Retrieval Port contract；
- PostgreSQL adapter exact/keyword/vector/filter/rerank；
- Tool schema 与输入校验；
- Evidence 生命周期；
- Frozen Snapshot 不可被生成阶段修改；
- Reviewer OFF/ON；
- Controller/Answer/Reviewer Stage Policy；
- session/history projection；
- structured map action compatibility；
- 文档 parser/chunker/index lifecycle；
- OpenAPI 向后兼容。

### 13.2 架构守卫测试

增加明确守卫，防止未来回退：

- Agent Runtime 不 import Chroma；
- 目标 Registry 不出现 graph tool；
- Answer Generator 不调用 retrieval；
- Runtime 不持有 intent classifier 权威；
- `use_generation=false` 不触发 Agent/LLM；
- Reviewer default 为 OFF；
- knowledge answer 无 Evidence 时不能正常发布。

### 13.3 集成测试

至少覆盖：

1. 精确标准号查询；
2. 普通语义搜索；
3. metadata filter；
4. spatial filter；
5. 上传文档后可检索；
6. 多轮 session 的 Evidence reuse；
7. Evidence 不足返回 limitation/clarification；
8. Reviewer OFF 正常回答；
9. Reviewer ON 的通过/拒绝；
10. MapAction 兼容现有前端。

### 13.4 真实 E2E

最终验收不能只停留在 pytest。

需要使用真实配置验证：

```text
Frontend
  → FastAPI
  → Auth / Demo quota
  → Agent Runtime
  → PostgreSQL / pgvector
  → real LLM endpoint
  → Answer / Evidence / MapAction
  → Frontend render / map state
```

同时验证：

- 真实 session 多轮；
- 模型 reasoning 配置；
- 上传新文档后的问答；
- 服务重启后的数据一致性；
- 旧搜索功能未被 Agent 改造破坏。

---

## 14. 成功标准

只有同时满足以下条件，才能认为本次“后端适配升级”完成：

1. GeoRAG 现有 Auth、Demo、Document、Spatial、Search 主要契约继续工作；
2. PostgreSQL/pgvector 是唯一正式知识索引，不存在 Chroma 双写；
3. 生成请求默认进入新的 Agent Runtime；
4. 纯搜索不依赖 LLM；
5. Main Controller 是 Agent 语义规划唯一权威；
6. Evidence 从 Working → Frozen → Answer/Review 的链路可追踪；
7. Reviewer 可显式开关且默认 OFF；
8. 知识回答默认不使用模型通用知识补空；
9. Runtime/工具层没有图谱残留；
10. 前端有稳定 session；
11. 地图动作具备结构化协议且旧前端迁移期不破坏；
12. 老 `SearchService` 已完成职责收缩，没有两套并行编排；
13. 正确 Python 3.12 环境下测试通过；
14. 真实模型 + PostgreSQL + 前端 E2E 通过；
15. 最终做全局 residue audit，不留下废弃代码、死配置、重复 Prompt 和无效兼容分支。

---

## 15. 设计结论

本次迁移的核心不是“把一个 RAG 项目塞进另一个 RAG 项目”，而是重新建立清晰边界：

```text
GeoRAG 决定：产品、API、GIS、数据资产生命周期

Agent Core 决定：语义规划、工具执行、证据生命周期、答案发布

Retrieval Adapter 决定：如何从 GeoRAG PostgreSQL/pgvector 取得候选事实
```

这样既保留 GeoRAG 已经有价值的产品能力，也避免把 `rag_cy/rag` 的 Chroma、图谱和其他项目特定历史包袱一起迁入。后续实现应围绕这个职责图执行，而不是按文件一一复制。
