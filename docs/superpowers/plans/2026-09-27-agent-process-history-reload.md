# Agent Process 历史恢复实施计划

**Goal:** 实施既有 observability requirement 的刷新恢复增量，以服务端持久化事件还原当前会话的 Process。

**Architecture:** localStorage 仅保存按认证身份隔离的 session ID。刷新后先获取会话消息及 turn 引用；管理员读取 S-06 turn/trace 详情，访客使用授权 session detail 内的事件。历史事件补齐 envelope、排序、去重，再复用 AgentEventProjector；恢复不执行 Browser GIS。

**Tech Stack:** React 19、TypeScript、生成的 OpenAPI contractClient、Vitest。

## Task 1：契约与恢复服务

- [x] 运行 `npm run api:generate`，将现有 session/turn/trace 路由纳入生成契约。
- [x] 在 `frontend/tests/agentHistory.test.ts` 写失败用例：多个 turn 严格配对，乱序/重复事件，管理员 S-06 读取，访客不调用管理员接口，404/网络失败。
- [x] 运行 `npx vitest run tests/agentHistory.test.ts` 记录失败，再实现 `frontend/src/services/agentHistory.ts`。
- [x] 补齐历史 citations，以服务端 message 为最终回答事实源，未发布 turn 仅附过程。
- [x] 将 `frontend/src/services/chatService.ts` 历史接口改为调用统一契约；支持取消请求。

## Task 2：刷新生命周期

- [x] `frontend/src/App.tsx` 按身份读取保存的 session ID，认证初始化后恢复。
- [x] 首次 SSE event 获得 session_id 即持久化，result 后再次确认。
- [x] 恢复期间禁止发送，失败保留 ID 并显示重试，404 清理 ID；清理 effect 防止过期请求覆盖消息。
- [x] 不由历史 map_action 触发 GIS，不向 storage 保存消息或 trace 内容。

## Task 3：历史展示一致性

- [x] 在 `frontend/tests/agentEventProjector.test.ts` 添加首事件时间、取消 turn、取消 browser tool 的失败测试。
- [x] 修复 `frontend/src/components/agent/eventProjector.ts` 与 types，取消事件不再显示永久 running。
- [x] 验证 `AgentProcess.tsx` 与 `Chat.tsx` 的错误历史默认展开行为。

## Task 4：验证及记录

- [x] 跑新增测试与现有 projector / chatService / authority tests。
- [x] 跑 `npm run lint` 和 `npm run build`，将既有失败与本次失败区分。
- [x] 独立审查恢复权限、请求竞态、跨 turn 身份隔离。
- [x] 更新专项 requirement 的本次实施记录；不改动用户正在修改的 Master Ledger。

用户已明确授权开始实施，使用当前 checkout。保留已有 Backend/document concurrency 和 Master Ledger 未提交改动。本次不提交、推送或部署。

验证记录：前端单元测试 29 项及 4 个页面脚本通过，lint/build 通过，模拟 API 的真实浏览器刷新回归 1 项通过，访客认证测试 4 项通过。审查 P1（首轮停止/断流覆盖真实 ID）已修复，复核无新增 P1/P2。未运行真实 LLM/GIS 全链路。
