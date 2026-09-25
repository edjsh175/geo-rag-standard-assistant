# GeoAI Active Map Runtime Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 GeoAI 后端只暴露并执行当前活动 2D/3D 地图真实支持的 Browser GIS 能力，同时修复 2D 图层显隐和流式 MapContext 漂移。

**Architecture:** Browser Bridge 维护 2D/3D Runtime Registry 与唯一 active key；OpenLayers 保留完整 7-tool runtime，Cesium 新增只暴露真实能力的轻量 adapter。后端从 active `map_context.supported_tools` 派生单一 allowed-tool set，并复用于 Controller schema/parse 与 ToolRuntime guard。

**Tech Stack:** React 19, TypeScript, OpenLayers 10, Cesium 1.140, Vitest, FastAPI, Pydantic, pytest

---

### Task 1: 冻结 Active Runtime 与动态动作面契约

**Files:**
- Modify: `frontend/tests/gisObservationContract.test.ts`
- Create: `frontend/tests/browserBridgeActiveRuntime.test.ts`
- Modify: `Backend/tests/test_agent_controller.py`
- Modify: `Backend/tests/test_agent_tool_runtime.py`

- [ ] **Step 1: 写前端失败测试**
  - 断言 2D/3D runtime 可同时注册；
  - active key 决定 `getBrowserMapContext()`；
  - action 只分发给 active runtime；
  - active runtime 未声明的 tool fail-close；
  - OpenLayers 非 user-vector 稳定 layer_ref 可被 `set_layer_visibility` 修改。

- [ ] **Step 2: 运行前端测试并确认 RED**

Run:

```bash
cd frontend
npx vitest run tests/browserBridgeActiveRuntime.test.ts tests/gisObservationContract.test.ts
```

Expected: 新增 Active Runtime API / system-layer visibility 行为尚不存在而失败。

- [ ] **Step 3: 写后端失败测试**
  - Controller 只渲染传入 allowed tool names；
  - structured output 选择 disallowed browser tool 时拒绝；
  - ToolRuntime 对 disallowed tool 二次拒绝。

- [ ] **Step 4: 运行后端定向测试并确认 RED**

Run:

```bash
python -m pytest Backend/tests/test_agent_controller.py Backend/tests/test_agent_tool_runtime.py -q
```

Expected: 动态 action surface 参数/guard 尚不存在而失败。

### Task 2: 实现前端 Active Map Runtime

**Files:**
- Modify: `frontend/src/gis/contracts.ts`
- Modify: `frontend/src/gis/browserBridge.ts`
- Modify: `frontend/src/gis/frontendExecutor.ts`
- Modify: `frontend/src/gis/mapContext.ts`
- Modify: `frontend/src/components/OpenLayersMap.tsx`
- Create: `frontend/src/gis/cesiumRuntime.ts`
- Modify: `frontend/src/components/CesiumGlobe.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 扩展共享 BrowserMapContext**
  - `dimension: '2d' | '3d'`；
  - 不新增第二套 Receipt/Action 类型。

- [ ] **Step 2: Browser Bridge 改为 Registry + Active Key**
  - `registerBrowserGisRuntime(kind, runtime)`；
  - `setActiveBrowserGisRuntime(kind)`；
  - snapshot/execute 永远读取 active runtime；
  - execute 前校验 `snapshot().supported_tools`。

- [ ] **Step 3: 修复 OpenLayers layer visibility**
  - 递归查找当前 map layer tree 的 `gisLayerRef` / `gisUserLayerRef`；
  - `set_layer_visibility` 支持所有稳定图层引用；
  - 未知引用抛 `UNKNOWN_LAYER`。

- [ ] **Step 3a: 让 2D supported_tools 由当前对象事实生成**
  - 无 `available_files` 时隐藏 import；
  - 无 user layer 时隐藏 style/fit/inspect；
  - 无可发现 `feature_ref` 时隐藏 geometry read；
  - `locate_map` 与稳定图层显隐保留为基础地图能力。

- [ ] **Step 4: 新增 Cesium Runtime Adapter**
  - snapshot 输出 `dimension='3d'`、viewport、逻辑 layer tree；
  - 仅声明 `locate_map`、`set_layer_visibility`；
  - locate 复用 `zoomToHeight`；
  - visibility 通过 App 已有 layers state callback 改变产品状态。

- [ ] **Step 5: App 绑定 active viewMode**
  - OpenLayers 注册为 `2d`；
  - Cesium 注册为 `3d`；
  - `viewMode` 变化时设置 active key。

- [ ] **Step 6: 运行前端 RED 测试至 GREEN**

Run:

```bash
cd frontend
npx vitest run tests/browserBridgeActiveRuntime.test.ts tests/gisObservationContract.test.ts
```

Expected: PASS。

### Task 3: 实现后端共享动态可执行动作面

**Files:**
- Modify: `Backend/app/services/agent/tools.py`
- Modify: `Backend/app/services/agent/controller.py`
- Modify: `Backend/app/services/agent/tool_runtime.py`
- Modify: `Backend/app/services/agent/runtime.py`

- [ ] **Step 1: 在 tools.py 定义唯一 Browser Tool 集合**
  - 从默认 ToolRegistry 已有名称复用；
  - Controller/Runtime 不再各自手写浏览器工具集合。

- [ ] **Step 2: Runtime 从 map_context 派生 allowed set**
  - 非 Browser Tool 永远保留；
  - Browser Tool = `supported_tools ∩ registered browser tools`；
  - 无 map_context 时 Browser Tool 集为空。

- [ ] **Step 3: MainController 使用 allowed set**
  - Prompt 只渲染 allowed specs；
  - parse 同样拒绝 disallowed name。

- [ ] **Step 4: ToolRuntime 使用相同 allowed set**
  - 执行前确定性校验；
  - 违规动作抛 `ToolExecutionError`。

- [ ] **Step 5: 运行后端定向测试至 GREEN**

Run:

```bash
python -m pytest Backend/tests/test_agent_controller.py Backend/tests/test_agent_tool_runtime.py Backend/tests/test_agent_runtime.py -q
```

Expected: PASS。

### Task 4: 消除 stream/non-stream MapContext 漂移

**Files:**
- Modify: `frontend/src/services/chatService.ts`
- Create or modify: `frontend/tests/chatServiceMapContext.test.ts`

- [ ] **Step 1: 写失败测试**
  - 首轮非流式与流式 request builder 都必须携带同一 active map context。

- [ ] **Step 2: 运行并确认 RED**

Run:

```bash
cd frontend
npx vitest run tests/chatServiceMapContext.test.ts
```

- [ ] **Step 3: 提取共享 request-context helper**
  - 两条链路共同调用；
  - 不复制 `getBrowserMapContext()` 拼装逻辑。

- [ ] **Step 4: 运行至 GREEN**

### Task 5: 回归与收口审查

**Files:**
- Review all files changed by Tasks 1-4.

- [ ] **Step 1: 前端合同、类型与 GIS 测试**

```bash
cd frontend
npm run contract:check
npm run lint
npm run test:gis
npx vitest run tests/browserBridgeActiveRuntime.test.ts tests/chatServiceMapContext.test.ts
npm run build
```

- [ ] **Step 2: 后端 Agent 定向回归**

```bash
python -m pytest Backend/tests/test_agent_controller.py Backend/tests/test_agent_tool_runtime.py Backend/tests/test_agent_runtime.py Backend/tests/test_search_agent_api.py -q
```

- [ ] **Step 3: Git/diff 审查**
  - 不修改 RAG/Reviewer/Answer Generator 语义；
  - 不引入新的前端 GIS 状态源；
  - Browser Tool 名称没有重复定义；
  - 只声明实际执行过的测试结果。

- [ ] **Step 4: 记录真实验证边界**
  - 若未跑 Backend + Frontend + LLM + Browser 真 E2E，明确标注“真实 E2E 未验证”。

