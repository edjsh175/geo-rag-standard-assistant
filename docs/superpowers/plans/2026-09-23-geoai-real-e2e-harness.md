# GeoAI Real E2E Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 36 条 GeoAI 评测清单升级为可通过真实浏览器、真实 Agent Runtime 和真实 Browser GIS Continuation 执行、断言和留档的 E2E 验收系统。

**Architecture:** 保留现有 Agent / GIS 业务链路不变。新增 Manifest 执行契约、Playwright 浏览器 Harness、通用 Assertion Engine 和证据级 Result 文件；根目录 runner 只编排 preflight、Playwright 与 evaluator。

**Tech Stack:** Python 3.12、TypeScript、Playwright、React/Vite、FastAPI、OpenLayers、pytest/Vitest。

**Spec:** `docs/superpowers/specs/2026-09-23-geoai-real-e2e-harness-design.md`

## Global Constraints

- Browser 是 WebGIS 实时状态权威源，GIS E2E 不得降级成 API-only。
- Harness 不创建第二套 Agent Runtime 或 Browser GIS Runtime。
- `completed=true` 必须来自 required assertions 全部通过。
- 失败任务必须留档，禁止 skip 伪装通过。
- 不修改 Agent 语义规划规则来迎合评测。
- 不把测试专用 fixture 混入生产知识库或默认空间数据。

---

### Task 1: Evaluation Manifest Contract

**Files:**
- Modify: `evals/geoai_agent_36_tasks.json`
- Create: `scripts/geoai_eval_contract.py`
- Modify: `Backend/tests/test_geoai_agent_eval_contract.py`

**Interfaces:**
- Produces: `load_manifest(path) -> list[EvalTask]`
- Produces: `validate_manifest(tasks) -> None`
- Manifest task fields: `id/category/scenario/depends_on/prompt/required_capabilities/success_criteria/assertions`.

- [ ] **Step 1: Write failing tests for scenario, dependency and assertion validation**
- [ ] **Step 2: Run targeted pytest and confirm RED**
- [ ] **Step 3: Implement minimal manifest contract loader/validator**
- [ ] **Step 4: Update 36 tasks with scenario/dependency/assertion metadata**
- [ ] **Step 5: Run targeted pytest and confirm GREEN**

### Task 2: Evidence-grade Result Contract

**Files:**
- Modify: `scripts/evaluate_geoai_agent_results.py`
- Modify: `Backend/tests/test_geoai_agent_eval_contract.py`

**Interfaces:**
- Consumes result rows with `id/completed/assertions`.
- `completed` must equal `all(required assertion passed)`.

- [ ] **Step 1: Add failing tests proving bare `completed=true` is rejected**
- [ ] **Step 2: Run targeted pytest and confirm RED**
- [ ] **Step 3: Implement result evidence validation**
- [ ] **Step 4: Keep per-category aggregation behavior**
- [ ] **Step 5: Run targeted pytest and confirm GREEN**

### Task 3: Deterministic GIS Fixtures

**Files:**
- Create: `evals/fixtures/sample_polygons.geojson`
- Create: `evals/fixtures/sample_points.geojson`
- Create: `evals/fixtures/README.md`

**Interfaces:**
- Fixtures use EPSG:4326 and stable human-readable properties.

- [ ] **Step 1: Add fixture existence/schema test to evaluation contract tests**
- [ ] **Step 2: Run test and confirm RED**
- [ ] **Step 3: Add minimal deterministic GeoJSON fixtures**
- [ ] **Step 4: Run test and confirm GREEN**

### Task 4: Playwright Harness Foundation

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/geoaiHarness.ts`
- Create: `frontend/e2e/geoai-agent.spec.ts`

**Interfaces:**
- `runTask(page, task, context) -> ExecutedTaskResult`
- Observer captures `/api/search/query` request/response payloads.
- Result contains `assertions/tool_calls/receipts/final_answer/artifacts`.

- [ ] **Step 1: Install `@playwright/test` as dev dependency**
- [ ] **Step 2: Add failing unit-style tests for assertion evaluation where feasible**
- [ ] **Step 3: Implement browser/network observer without bypassing `chatService`**
- [ ] **Step 4: Implement UI prompt submission and completion wait**
- [ ] **Step 5: Save screenshot and Playwright trace on each task**
- [ ] **Step 6: Run Playwright test in a deliberately unavailable environment and verify explicit failure**

### Task 5: Scenario / Dependency Executor

**Files:**
- Modify: `frontend/e2e/geoaiHarness.ts`
- Modify: `frontend/e2e/geoai-agent.spec.ts`

**Interfaces:**
- One Browser Context per scenario.
- Dependencies execute before dependents.
- Dependency failure still emits result row for dependent task.

- [ ] **Step 1: Write failing tests for topological ordering and dependency failure propagation**
- [ ] **Step 2: Implement deterministic scenario grouping/order**
- [ ] **Step 3: Implement dependency failure result generation**
- [ ] **Step 4: Verify all 36 IDs yield exactly one result row**

### Task 6: Root E2E Runner

**Files:**
- Create: `scripts/run_geoai_agent_e2e.py`
- Create: `Backend/tests/test_geoai_agent_e2e_runner.py`

**Interfaces:**
- CLI: `python scripts/run_geoai_agent_e2e.py`
- Runs preflight → Playwright → evaluator.
- Exits nonzero if environment fails, Playwright fails, result file incomplete, or completion rate < 1.0.

- [ ] **Step 1: Write failing runner orchestration tests with injected subprocess runner**
- [ ] **Step 2: Implement minimal orchestration**
- [ ] **Step 3: Verify nonzero exit on blockers and incomplete results**
- [ ] **Step 4: Verify success path with synthetic evidence-grade result fixture**

### Task 7: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `scripts/preflight_geoai_agent_e2e.py` only if needed for Playwright-specific checks.

**Interfaces:**
- README distinguishes “36-task suite exists” from “latest real run result”.

- [ ] **Step 1: Replace ambiguous `36/36` wording with evidence-based status wording until a real run exists**
- [ ] **Step 2: Document `npm run e2e:geoai` and root runner**
- [ ] **Step 3: Run targeted backend tests**
- [ ] **Step 4: Run `npm run test:gis`**
- [ ] **Step 5: Run `npm run lint`**
- [ ] **Step 6: Run `npm run build`**
- [ ] **Step 7: Run preflight and record remaining external blockers**
- [ ] **Step 8: Inspect final diff for test-only bypasses or duplicated runtime ownership**
