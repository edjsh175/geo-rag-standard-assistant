# GeoRAG 对公司 RAG 2026-09-22 架构增量适配记录

## 状态

- 设计判断：已完成。
- 代码实现：已完成于隔离 worktree，尚未在本文记录时合并回 `main`。
- 自动化验证：Agent / Search API 相关回归已执行；真实 PostgreSQL + pgvector + LLM + 浏览器 E2E 仍未执行。
- 参考仓库基线：`rag_cy\rag` 当前 `main` 为 `90bb3eb`；本轮核心架构变化主要来自 `82aa5d6`、`bed125f`、`cdbbad4`、`dd0a54c`、`003dce1`。

## 为什么需要再次适配

上一轮 GeoRAG 已完成 Agent Runtime、Retrieval Port、Evidence 生命周期、Session、Tool Calling、Answer Generator、Reviewer 和 MapAction 的主体升级，但公司 RAG 后续又收紧了若干横切契约。真正需要同步的不是文件结构，而是以下不变量：

1. **Main Model Identity**：一次请求只解析一次 Main 模型身份；Controller、Answer Generator、Reviewer 共享该身份。`thinking` 只影响阶段是否请求 reasoning，不能导致不同阶段偷偷使用不同模型。
2. **Structured Candidate Contract**：结构化模型输出统一遵循 `生成 -> 确定性校验 -> 最多一次 clean retry -> fail-close`。
3. **Publication Authority**：候选答案是否可见只能由单一发布契约决定，API 不得根据零散字段重新推断。
4. **Reviewer Referential Integrity**：Reviewer 必须基于稳定 `unit_id` 对 Answer Unit 一一审查；“漏审”不能等价于“SUPPORTED”。

## GeoRAG 本轮实现边界

### 1. 请求级 Main 模型身份

`LLMConfig` 增加请求级 Main 模型解析；`AgentRuntime` 每次运行只解析一次，并把结果显式传给 Controller、Answer Generator、Reviewer。

当用户开启 thinking 且配置了 reasoning-capable Main 模型时，可以选择该模型作为本次请求的 Main 模型；后续 Answer Generator / Reviewer 即使阶段 reasoning 关闭，也继续使用同一模型身份。

### 2. 统一 Structured Candidate 协议

新增轻量 `structured_candidate` 边界，Answer Generator 与 Reviewer 共用同一协议：

```text
attempt 1
  -> generate
  -> deterministic validate
  -> valid: accept
  -> invalid: one clean retry

attempt 2
  -> reasoning = false
  -> temperature = 0
  -> deterministic validate
  -> invalid: fail-close
```

禁止从 `reasoning_content` 抢救结构化结果，也不允许无限协议重试。

### 3. Answer Unit 与 Reviewer 一一绑定

Answer Generator 的优先结构改为：

```json
{
  "kind": "knowledge_answer",
  "units": [
    {
      "unit_id": "u1",
      "text": "...",
      "citations": ["E1"]
    }
  ]
}
```

Reviewer 必须返回与 Candidate Units 完全同构的一组 `unit_id` 审查结果：

- 不允许缺失 Unit；
- 不允许重复 Unit；
- 不允许引用不存在的 Unit；
- citation 必须属于当前 Frozen Evidence；
- 协议错误最多 clean retry 一次，之后失败关闭。

旧 `answer + citations` 形式仍只在 Answer Generator 输入边界做确定性兼容，并立即正规化成单一 `u1`；Reviewer 不再接受自由文本 `claim` 作为指代主键。

### 4. 单一发布权威

新增 `PublishedResult` / `PublicationDecision`。Agent Runtime 的最终结果负责把内部状态映射为：

- `PUBLISH`
- `SAFE_FALLBACK`

Search Application Service 只消费 `PublishedResult`，不再自行从 `answer / clarification / limitation` 重新推断 Agent 发布结果。

Linear 兼容路径也必须经过同一 `PublishedResult` 类型边界，Reviewer 拒绝或失败时不得泄漏 Candidate 或 MapAction。

## 明确不迁移的公司 RAG 能力

### LogicalTurn / QA Debug

公司 RAG 的 QA Trace、证据审查页、LogicalTurn 生命周期属于其运营与审计产品域。GeoRAG 当前没有对应页面和跨 Trace 聚合问题，本轮不引入。

### Graph subsystem

GeoRAG 本版设计仍明确不引入 Graph subsystem，因此不迁移 GraphWorkingSet、GraphBudget、图谱工具或相关语义策略。

### Provider retry / unified model-call deadline accounting

公司 RAG 新增了“一个逻辑模型调用共享唯一 wall-clock deadline，并记录 attempt/backoff”的完整调用记账。GeoRAG 当前底层 LLM 适配器没有同等级的 provider retry/backoff 机制，只有现有 provider timeout 与本轮结构化协议 clean retry。

因此本轮不为了形式一致而复制整套 `ModelStreamRunner/llm_http` 机制。若后续 GeoRAG 引入 provider retry、fallback 或多 endpoint 路由，再把“逻辑调用 deadline + attempt accounting”作为独立基础设施任务实现。

## 验收边界

自动化需要证明：

1. 一次 Runtime 请求只解析一次 Main 模型身份，并贯穿 Controller / Answer / Reviewer；
2. Answer Generator 非法结构最多 clean retry 一次；
3. Reviewer 缺失任一 Answer Unit 时不能通过，必须进入 bounded retry / fail-close；
4. 被 Reviewer 阻断的答案不能通过 API 出口泄漏 Candidate 或 MapAction；
5. Agent 与 Linear 的发布结果都经过 `PublishedResult`；
6. 既有 Agent、Evidence、Tool Runtime、Session、Search API 与 SSE 回归继续通过。

真实 PostgreSQL + pgvector + 真实 LLM + 浏览器前端链路仍属于独立 E2E 验收，不因单元/集成测试通过而视为完成。
