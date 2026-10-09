# AI 回答可读性 Implementation Plan

> **For agentic workers:** Follow the approved design and astra-orchestrator delegation policy. Execute task-by-task with test-driven-development and verification-before-completion. Root owns integration; file ownership below prevents overlapping edits.

**Goal:** 让 AI 回答先呈现结论与限制，再按层级提供可展开的依据，修复回答单元被 Markdown 合并为同一段的问题。

**Architecture:** 保留 Frozen Evidence、AnswerUnit、发布和历史协议。后端以空行组装完整 Markdown 单元并补充表达指导；前端独立 AnswerMarkdown 组件负责语义 HTML、顶层列表折叠和宽内容局部滚动，不推断或改写事实。

**Tech Stack:** Python、pytest、React 19、react-markdown、remark-gfm、Vitest、Playwright、现有 CSS 主题变量。

## 执行环境

工作区：`D:/work/Project/ragAI知识库 (2)/ragAI知识库`。已存在 Chat、AgentProcess 与 agentProcessUi 测试的未提交改动，必须保留。沿用当前工作区和现有依赖，不提交或覆盖用户既有修改，不增加运行依赖。

## Task 1: 后端表达与段落边界

**Ownership:** backend worker

**Files:**
- Modify: `Backend/app/services/agent/answer_generator.py`
- Test: `Backend/tests/test_agent_answer_generation.py`

- [x] 添加解析回归测试：两个引用 E1 的单元必须保留独立段落以及原始 unit text、unit_id、citation。

```python
payload = json.dumps({"kind": "knowledge_answer", "units": [
    {"unit_id": "u1", "text": "已确认适用。", "citations": ["E1"]},
    {"unit_id": "u2", "text": "适用范围仍有待核验项。", "citations": ["E1"]},
]}, ensure_ascii=False)
answer = AnswerGenerator._parse(payload, snapshot=make_snapshot())
assert answer.answer == "已确认适用。\n\n适用范围仍有待核验项。"
assert [unit.unit_id for unit in answer.units] == ["u1", "u2"]
assert answer.citations == ("E1",)
```

- [x] 执行上述测试并记录失败原因；确认旧代码输出单个换行。
- [x] 修改组装语句，不修改单元或引用：

```python
answer = "\n\n".join(unit.text for unit in units)
```

- [x] 对生成和修复路径加入共用表达规则：遵循用户语言；简单问题直接简短回答；长回答先给结论和限制；标准清单根据真实证据范围分组；列表一项一行；重要限制放独立段落；每个 unit 自身构成完整 Markdown 块。
- [x] 为原始工具字段提供准确释义：eligible_count 是已确认适用总数；unresolved_count 是库内适用范围未知的标准数；coverage_complete 不代表分页状态；next_cursor 代表后续页。禁止从编号推断范围、编造标准或把 GIS 执行回执当作业务适用性证据。
- [x] 修复表达指导只能用于 editable units，immutable units 必须原样保持。提示输出仍为现有 kind/units schema，不增加字段。
- [x] 测试混合 Markdown 单元内部文字不变，并通过 FakeModelClient 验证正常生成和受限修复都收到表达规则；保留所有现有 schema、引用和干净重试测试。
- [x] 运行后端验证：

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_agent_answer_generation.py tests/test_agent_reviewer.py tests/test_agent_reviewer_repair.py tests/test_agent_publication.py tests/test_agent_public_history_projection.py -q
```

工作目录为 Backend；期望全部通过。

## Task 2: 前端 Markdown 阅读组件

**Ownership:** frontend worker

**Files:**
- Create: `frontend/src/components/AnswerMarkdown.tsx`
- Create: `frontend/src/components/answerMarkdown.css`
- Modify: `frontend/src/components/Chat.tsx`（仅 Markdown 导入和 assistant 渲染块）
- Create: `frontend/tests/answerMarkdown.test.tsx`
- Modify: `frontend/package.json`（仅 test:unit 包含新测试）

- [x] 先通过现有 Chat 渲染长列表，断言出现“展开剩余”入口，运行并记录缺少折叠功能的预期失败。
- [x] 实现独立组件，接口如下；Chat 用 message.id 作 key 隔离不同回答的展开状态：

```tsx
interface AnswerMarkdownProps { content: string }
<AnswerMarkdown key={message.id} content={message.content} />
```

- [x] 使用 ReactMarkdown/remark-gfm。列表从已解析 React li 元素中取条目；通过 context 区分顶层和嵌套列表，只有超过 6 条的顶层列表折叠。前 6 条保持可见，剩余部分用原生 details/summary 展开；CSS 切换“展开剩余 N 项”与“收起”标签。ordered list 续接原始起始编号。
- [x] 表格与 pre 使用具有可访问标签和键盘可滚动的局部容器，保证不撑宽聊天栏。嵌套列表不二次折叠。
- [x] 样式全部以 answer-markdown 为作用域：保留主题变量，强调标题和 strong，增加段落与分组间距；前后段落去除多余外边距；可读的列表标记和续项间距；完整保留 Markdown 代码空白。
- [x] 先测试再实现短列表、嵌套列表、ordered list 编号、代码块、表格、段落/标题/限制不被折叠、危险 HTML 不执行和历史纯文本原样显示。
- [x] 把新测试加入既有 test:unit，不改其他脚本或依赖。
- [x] 运行前端定向测试：

```powershell
npx vitest run tests/answerMarkdown.test.tsx tests/agentProcessUi.test.tsx tests/agentHistory.test.ts
```

工作目录为 frontend；期望全部通过。

## Task 3: 集成验证与独立审查

**Ownership:** root + tester + reviewer（tester/reviewer 不修改业务文件）

- [x] Root 检查 diff，确保保留既有工作区修改、引用/schema/历史路径不变，并确认各 worker 的失败与通过证据。
- [x] Tester 用 Vite 临时页面挂载真实 Chat/AnswerMarkdown，在 360px 和 640px 宽度、明暗主题检查长清单、展开/收起、键盘操作、完整条目、宽表格/代码、消息隔离和引用点击。
- [x] 临时预览与脚本只写 frontend/.tmp；截图写用户可访问的本地目录。清单样例保留“节选”语义，不作为业务数据。
- [x] 执行完整前端验证：

```powershell
npm run test:unit
npm run lint
npm run build
```

- [x] Astra reviewer 基于最终差异只读审查，重点检查 Markdown 块边界、引用保持、嵌套列表、编号、可访问性、折叠后的完整信息和受限修复约束。
- [x] 修复实质问题并执行受影响检查；记录不能验证的条件。
- [x] Root 更新设计/计划验收状态，报告实现内容、测试结果和截图。

## 完成边界

不部署、不 push、不提交用户已有修改。首轮未加载 AOCI MCP 注册；跟进维护通过 stdio 接入已配置的本地服务，按机器签发的完整候选批次、源码哈希与 Guide 更新索引并校验，不伪造维护成功。既有单段历史回答只保留其原意，不能由前端猜测出业务分组。
