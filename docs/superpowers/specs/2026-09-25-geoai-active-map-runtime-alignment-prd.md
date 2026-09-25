# GeoAI Active Map Runtime 前后端能力对齐增量 PRD

## 1. 背景

当前 GeoAI 已具备完整的 Browser GIS continuation 主链路：

`Controller -> browser tool -> frontend executor -> BrowserToolReceipt -> Agent continuation`

OpenLayers 2D 已实现以下浏览器工具：

- `import_vector_dataset`
- `set_layer_visibility`
- `set_vector_style`
- `fit_vector_layer`
- `locate_map`
- `inspect_layer_features`
- `get_feature_geometry`

但当前产品同时存在 OpenLayers 2D 与 Cesium 3D，默认视图为 3D，而 Browser GIS Runtime 只由 OpenLayers 注册。由此产生三个已确认的契约缺口：

1. 用户处于 3D 时，Agent 读取和操作的仍可能是隐藏的 2D Runtime；
2. 后端 Controller 始终看到全部浏览器工具，即使当前活动地图并不支持；
3. `set_layer_visibility` 的后端语义是“稳定 `layer_ref` 的图层显隐”，但 2D 前端实现只支持 Agent 导入的 user-vector layer。

此外，流式聊天首轮请求未携带当前 `map_context`，与非流式链路存在行为漂移。

本 PRD 是增量收口，不重写现有 Agent Runtime、Evidence、Receipt、OpenLayers user-vector 能力或 RAG 链路。

---

## 2. 第一性原则

### 2.1 当前可见地图才是地图状态真源

系统不能因为 OpenLayers Runtime 已经存在，就把隐藏的 2D 地图当作 3D 用户当前操作对象。

必须满足：

> `getBrowserMapContext()` 与 `executeBrowserTool()` 永远指向当前活动地图 Runtime。

2D/3D 组件各自拥有内部实现，但 Browser Bridge 只暴露一个“当前活动 Runtime”。

### 2.2 动作面描述的是“现在能执行什么”，不是“系统理论上有什么工具”

Controller 可见的浏览器工具必须来自活动 `map_context.supported_tools`。

因此：

- 2D 以现有 7 个工具为能力上限，但只暴露当前状态真正可执行的子集；
- 3D 只暴露当前真实实现的工具；
- 当前 Runtime 不支持的工具不允许进入 Controller Prompt；
- 当前 Runtime `ready != true` 时不暴露任何 Browser Tool；
- 即使模型绕过 Prompt 输出不支持动作，Runtime Guard 仍必须确定性拒绝。

不能通过“让模型自己记住 3D 不支持某工具”解决物理能力约束。

### 2.3 不为“表面功能对齐”复制第二套 GIS 系统

本阶段不在 Cesium 中重新实现完整的 SHP/GeoJSON 导入、feature_ref、vector style、feature inspection。

原因：

- 这些能力当前已经由 OpenLayers 完整拥有；
- 直接复制会产生双份对象生命周期、样式语义和 feature identity；
- 需求本质是“后端只调用活动地图真实能力”，而不是“两个引擎立即功能数量一致”。

3D 本阶段只实现其真实且低成本的原生能力：

- `locate_map`
- `set_layer_visibility`（针对 Cesium 当前产品逻辑图层）

后续若需要 3D user-vector parity，应单独立项，共享数据对象层，而不是复制 OpenLayers 实现。

### 2.4 契约只定义一次，并在多个边界复用

浏览器工具集合必须有一个共享常量，供以下边界复用：

- Controller 动态动作面；
- ToolRuntime 执行 Guard；
- Runtime 从 `map_context` 派生当前可执行工具。

不得在 Controller、Runtime、ToolRuntime 各维护一份独立字符串列表。

---

## 3. 目标

### 3.1 Active Map Runtime

Browser Bridge 从单一全局 `runtime` 改为：

- Runtime Registry：按 `2d` / `3d` 注册；
- Active Runtime Key：由当前 `viewMode` 设置；
- `getBrowserMapContext()`：只读取 active runtime；
- `executeBrowserTool()`：只执行 active runtime。

若 active runtime 未注册或 action 不在 active runtime 的 `supported_tools` 中，前端必须 fail-close。

### 3.2 2D OpenLayers 对齐

保持现有 user-vector 能力不变。

`supported_tools` 必须从当前 MapContext 事实动态生成：

- `locate_map`：地图 ready 后可用；
- `set_layer_visibility`：存在稳定地图图层时可用；
- `import_vector_dataset`：仅 `available_files` 非空时可用；
- `set_vector_style` / `fit_vector_layer` / `inspect_layer_features`：仅存在 user layer 时可用；
- `get_feature_geometry`：仅存在可发现 `feature_ref` 时可用。

因此“OpenLayers 实现过某个工具”不等于“当前这一刻必须向 Controller 暴露该工具”。

修正 `set_layer_visibility`：

- 支持 `MapContext.layer_tree` 中任意稳定 `layer_ref`；
- 递归查找 LayerGroup 子节点；
- user-vector layer 继续使用同一稳定 `layer_ref`；
- 未知 `layer_ref` 返回明确 `UNKNOWN_LAYER`，不静默成功。

### 3.3 3D Cesium Runtime

新增轻量 Cesium Runtime Adapter，复用现有 Browser Bridge 契约。

3D `MapContext`：

- `dimension = "3d"`；
- viewport 使用 WGS84 center，并将相机高度转换为与现有 API 一致的 zoom 表达；
- layer tree 只表达产品逻辑图层，不暴露主题实现内部的重复 imagery layer；
- `supported_tools = ["locate_map", "set_layer_visibility"]`。

逻辑图层至少包括：

- `system:provinces`
- `base:vector`
- `base:satellite`

`set_layer_visibility` 必须更新 App 已有 `layers` 状态，由现有 Cesium effect 负责真正改变场景，不新建第二份 visibility state。

### 3.4 后端动态动作面

新增确定性“可执行工具集合”派生：

```text
所有非 Browser Tool
    +
当前 map_context.supported_tools ∩ 已注册 Browser Tool
```

规则：

- 没有 `map_context` 时不暴露 Browser Tool；
- `supported_tools` 中未知名称忽略；
- 非 Browser Tool（RAG、compose、clarify、PostGIS 等）不受地图状态影响；
- MainController Prompt 只渲染当前 allowed tools；
- MainController structured parse 只接受 allowed tools；
- ToolRuntime 再次使用同一 allowed set 做执行 Guard。

这保证“模型看到的动作”和“Runtime 真能执行的动作”一致。

### 3.5 流式 / 非流式请求统一

提取共享的“附加 Active MapContext”逻辑，供：

- `sendMessage()`
- `sendMessageStream()`

共同使用。

不得继续由两个请求分支分别手写 `map_context`，避免再次漂移。

---

## 4. 非目标

本阶段明确不做：

1. Cesium 中完整复刻 OpenLayers user-vector import/style/feature-ref 能力；
2. 修改 RAG Evidence / Answer Generator / Reviewer 架构；
3. 引入新的 GIS 框架或状态管理库；
4. 改写 2D/3D 视角交接机制；
5. 改变 PostGIS spatial tools；
6. 为 UI 增加 Reviewer / Thinking 开关。

这些内容与本次“活动地图物理能力契约对齐”不是同一问题。

---

## 5. 数据与调用流

### 5.1 首轮请求

```text
viewMode
  -> BrowserBridge.activeRuntime
  -> activeRuntime.snapshot()
  -> SearchRequest.map_context
  -> AgentRuntime derives allowed tool names
  -> MainController sees only executable actions
```

### 5.2 Browser Tool

```text
Controller tool call
  -> ToolRuntime allowed-tool guard
  -> map_action
  -> BrowserBridge active-runtime guard
  -> active runtime execute
  -> BrowserToolReceipt + new active map_context
  -> continuation
```

### 5.3 视图切换

```text
2D -> 3D
  -> existing view-state handoff
  -> setViewMode("3D")
  -> BrowserBridge active key = "3d"

3D -> 2D
  -> existing view-state handoff
  -> setViewMode("2D")
  -> BrowserBridge active key = "2d"
```

不销毁非活动引擎，只改变 Agent 的权威 Runtime 指向。

---

## 6. 代码复用要求

必须复用：

- `BrowserToolReceipt` 现有结构；
- `BrowserMapAction`；
- `browserBridge` continuation 链路；
- `useMapStore` 中已有 `zoomToHeight` / `heightToZoom`；
- App 已有 `layers` 状态；
- OpenLayers `MapContext` 与 user-vector capability；
- 后端 `ToolRegistry` / `ToolRuntime`。

禁止：

- 为 3D 新建第二套请求协议；
- 为 3D 新建第二套 Agent Tool 名称；
- 再维护一份浏览器 Tool 名称列表；
- 通过字符串 Prompt 约定代替 Runtime Guard。

---

## 7. 验收标准

### P0 契约正确性

1. 默认 3D 模式下 `getBrowserMapContext().dimension === "3d"`；
2. 切换 2D 后立即读取 2D context，不再读取隐藏 3D；
3. 3D Controller 动作面不包含 `import_vector_dataset` / `set_vector_style` 等未实现工具；
4. 2D Controller 动作面不超过现有 7 个 Browser Tool，并随 `available_files / user_layers / feature_refs` 动态收缩；
5. 模型输出一个不在当前 allowed set 的 Browser Tool 时，确定性拒绝；
6. Browser Bridge 收到 active runtime 未声明的 action 时，确定性拒绝；
7. active runtime 未 ready 时，前后端两侧都禁止 Browser Tool 执行；
8. 2D `set_layer_visibility("base:satellite", ...)` 可真实改变对应 OpenLayers layer；
9. 3D `locate_map` 与逻辑图层显隐通过同一 Receipt continuation 返回。
10. 2D 空状态不暴露 `import_vector_dataset / set_vector_style / inspect_layer_features / get_feature_geometry` 等当前不可执行动作；

### P1 一致性

11. 流式和非流式首轮都携带 active `map_context`；
12. `BrowserMapContext.dimension` 类型支持 `2d | 3d`；
13. 现有 file_ref/layer_ref/feature_ref 生命周期测试不回归；
14. 前端 TypeScript、contract check、GIS 定向测试通过。

### 验证口径

“代码实现”与“真实 E2E”必须分开记录。

本 PRD 完成代码与定向测试后，只能声明“契约层完成”；若没有实际启动 Backend + Frontend + LLM + Browser 跑场景，不得声明真实 GeoAI E2E 已完成。

---

## 8. 风险与后续

### 风险 1：3D 功能少于 2D

这是当前真实能力差异，不是契约错误。正确行为是动态隐藏不可执行工具，而不是伪造 parity。

### 风险 2：Cesium 产品逻辑图层与物理 ImageryLayer 不一一对应

Runtime 暴露产品逻辑层，不暴露 light/dark 内部双缓存实现，避免 Agent 操作主题实现细节。

### 后续阶段

若产品要求“3D 也能导入/改样式/按 feature_ref 查询”，应设计共享 Vector Dataset Domain State，让 OpenLayers 与 Cesium 都投影同一份对象事实，再分别渲染；不应复制两套独立对象生命周期。

