# GeoAI Real E2E Harness Design

## 1. 背景

当前仓库已经具备：

- 36 条 GeoAI 评测任务清单：`evals/geoai_agent_36_tasks.json`
- 环境预检：`scripts/preflight_geoai_agent_e2e.py`
- 结果聚合：`scripts/evaluate_geoai_agent_results.py`

但目前缺少真正执行这些任务的中间层。现有评测链路只能回答“任务定义是否完整”“一个结果文件里有多少条 `completed=true`”，不能证明任务真的经过了：

```text
Web UI
→ Backend Agent Runtime
→ Browser Tool Continuation
→ Browser Bridge
→ Frontend Executor
→ OpenLayers
→ Tool Receipt / MapContext
→ Backend Resume
→ PostGIS / RAG
→ Published Answer
```

因此 README 中的 `36/36` 只能作为完成态验收标准，不能作为已经发生的执行证据。

## 2. 目标

新增一个真实、可重复、可机器判定、可留档的 GeoAI E2E Harness，使每条评测结果都能回答：

1. 实际执行了什么任务；
2. 经过了哪些真实 Agent / Browser GIS / PostGIS 路径；
3. 为什么判定为通过或失败；
4. 可以通过哪些 Trace、Receipt、Screenshot 或 Playwright Trace 复核。

## 3. 非目标

本轮不做：

- 重构 Agent Runtime；
- 新增 GIS 业务工具；
- 重写 RAG；
- 引入第二套 Browser GIS 状态机；
- 通过 Mock Browser Tool 伪造 E2E；
- 为得到 `36/36` 修改判定规则或跳过失败任务。

## 4. 第一性原则

### 4.1 E2E 必须验证真实权威源

WebGIS 实时状态的权威源是浏览器中的真实 OpenLayers Runtime。因此 GIS 相关任务必须进入真实浏览器，API-only 不能算完整 E2E。

### 4.2 成功由事实判定，不由回答措辞判定

例如“把图层边线改红色”不能因为模型回答“已修改”就判通过。应检查真实工具调用、成功 Receipt、对应 `layer_ref` 以及最新 MapContext/状态。

### 4.3 评测执行与业务 Runtime 分离

Harness 负责驱动、收集和断言；业务 Runtime 仍由现有代码负责执行。Harness 不拥有第二套 Agent Loop，也不直接修改 OpenLayers 对象绕开 Browser Bridge。

### 4.4 每个通过结论必须可追溯

`completed=true` 必须来自具体断言集合，而不是人工随手填写布尔值。

## 5. 体系结构

```text
Evaluation Manifest
      │
      ▼
Scenario Planner
      │
      ▼
Playwright Browser
      │
      ├─ UI input / file chooser
      ├─ network observation
      ├─ screenshots
      └─ Playwright trace
      │
      ▼
Existing React App
      │
      ▼
chatService.runAgentRequest()
      │
      ▼
Backend Agent Runtime
      │
      ├─ RAG / Evidence
      ├─ PostGIS
      └─ Browser Tool Continuation
                    │
                    ▼
        Browser Bridge / OpenLayers
                    │
                    ▼
        Receipt + latest MapContext
                    │
                    └───────────────→ Backend Resume

Execution Observer
      │
      ▼
Machine Assertions
      │
      ▼
Evidence-grade Result JSON
      │
      ▼
evaluate_geoai_agent_results.py
```

## 6. Manifest 契约

36 条任务仍以 `evals/geoai_agent_36_tasks.json` 为唯一评测清单，但增加执行语义：

- `scenario`: 共享浏览器与 Session 的场景名；
- `depends_on`: 同场景前置任务 ID；
- `fixture`: 所需测试数据；
- `assertions`: 机器断言定义。

示例：

```json
{
  "id": "L03",
  "category": "layer_control",
  "scenario": "vector_layer_lifecycle",
  "depends_on": ["I01"],
  "prompt": "把图层边线改成红色。",
  "assertions": [
    {"type": "tool_called", "tool": "set_vector_style"},
    {"type": "tool_receipt_success", "tool": "set_vector_style"},
    {"type": "published_answer_present"}
  ]
}
```

`success_criteria` 保留给人阅读，但最终 pass/fail 只由 `assertions` 计算。

## 7. 场景与状态

36 条任务不是 36 个完全独立请求。以下任务天然依赖上一轮状态：

- Follow-up Evidence：K03 依赖知识检索场景；
- Layer lifecycle：I01 → I03 → L01/L02/L03/L04/L05；
- Feature observation：F01 → F02/F03/F04；
- Cross-tool recovery：R04 需要知识检索和真实 GIS 工具共同完成。

Harness 按 `scenario` 创建 Browser Context。一个场景内共享：

- 页面；
- Agent Session；
- Browser GIS Runtime；
- 稳定 `file_ref / layer_ref / feature_ref`；
- 已产生的运行事实。

不同场景之间必须隔离，避免状态污染。

## 8. 测试数据

在 `evals/fixtures/` 放置最小、可确定的数据：

- `sample_polygons.geojson`
- `sample_points.geojson`
- `sample_shapefile/`（SHP/DBF/SHX）

Fixture 只服务 E2E，不进入产品默认数据源。

## 9. 观测策略

Harness 不读取 React 内部 state，不直接访问 OpenLayers JS 对象做旁路验证。

主要证据来源：

1. `/api/search/query` 请求/响应；
2. Browser Tool continuation 响应中的 `trace_id / pending_tool_call_id / continuation_token / map_action`；
3. continuation 请求中的 `browser_tool_receipt / map_context`；
4. 最终 Published Response；
5. 页面截图与 Playwright Trace。

必要时可在现有 Browser Bridge 上增加只读测试观测接口，但不得改变业务控制流。

## 10. Result 契约

每条任务产出：

```json
{
  "id": "L03",
  "completed": true,
  "scenario": "vector_layer_lifecycle",
  "session_id": "...",
  "trace_ids": ["..."],
  "started_at": "...",
  "duration_ms": 1234,
  "assertions": [
    {"type": "tool_called", "passed": true, "evidence": {...}}
  ],
  "tool_calls": [],
  "receipts": [],
  "final_answer": "...",
  "failure_reason": null,
  "artifacts": {
    "screenshot": "...",
    "playwright_trace": "..."
  }
}
```

`completed` 必须严格等于全部 required assertions 的 AND 结果。

## 11. 断言类型

第一阶段实现以下通用断言：

- `published_answer_present`
- `publication_state`
- `tool_called`
- `tool_receipt_success`
- `tool_receipt_failure`
- `map_context_present`
- `stable_layer_ref`
- `stable_feature_ref`
- `response_has_citations`
- `response_contains_limit`
- `no_false_success_after_failure`

空间关系、几何类型、样式字段等断言基于实际 response / receipt payload 做结构化比较，不基于模型自然语言模糊匹配。

## 12. Playwright 边界

新增 `@playwright/test` 作为开发依赖。

Playwright 负责：

- 打开真实前端；
- 输入用户指令；
- 选择本地 Fixture 文件；
- 等待真实 Agent 完成；
- 监听 `/api/search/query` 网络流量；
- 保存 screenshot/trace；
- 把观测事实交给 Assertion Engine。

Playwright 不直接调用 Backend 内部 Python 对象，不直接写 Runtime Session。

## 13. 运行入口

提供：

```bash
npm run e2e:geoai
```

以及根目录：

```bash
python scripts/preflight_geoai_agent_e2e.py
python scripts/run_geoai_agent_e2e.py
python scripts/evaluate_geoai_agent_results.py evals/results/latest/results.json
```

Python runner 负责：

- 运行 preflight；
- 启动 Playwright suite；
- 确认结果文件完整；
- 调用 evaluator；
- 返回非零退出码表示未达到 36/36。

## 14. 失败语义

以下情况都必须产生明确失败记录，而不是跳过：

- 环境未就绪；
- 页面未加载；
- Agent 超时；
- Browser Tool contract 不完整；
- Receipt 失败但任务要求成功；
- 前置任务失败；
- Assertion 未通过；
- 结果文件缺任务；
- 同一个 task 重复结果。

如果前置任务失败，依赖任务标记为 `completed=false`，`failure_reason=dependency_failed:<id>`，保证总账仍有恰好 36 条结果。

## 15. 验收标准

代码级验收：

1. Manifest 可被确定性校验；
2. Harness 能按 scenario / dependency 顺序执行；
3. 至少一条真实 Browser GIS 任务能通过真实前端完成并生成 Receipt 证据；
4. 失败任务能够生成完整失败记录；
5. evaluator 拒绝无 assertion evidence 的伪结果；
6. Frontend lint/build 与现有 GIS Contract Test 不回归；
7. E2E 环境不可用时明确报告 blocker，不伪造 `36/36`。

项目完成态验收：

```text
36 / 36 tasks completed
Completion Rate: 100%
```

只有真实结果文件满足上述条件时，README 才能把 `36/36` 表述为已执行结果。
