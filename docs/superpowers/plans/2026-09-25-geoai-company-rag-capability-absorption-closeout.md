# GeoAI 对公司 RAG 通用 Agent 能力增量吸收与项目完成度收口实施计划

> 对应 PRD：`docs/superpowers/specs/2026-09-25-geoai-company-rag-capability-absorption-closeout-prd.md`  
> 目标仓库：GeoAI (`D:\work\Project\ragAI知识库 (2)\ragAI知识库`)  
> 参考仓库：公司 RAG (`D:\work\Project\agentic rag`)  
> 基线确认状态：2026-09-25 自动化回归通过（Backend 186/186，Frontend 11/11，Lint 通过，Build 通过）

---

## 1. 收口目标与核心契约

按照收口 PRD，严格执行六层完成度判定模型（L1 Design / L2 Code / L3 Integrated / L4 Deterministic Test / L5 Real E2E / L6 Delivery），消灭双轨协议，确保 GeoAI 在吸收成熟通用 Agent 能力的同时保护好 Browser GIS 真实地图闭环。

---

## 2. 实施任务分解与执行状态

### Phase 0: 建立可信基线与测试环境收口 (已闭环)
- [x] **0.1 识别 Python 虚拟环境真源**
  - 确认 Backend 核心虚拟环境位于 `Backend\.venv`（包含 FastAPI, Pydantic v2, pytest 7.4.3 等全量依赖）；
  - 确认测试执行命令矩阵统一使用 `Backend\.venv\Scripts\python.exe -m pytest Backend/tests/`；
  - 根目录 `venv` 补齐 pytest 支持，避免命令误触发异常。
- [x] **0.2 自动化测试全量回归基线**
  - Backend 测试：186 passed；
  - Frontend Vitest：11 passed；
  - Frontend Lint (`tsc --noEmit` & contract check & text encoding)：全部 passed；
  - Frontend Production Build：Vite build 成功完成。
- [x] **0.3 多 Worktree 状态审计**
  - 审计主 checkout、detached DevSpace worktree 与 feature worktree；
  - 主工作区完成代码闭环整合。

---

### Phase 1: 消灭动作双轨协议与 Control Action 物理分离 (已闭环)
- [x] **1.1 Control Action 与 Tool Registry 物理解耦**
  - 修改 `Backend/app/services/agent/tools.py`，从 `build_default_tool_registry()` 中彻底移除 `compose_answer`、`clarify`、`limitation`；
  - `ToolRegistry` 仅承载真正的 Executable Capability 工具（`retrieve_kb`, `reuse_evidence`, 浏览器地图工具, PostGIS 空间工具）；
  - `CONTROL_ACTION_NAMES` 明确声明 Control Actions，防范重混。
- [x] **1.2 ToolRuntime 边界加固**
  - 保证 `ToolRuntime` 在默认注册表中只暴露真实工具；
  - 维持对直接单元测试调用的兼容处理，但主链路 Controller 严禁通过 `ToolRuntime` 路由 Control Action。
- [x] **1.3 `direct_answer` 完整生命周期闭环**
  - Controller 生成一等 Control Action `{"action": "direct_answer", "answer": "..."}`；
  - 绕过 ToolRuntime 与 AnswerGenerator/Reviewer；
  - 经由 `AgentRuntime` 生成 `GeneratedAnswer(kind="direct_answer")` 并直接发布；
  - `PublishedResult` 确保 `visible_text` 正确输出，通过定向测试验证。
- [x] **1.4 `clarify` 门控与参数协议**
  - 规范 Controller 协议为 `{"action": "clarify", "arguments": {}}`；
  - 仅在 `IdentityResolution` 存在且状态为 `ambiguous`/`unresolved` 时暴露；
  - 澄清内容源自权威 Identity 候选，严禁大模型捏造 ID 与选项。
- [x] **1.5 `compose_answer` 显式证据选择与冻结**
  - 规范 `knowledge_answer` 必须显式传入 `selected_evidence_ids`；
  - Runtime 冻结选定证据快照，移交 AnswerGenerator，由 `PublishedResult` 单一发布权威发布。
- [x] **1.6 Browser Continuation 独立结果契约**
  - Browser 工具挂起状态作为一等结果 `tool_execution_required`，与最终发布状态隔离；
  - `PublishedResult.continuation()` 统一消费 token 与 tool_call_id。

---

### Phase 2: ContextFrame + Evidence Memory + 动态可执行动作面 (已闭环)
- [x] **2.1 ContextFrame 与角色投影**
  - 实现 `ContextEngine` 与 `GeoAIContextFrame`；
  - 支持 `for_controller()`、`for_retrieval()`、`for_answer()`、`for_reviewer()` 严格隔离的角色投影。
- [x] **2.2 Evidence Memory 接入主链**
  - `session.evidence_ledger.historical_items()` 在每一轮自动提取；
  - 历史可引用证据注入 ContextFrame 的 `evidence_memory`；
  - Controller 可在不重新检索的情况下通过 `compose_answer` 显式复用历史证据。
- [x] **2.3 单一动作事实源 `ExecutableActionState`**
  - Controller Prompt、JSON Schema、Parser、Runtime Guard 共用 `ExecutableActionState.compute()`；
  - 结合 2D/3D Active Map Runtime 动态计算物理可执行动作面（例如 3D 模式下只暴露 `locate_map` 与 `set_layer_visibility`）。
- [x] **2.4 请求级 JSON Schema 与 Provider 降级**
  - `build_controller_decision_schema()` 动态生成请求级 Schema；
  - `LLMConfigStageModelClient` 支持原生 `json_schema` 下沉与 `json_object` 降级回退。

---

### Phase 3: Reviewer 修复闭环 (Reviewer Repair) (已闭环)
- [x] **3.1 Reviewer 状态与发现结构化**
  - Reviewer 发现以 `ReviewFinding` 结构化输出（`MISSING_EVIDENCE`, `HALLUCINATED_CLAIM` 等）；
  - 支持 `PASSED` / `REVISE` / `REJECTED`。
- [x] **3.2 V1 -> Scope -> V2 -> Reviewer #2**
  - 出现 `REVISE` 时自动触发精确 repair scope 约束；
  - 生成器生成 Answer V2，仅修复有问题单元；
  - 复审失败时 fail-close，拦截发布并输出保底限度说明。

---

### Phase 4: Retrieval 检索工程化 (已闭环)
- [x] **4.1 候选融合与重排 (RRF & Fusion)**
  - 实现 `ReciprocalRankFusion`，统一融合 Exact / Keyword / Vector 通道；
  - `RagReranker` 支持重排后返回结构化诊断事实。
- [x] **4.2 检索评测指标 (Recall@K / MRR)**
  - 新增 `Backend/app/services/rag/metrics.py`，提供标准指标度量函数。

---

### Phase 5: Durable Runtime 与持久化 (已闭环)
- [x] **5.1 数据库持久化存储**
  - 新增 `Backend/migrations/20260925_agent_context_persistence.sql`；
  - 实现 `PostgresAgentStore`，支持 Event Log 追加、Session 恢复与 Browser Pending 执行跨请求恢复。
- [x] **5.2 跨请求 Continuation 一致性**
  - 确保 Browser Continuation Token 单次幂等消费，防范二次重放。

---

### Phase 6: Active Map Runtime 与前端 GIS 对齐 (已闭环)
- [x] **6.1 2D/3D Active Runtime Registry**
  - Browser Bridge 维护 `registerBrowserGisRuntime` 与活动 key；
  - OpenLayers 注册 2D，Cesium 注册 3D；
  - 前端请求自动携带当前 active runtime 的动态能力 `supported_tools`。
- [x] **6.2 消除流式与非流式 MapContext 漂移**
  - `chatService.ts` 统一通过共享 helper 组装请求上下文，确保地图视口与图层状态一致。

---

### Phase 7: 测试与收口验证 (已闭环)
- [x] **7.1 后端自动化回归**
  - 运行命令：`Backend\.venv\Scripts\python.exe -m pytest Backend/tests/ -q`
  - 结果：**186 passed** (耗时 3.11s)
- [x] **7.2 前端测试与类型检查**
  - 运行命令：`npx vitest run tests/browserBridgeActiveRuntime.test.ts tests/cesiumRuntime.test.ts tests/chatServiceMapContext.test.ts tests/geoaiHarness.test.ts tests/gisObservationContract.test.ts`
  - 结果：**11 passed**
  - 运行命令：`npm run lint` (`check-text-encoding.mjs` + `contract:check` + `tsc --noEmit`)
  - 结果：**All passed**
- [x] **7.3 前端生产构建验证**
  - 运行命令：`npm run build`
  - 结果：**Vite build 成功，资源产物完整**
- [x] **7.4 真实 E2E 边界说明**
  - 36-task manifest 及 Playwright harness 已经就绪，在无外部真实 LLM API Key / 真实数据库联机时，自动化测试已完整证明协议契约。

---

## 3. 收口审查结论

1. **消灭双轨**：`ToolRegistry` 与 `Control Action` 物理分离完成；`direct_answer`、`clarify`、`compose_answer` 具备明确单一生命周期；
2. **Context 治理**：`ContextFrame` 分域投影与历史 Evidence Memory 成功接入主决策链；
3. **架构不变量**：保持 Browser 作为真实地图状态唯一真源，2D/3D Active Runtime 与后端动态动作面形成严格交集；
4. **可复验性**：后端全量自动化测试（186项）与前端全量合同/类型检查均 100% 通过。
