# Agent 全流程可观测实施计划

**Goal:** 按既有 observability requirement 补齐真实 Runtime 事件 → 流式 Projector → DisclosureRow/ToolRow/AgentProcess → 历史回放的完整链路。

**Architecture:** 初始请求和 Browser Receipt 续接均复用 `/api/search/query/stream` 及同一 Runtime。工具输入由 ToolRuntime canonicalization 提供，输出和 Reviewer/Receipt 仅投影有限公开事实；前端只配对和展示，不决定执行或发布。会话历史复用上一轮的服务端重载能力。

**Tech Stack:** Python/FastAPI、React 19/TypeScript、Vitest、Playwright。

## Task 1：后端事件事实与安全边界（后端 worker）

- [ ] 在 `Backend/tests/test_agent_stream_events.py` 及专项测试中先验证 canonical arguments、safe result summary、receipt 同 ID、Reviewer on/off/异常/修复复审、唯一 publication；记录 red。
- [ ] 在 `Backend/app/services/agent/tool_runtime.py` 提供 prepare/canonicalize 入口，Runtime 将同一 canonical call 发到 UI 并执行。
- [ ] `Backend/app/services/agent/runtime.py` 补齐有限 tool arguments/results/errors、browser receipt、真实 Reviewer start/completed。
- [ ] `Backend/app/api/search_routes.py` 保留 SSE endpoint，补 event_id/sequence，并限制公开事件；审计数据继续保存在服务端。
- [ ] 修正 `session_service.py` 的最终正文恢复：publication 缺正文时使用真正的 assistant_message，不能用空文本覆盖。
- [ ] 运行后端事件、Runtime、Reviewer、ToolRuntime 与 session 恢复相关测试。

## Task 2：投影与统一展示（前端 worker）

- [ ] 在 `frontend/tests/agentEventProjector.test.ts` 写重复、乱序、多 Turn、Reviewer、Browser failure 和 terminal 稳定性的 red 用例。
- [ ] `frontend/src/components/agent/eventProjector.ts` 按 ID 去重、工具 O(1) 配对、快照不共享可变对象；使用实际状态而不默认 PASS/published。
- [ ] 同目录新增 Generic fallback 与 P0 keyed renderers，覆盖十个 requirement P0 Tool，显示关键输入与有限结果、Receipt、error。
- [ ] DisclosureRow/AgentProcess 补 ARIA、reduced-motion、展开后才格式化且有长度上限、running 展开/成功折叠/失败展开/手动优先。
- [ ] Reviewer 按真实 review ID/attempt 展示 running → verdict，关闭时无假行。

## Task 3：SSE 续接与页面生命周期（root）

- [ ] 新 `frontend/tests/agentStreamProcess.test.ts` 先记录非流式 continuation 的 red；验证多次 handoff、同 Turn 事件、Browser failure、取消不再继续。
- [ ] `chatService.ts` 将 Browser continuation 全部改为同 SSE endpoint，透传 event_id/sequence 和后续事件。
- [ ] `App.tsx` 按当前请求 ownership 更新 UI，旧请求 finally 不清理新 Turn；停止/异常保留已观察事实，通信中断与 Runtime 失败分开显示。
- [ ] `Chat.tsx` 根据 Process 增量更新保持自动滚动规则，历史及完成 UI 复用同组件。

## Task 4：集成验证与验收记录

- [ ] 跑完整前端单测、lint/build 和必要后端回归。
- [ ] 浏览器验证流式 GIS handoff → receipt → resume → answer → review → publication；UI 键盘/折叠/未知工具/失败及历史恢复。
- [ ] 独立代码审查并修复必要问题。
- [ ] 更新 requirement：区分代码/确定性测试、模拟浏览器测试与真正连接 LLM/GIS 的验收证据；不能用其中一项替代另一项。

当前本机后端与数据库服务未监听，Docker daemon 未运行。真实 LLM/GIS 全链路需要可用验收环境；代码及确定性测试先独立完成。已有 auth/config/docker 与 Master Ledger 修改由其他任务负责，本次不覆盖、不提交、不部署。
