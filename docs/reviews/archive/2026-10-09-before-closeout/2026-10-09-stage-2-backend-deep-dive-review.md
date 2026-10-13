# 阶段二：后端 Agent Runtime 与领域服务深度审查报告

> 审查基线时间：2026-10-09  
> 执行规范依据：[AI 辅助软件工程统一执行规范](../AI_ENGINEERING_STANDARDS.md)  
> 上阶段基线：[阶段一：全局架构与项目认知审查结论报告](./2026-10-09-stage-1-system-baseline-review.md)

---

## 1. 整体审查进度概览

| 阶段 | 审查主题 | 状态 | 核心交付物 / 目标 |
| :--- | :--- | :--- | :--- |
| **阶段一** | **全局架构与项目认知审查 (System Baseline)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-1-system-baseline-review.md`](./2026-10-09-stage-1-system-baseline-review.md) |
| **阶段二** | **后端 Agent Runtime 与领域服务审查 (Backend Deep-Dive)** | **已完成 (COMPLETED)** | 本文档：Runtime 循环剖析、LangGraph 封装度、OCC 并发、PostGIS/GeoSQL、God Class 识别 |
| **阶段三** | **前端架构与 WebGIS Runtime 审查 (Frontend Deep-Dive)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-3-frontend-deep-dive-review.md`](./2026-10-09-stage-3-frontend-deep-dive-review.md) |
| **阶段四** | **跨端契约、协议与安全防御审查 (Contracts & Security)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-4-contracts-and-security-review.md`](./2026-10-09-stage-4-contracts-and-security-review.md) |
| **阶段五** | **工程质量、测试套件与基线验证 (Harness & Evals)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-5-engineering-harness-and-evals-review.md`](./2026-10-09-stage-5-engineering-harness-and-evals-review.md) |
| **阶段六** | **多视角收敛对账与改进路线图 (Convergence & Roadmap)** | **已完成 (COMPLETED)** | [`2026-10-09-stage-6-convergence-and-roadmap-review.md`](./2026-10-09-stage-6-convergence-and-roadmap-review.md) |

---

## 2. Agent Runtime 编排与 LangGraph 封装深度审查

### 2.1 AgentRuntime.run 循环架构与闭包膨胀

- **物理位置**：[`Backend/app/services/agent/runtime.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/runtime.py)
- **实现剖析**：
  - `AgentRuntime.run` 方法长度达到 **930+ 行**（第 404 行至第 1337 行）。
  - 方法体内定义了超过 12 个嵌套异步闭包函数（包括 `persist_turn_event`、`resource_fuse_result`、`model_output_failure_result`、`planning_project_context`、`planning_decide`、`planning_execute_tool`、`planning_handle_control`、`planning_finalize_terminal` 等）。
  - 这些闭包捕获了包含 `session`、`turn_events`、`event_listener`、`snapshot`、`fuse`、`reviewer_enabled`、`thinking` 等在内的 30 多个局部变量，并使用 `nonlocal` 进行跨闭包状态修改。
- **正向工程设计**：
  - 团队已逐步提炼出 `orchestration/` 子目录下的独立协调器（如 [`AnswerPublicationPipeline`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/orchestration/answer_publication.py)、[`ReviewerPipeline`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/orchestration/reviewer_pipeline.py)、[`ToolExecutionCoordinator`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/orchestration/tool_execution.py)、[`TurnLifecycleCoordinator`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/orchestration/turn_lifecycle.py)）。
- **严重代码气味 (Code Smell)**：
  - 外层 `AgentRuntime.run` 仍承担了“粘合剂”角色，未能将整套执行状态机封装为独立类或状态对象，单方法复杂度过高，调试和单元测试难以针对中间状态切片单独注入。

### 2.2 LangGraph 封装度与“空心化状态机”反模式

- **物理位置**：
  - [`Backend/app/services/agent/graph/planning.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/graph/planning.py)
  - [`Backend/app/services/agent/graph/state.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/graph/state.py)
- **结构现状**：
  ```mermaid
  flowchart TD
      subgraph LangGraph["LangGraph StateGraph 编排外壳"]
          START((START)) --> N1["project_context"]
          N1 --> N2["plan"]
          N2 --> N3{"route_after_plan"}
          N3 -- "tool_call" --> N4["execute_tool"]
          N3 -- "control" --> N5["handle_control"]
          N4 --> N1
          N5 --> N1
          N3 -- "terminal" --> N6["finalize_terminal"]
          N6 --> END((END))
      end

      subgraph Closures["AgentRuntime.run 内部局部闭包"]
          C1["planning_project_context()"]
          C2["planning_decide()"]
          C3["planning_execute_tool()"]
          C4["planning_handle_control()"]
          C5["planning_finalize_terminal()"]
      end

      N1 -.->|回调| C1
      N2 -.->|回调| C2
      N4 -.->|回调| C3
      N5 -.->|回调| C4
      N6 -.->|回调| C5
  ```
- **审查发现与诊断**：
  1. **状态空心化**：LangGraph 的 `AgentGraphState`（仅 41 行）只记录了几个标识符字符串（`decision_kind`、`tool_name` 等），实际的领域状态、证据、会话与观测结果完全存放在外部局部变量中。
  2. **反向回调绑定**：LangGraph 内部各个 Node 仅仅是直接调用了 `PlanningGraphContext` 中注入的 Python 回调（例如 `await runtime.context.execute_tool(...)`）。
  3. **违背最小充分机制原则**：系统虽然引入了重量级框架 `langgraph`，但完全没有使用其内建的 Checkpointer 持久化、跨节点恢复、分支回溯或事件流能力；LangGraph 在此仅充当了一个控制流循环驱动器。
  4. **架构建议**：未来演进有两种可选路径：
     - *路径 A（极简充分）*：如果状态持久化完全由自研 `PostgresAgentStore` 与事件流保障，则可以直接使用精炼的 Python FSM 循环替换 LangGraph，剔除重依赖；
     - *路径 B（深度拥抱）*：若保留 LangGraph，必须将状态机与 Checkpointer 正式解耦，避免将闭包句柄作为 `context` 强行绑定在单个进程调用栈中。

---

## 3. 并发控制与持久化真源（Store & OCC）审查

### 3.1 God Class 识别：`PostgresAgentStore`

- **物理位置**：[`Backend/app/services/agent/store.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/store.py) (76KB, 1937 行)
- **职责聚集情况**：
  - 承载 `AgentStore` 抽象接口（第 145 行至 319 行）
  - 承载 `InMemoryAgentStore` 测试桩实现（第 320 行至 711 行）
  - 承载 `PostgresAgentStore` 生产实现（第 712 行至 1937 行，超 1200 行）
  - 内部混合了 8 张核心数据库表的大量 Raw SQL 文本拼装：
    - `geoai_agent_sessions`
    - `geoai_agent_events`
    - `geoai_agent_evidence`
    - `geoai_agent_evidence_activations`
    - `geoai_context_snapshots`
    - `geoai_model_input_audits`
    - `geoai_conversation_memory_states`
    - `geoai_pending_browser_executions`
  - 负责自定义对象的多态 JSON 序列化/反序列化（`ToolObservation`、`SpatialFilter`、`MetadataFilter`）。
- **审查结论**：属于典型的 **God Class / God Module**。建议拆分为独立仓储：`SessionRepository`、`EventRepository`、`EvidenceRepository`、`AuditRepository`。

### 3.2 悲观锁 vs. 乐观锁 (OCC) 的混合并发机制对账

系统在不同场景根据写入烈度与一致性要求采用了分层并发保护机制：

| 领域对象 | 并发控制模式 | 实现位置与 SQL 特征 | 正确性与安全评估 |
| :--- | :--- | :--- | :--- |
| **轮次分配 (Turn Allocation)** | **悲观行级排他锁** | `store.py:1014`<br>`SELECT next_turn_number ... FOR UPDATE` | **高可靠**。保证在同一会话下并发提问时，轮次序号 `next_turn_number` 严格单调递增，无竞争空洞。 |
| **会话记忆 (Conversation Memory)** | **乐观并发控制 (OCC)** | `store.py:1637`<br>`ON CONFLICT (principal_id, session_id, summary_version) DO NOTHING`<br>`RETURNING memory_id` | **安全闭环**。版本号严格逐次递增；若发生版本冲突，主动抛出 `RuntimeError("conversation memory version conflict")`。 |
| **浏览器任务续接 (Pending Execution)** | **原子 CAS 抢占** | `store.py:1898`<br>`UPDATE ... SET status = 'resumed' WHERE status = 'awaiting_browser' RETURNING token` | **高可靠**。单一 Winner 机制，防止前端重复上报或网络重试导致同一个浏览器 Tool Receipt 被重复消费执行。 |
| **事件流 (Agent Events)** | **严格递增单调序列** | `geoai_agent_events`<br>事务内按 `sequence` 校验与追加 | **安全**。保障 SSE 事件序列化无乱序、无重复。 |

---

## 4. 空间能力与 GeoSQL 领域服务审查

### 4.1 GeoSQL V1 安全解析与编译执行引擎

- **物理位置**：[`Backend/app/services/geosql/`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/geosql/)
- **审查结论**：**极高水准的安全防御与深度设计**，完全符合规范中关于“防御性架构”的要求：
  1. **AST 白名单限制**：[`validator.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/geosql/validator.py) 强制校验目标表名（目前仅开放 `spatial_regions`）、可查列（`selectable_columns`）与可过滤列（`filterable_columns`），未知列立即拒绝。
  2. **完全参数化编译**：[`compiler.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/geosql/compiler.py) 将所有过滤值抽离为 `:f_0`, `:spatial_geometry`, `:distance_m` 等绑定参数，彻底绝缘 SQL 注入。
  3. **沙箱式只读执行**：[`executor.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/geosql/executor.py) 强制在事务开始前执行 `SET TRANSACTION READ ONLY`，并设置局部毫秒级超时 `statement_timeout`（默认 3000ms）。
  4. **拓扑防爆与简化**：对返回几何体自动包裹 `ST_SimplifyPreserveTopology(geometry, 0.001)`，且对几何字段强制施加 20 条上限，保护前端渲染与后端传输性能。

### 4.2 SpatialService 空间拓扑与测地计算

- **物理位置**：[`Backend/app/services/spatial_service.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/spatial_service.py)
- **审查发现**：
  - **优势**：
    - `validate_geojson_geometry` 函数严格执行 RFC 7946 契约检验：大小上限 256KB、坐标经纬度边界、递归深度限制（<=3）、Polygon 闭合校验与 WGS84 坐标系断言。
    - 空间拓扑关系（`query_relation`）和几何叠加（`overlay`）严格由 PostGIS `ST_Intersects`、`ST_Within`、`ST_Intersection` 等原生函数执行。
    - 测地缓冲区 `create_buffer` 采用真实的 `ST_Buffer(...::geography, distance)`，而非简单的欧式平面近似。
  - **缺陷与代码异味**：
    1. **原生 PostGIS 能力闲置**：`calculate_distance` 方法在 Python 应用层使用手动编写的 Haversine 球面公式（`atan2`, `cos`, `sin`）计算距离，未复用数据库中的 `ST_Distance(geography, geography)`。
    2. **未实现空桩存留**：`geocode`、`reverse_geocode`、`spatial_query` 直接抛出 `NotImplementedError`。若未来不打算自建 Geocoding 服务，应清理未使用的协议接口，或明确标注第三方代理策略。

---

## 5. Controller 规划器与 Prompt 工程审查

### 5.1 Prompt 过拟合与评测 Benchmark 硬编码倾向

- **物理位置**：[`Backend/app/services/agent/controller.py`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/controller.py)（第 201 行至第 225 行）
- **发现事实**：
  在 MainController 的系统 Prompt 中，包含了高度硬编码的中文提示词分支，直接对应测试集用例：
  - *"当用户要求'尝试'导入、读取或定位时，必须先发起 tool_call..."*
  - *"对于重复读取，当用户未指定次数时，获取恰好两次当前轮次的成功读取..."*
  - *"对于空间要素区域分析（'判断要素几何是否位于指定行政区'）：若几何未读取，先调 get_feature_geometry；随后调用 query_spatial_relation，right=成都市..."*
- **风险评估**：
  - **过度针对评测集适配 (Overfitting to Benchmark)**：Controller 规划逻辑中出现了具体的城市名字（“成都市”）以及特定的固定多步流水线模式。
  - **泛化能力受损**：当外部用户换一种自然语言提问或者查询“武汉市”时，Prompt 中的“成都市”示例可能对模型产生负面注意偏置。
  - **改进建议**：将这类针对业务流程的具体指引，迁移为 Controller 的工具使用规范（Tool Spec 的 `use_when` / `avoid_when` 字段）或动态 Few-Shot 机制，从核心通用 Prompt 中解耦。

---

## 6. 证据闭环与生成审查管道（Answer & Reviewer）

### 6.1 审查闭环机制有效性

- **核心链路**：
  $$\text{Working Evidence} \xrightarrow{\text{freeze}} \text{FrozenEvidenceSnapshot} \xrightarrow{\text{generate}} \text{GeneratedAnswer (Units + Citations)} \xrightarrow{\text{review}} \text{ReviewerPipeline}$$
- **审查通过事实**：
  1. [`AnswerGenerator`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/answer_generator.py) 强制要求非空 `FrozenEvidenceSnapshot`，严禁在无证据支持时生成知识型回答。
  2. 生成的答案以 `AnswerUnit` 为最小事实颗粒度，每条 Unit 必须反向绑定 `citation_id`。
  3. [`ReviewerPipeline`](file:///d:/work/Project/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93%20(2)/ragAI%E7%9F%A5%E8%AF%86%E5%BA%93/Backend/app/services/agent/orchestration/reviewer_pipeline.py) 实现严格的**单次受限修复**（At most one constrained repair）：
     - 若 Reviewer 裁定为驳回且修复失败，系统将状态置为 `grounding_rejected`，发布预置的安全局限说明（`SafeLimitation`），绝不向客户端下发未经审计的幻觉文本。

---

## 7. 阶段二技术债汇总与风险评级

| 编号 | 技术债 / 架构问题描述 | 影响模块 | 严重程度 | 建议处理阶段 |
| :---: | :--- | :--- | :---: | :---: |
| **B-01** | `AgentRuntime.run` 超长单体方法（930+ 行），存在十余个庞大嵌套闭包 | `runtime.py` | **P1 (高)** | 阶段六重构规划 |
| **B-02** | LangGraph 封装度空心化，仅作为外部循环调用局部闭包，双轨复杂度冗余 | `graph/planning.py` | **P2 (中)** | 阶段六评估精简 |
| **B-03** | `PostgresAgentStore` (1937 行) 承担过多职责，Raw SQL 混杂与多表仓储集中 | `store.py` | **P1 (高)** | 阶段六拆分计划 |
| **B-04** | Controller 系统 Prompt 存在硬编码测试集特征短语（如特定成都市用例） | `controller.py` | **P2 (中)** | 提示词通用化优化 |
| **B-05** | `calculate_distance` 使用 Python 手写 Haversine，未复用 PostGIS `ST_Distance` | `spatial_service.py` | **P3 (低)** | 迁移至 PostGIS |
| **B-06** | Pydantic V1 遗留废弃语法（`BaseSettings`, `@validator`, `min_items`）引发大量运行时警告 | `config.py`, `spatial_models.py` | **P2 (中)** | 统一升级至 V2 规范 |

---

## 8. 阶段二验证执行记录

- **后端测试套件验证**：
  - 测试命令：`.\.venv\Scripts\pytest.exe tests/test_agent_langgraph_planning.py tests/test_geosql_v1.py tests/test_spatial_agent_service.py tests/test_agent_store.py tests/test_agent_runtime.py`
  - 运行结果：**71 项测试全数通过 (71 passed, 5 warnings in 4.42s)**。
  - 验证表明：虽然存在代码结构层面的膨胀与封装气味，但当前系统的业务逻辑契约、空间计算与状态机闭环在功能层面保持高度一致与稳定。
