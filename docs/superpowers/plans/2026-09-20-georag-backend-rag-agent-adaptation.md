# GeoRAG Backend RAG / Agent Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在保留 GeoRAG 现有产品/API/GIS/文档生命周期与 PostgreSQL/pgvector 存储的前提下，用清晰的 Retrieval Port、Evidence 生命周期和 Agent Runtime 替换 `SearchService` 中混杂的语义规划与答案生成核心。

**Architecture:** `SearchService` 最终只保留确定性搜索门面；底层检索统一收敛到 `RetrievalPort -> PostgresRetrievalAdapter`。生成请求进入独立 `services/agent` 核心，由 Main Controller 唯一负责语义规划，Runtime 只负责工具执行、状态、事件和物理资源保险丝；Answer Generator 只能基于 Frozen Evidence 生成，Reviewer 为请求级显式开关且默认关闭。

**Tech Stack:** Python >= 3.12, FastAPI, Pydantic v2, PostgreSQL, pgvector, PostGIS, existing LLM client/config, pytest, React + TypeScript + generated OpenAPI schema.

**Spec:** `docs/superpowers/specs/2026-09-20-georag-backend-rag-agent-adaptation-design.md`

## Post-Review Closure Status

2026-09-20 final code-review closure completed the remaining non-E2E gaps:
Controller receives bounded Working Evidence; tool input models are the
schema/validation source of truth; request-level retrieval constraints are
preserved in Agent mode; retrieval now distinguishes zero matches, partial
degradation and total `RETRIEVAL_UNAVAILABLE`; limitation/resource/model/review
failure outcomes are structured; every user-visible terminal response is
written back to Session conversation state; Reviewer verdicts gate publication
in both Agent and explicit Linear mode; Session state is principal-scoped with
a hard in-memory capacity; legacy client history only seeds a new Session; the
production model adapter derives Controller reasoning capability from an
explicitly configured `LLM_REASONING_MODEL`; and the API composition root no
longer reaches through a private `SearchService` retrieval accessor.

Tasks 1–12 are code-complete and subject to the final automated verification
recorded by the implementation session. Task 13 real PostgreSQL + real LLM +
frontend E2E is intentionally skipped at the user's request. Therefore the
code migration may be treated as implementation-complete, but the original PRD
success criterion requiring production-like E2E remains explicitly unverified.

## Global Constraints

- Python 运行时必须满足 `>=3.12`；不能用系统 Python 3.11 的失败结果判断代码测试状态。
- PostgreSQL/pgvector 是唯一正式知识索引；不得引入 Chroma、双写或第二套 chunk 真源。
- 本次目标 Runtime 从结构上不包含图谱工具、GraphWorkingSet、GraphBudget 或 graph 配置。
- `use_generation=false` 必须保持纯确定性搜索，不进入 Agent/LLM。
- Agent 模式中 Main Controller 是唯一语义规划权威；Runtime 不做 intent/entity/relation 分类，不用固定检索次数替代 Controller 决策。
- 知识回答必须从 Working Evidence 选择并冻结为 Frozen Evidence 后才能生成；Controller 不允许直接发布知识答案。
- Reviewer 默认 `false`，只验证 Claim ↔ Frozen Evidence，不重新规划检索，不补充模型通用知识。
- Controller reasoning 可按请求和模型能力开启；Answer Generator 与 Reviewer reasoning 默认关闭。
- 禁止从 `reasoning_content` 抢救答案；结构化输出失败只允许明确、有限、可观测的 clean retry。
- 旧 API 兼容只能存在于 Route/Response Compatibility 边界，不能长期保留两套生成核心。
- 前端现有 `conversation_id` 必须成为后端 `session_id`；客户端 `history` 仅作为迁移期兼容输入。
- MapAction 最终为结构化响应字段；Markdown JSON 仅允许作为迁移期兼容输出。
- 每个任务先写失败测试，再写最小实现；每个任务通过定向测试后独立提交。

---

## Task 1: 建立隔离实施基线、Python 3.12 环境与 API 快照

**Files:**
- Create: `docs/superpowers/baselines/2026-09-20-search-openapi.json`
- Create: `docs/superpowers/baselines/2026-09-20-backend-test-baseline.md`
- Modify only if needed for reproducible dev install: `pyproject.toml`

**Interfaces:**
- Consumes: committed design/spec at `3a452af` plus this plan.
- Produces: isolated worktree, known Python 3.12 interpreter, reproducible test command, frozen `/api/search/query` OpenAPI contract.

- [x] **Step 1: Create the isolated implementation worktree from the plan commit**

Use `superpowers:using-git-worktrees`. Confirm the new worktree is based on the commit containing this plan and has a clean `git status` before edits.

- [x] **Step 2: Verify a Python 3.12 interpreter exists before creating any environment**

Run:

```bat
py -0p
py -3.12 --version
```

Expected: `Python 3.12.x`. If `py -3.12` does not exist, record the environment blocker in the baseline document; do not fall back to 3.11 and call the suite broken.

- [x] **Step 3: Create the project environment and install the dev dependencies**

Run:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

If editable install exposes existing packaging defects, record the exact failure and use the repository's already-declared dependency files only if present; do not silently invent a second dependency manifest.

- [x] **Step 4: Run the existing backend suite unchanged**

Run:

```bat
.venv\Scripts\python.exe -m pytest Backend\tests -q
```

Record interpreter version, pass/fail counts and every pre-existing failure in `docs/superpowers/baselines/2026-09-20-backend-test-baseline.md`.

- [x] **Step 5: Freeze the current OpenAPI shape**

Write a small one-shot Python command/test that imports `Backend/main.py`, serializes `app.openapi()` with stable key ordering, and writes `docs/superpowers/baselines/2026-09-20-search-openapi.json`. The snapshot must include `SearchRequest`, `SearchResponse` and `/api/search/query`.

- [x] **Step 6: Commit the baseline**

```bat
git add docs/superpowers/baselines pyproject.toml
git commit -m "test: establish GeoRAG adaptation baseline"
```

---

## Task 2: 收敛 Retrieval Boundary，建立 `RetrievalPort` 与 PostgreSQL Adapter

**Files:**
- Create: `Backend/app/services/rag/contracts.py`
- Create: `Backend/app/services/rag/postgres_adapter.py`
- Modify: `Backend/app/services/rag/filters.py`
- Modify: `Backend/app/services/rag/reranker.py`
- Modify: `Backend/app/services/search_service.py`
- Delete after migration: `Backend/app/services/rag/retriever.py`
- Modify: `Backend/app/services/rag/types.py`
- Test: `Backend/tests/test_rag_retrieval_port.py`
- Modify tests: `Backend/tests/test_rag_retriever_degradation.py`
- Regression tests: `Backend/tests/test_search_service_standard_code.py`, `Backend/tests/test_rag_metadata_filters.py`, `Backend/tests/test_rag_spatial_filters.py`, `Backend/tests/test_rag_reranker.py`

**Interfaces:**
- Consumes: current exact-standard, SQL keyword, pgvector, metadata, spatial and rerank behavior from `SearchService` and existing `services/rag/*` helpers.
- Produces:
  - `RetrievalQuery(query_text, top_k, threshold, search_mode, use_rerank, metadata_filter, spatial_filter)`
  - `RetrievalCandidate(chunk_id, document_id, text, title, score, metadata, provenance, source_result)`
  - `RetrievalResult(candidates, embedding_available, diagnostics)`
  - `RetrievalPort.retrieve(query: RetrievalQuery) -> RetrievalResult`
  - `RetrievalPort.fetch_chunks(chunk_ids: Sequence[str]) -> list[RetrievalCandidate]`

- [x] **Step 1: Write failing port contract tests**

Add tests proving that retrieval contracts contain stable chunk/document identity and provenance, and that `PostgresRetrievalAdapter.retrieve()` preserves exact/keyword/vector fallback behavior without requiring any LLM.

Example shape:

```python
query = RetrievalQuery(query_text="GB 50016", top_k=5, search_mode="hybrid")
result = await adapter.retrieve(query)
assert result.candidates
assert all(item.chunk_id for item in result.candidates)
assert all(item.provenance.source == "postgres" for item in result.candidates)
```

- [x] **Step 2: Run the new tests and verify they fail for missing contracts**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_rag_retrieval_port.py -q
```

- [x] **Step 3: Implement neutral retrieval contracts**

Use frozen dataclasses or Pydantic models with no SQL/pgvector imports. `RetrievalPort` must be a `Protocol`; the Agent layer must be able to depend on this module without importing `search_service.py`.

- [x] **Step 4: Move retrieval ownership into `PostgresRetrievalAdapter`**

Move/extract the current `_exact_standard_code_search`, `_keyword_search`, `_vector_search`, uploaded-document variants, candidate merge, metadata/spatial filter application and rerank orchestration out of semantic/generation ownership in `SearchService`. Preserve behavior through tests; do not add new retrieval heuristics during this task.

`SearchService.search()` becomes a thin deterministic façade that creates `RetrievalQuery`, calls the adapter, maps candidates back to existing `DocumentResult`, logs, and returns results.

- [x] **Step 5: Remove the duplicate retrieval orchestrator**

Once `PostgresRetrievalAdapter` owns exact/keyword/vector composition, migrate `test_rag_retriever_degradation.py` to the port/adapter contract and delete `Backend/app/services/rag/retriever.py`. Do not keep both `RagRetriever` and `PostgresRetrievalAdapter` performing the same composition.

- [x] **Step 6: Run retrieval regression tests**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_rag_retrieval_port.py Backend\tests\test_rag_retriever_degradation.py Backend\tests\test_search_service_standard_code.py Backend\tests\test_rag_metadata_filters.py Backend\tests\test_rag_spatial_filters.py Backend\tests\test_rag_reranker.py -q
```

- [x] **Step 7: Commit the retrieval boundary**

```bat
git add Backend/app/services/rag Backend/app/services/search_service.py Backend/tests
git commit -m "refactor: establish PostgreSQL retrieval boundary"
```

---

## Task 3: 建立 Evidence Ledger、Working Evidence、Frozen Snapshot 与会话 Evidence Memory

**Files:**
- Create: `Backend/app/services/agent/__init__.py`
- Create: `Backend/app/services/agent/contracts.py`
- Create: `Backend/app/services/agent/evidence.py`
- Test: `Backend/tests/test_agent_evidence_lifecycle.py`

**Interfaces:**
- Consumes: `RetrievalCandidate` from Task 2.
- Produces: `EvidenceItem`, `EvidenceLedger`, `FrozenEvidenceSnapshot`, `EvidenceMemorySearchResult`, stable evidence/citation IDs.

- [x] **Step 1: Write failing lifecycle tests**

Cover:

```python
ledger.add_candidates(turn_id="t1", candidates=[candidate])
snapshot = ledger.freeze(turn_id="t1", evidence_ids=[candidate_evidence_id])
assert snapshot.items[0].evidence_id == candidate_evidence_id
assert snapshot.items[0].citation_id.startswith("E")
```

Also assert that historical evidence is searchable but is not automatically part of a new turn's frozen snapshot.

- [x] **Step 2: Verify the tests fail**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_agent_evidence_lifecycle.py -q
```

- [x] **Step 3: Implement deterministic candidate admission and stable identity**

Candidate admission may reject structurally invalid/empty candidates, but must not call an LLM per chunk. Preserve provenance, source document/chunk IDs, retrieval score and scope metadata.

- [x] **Step 4: Implement immutable frozen snapshots**

`FrozenEvidenceSnapshot` must be immutable after creation. Answer generation/review receives the snapshot rather than a mutable ledger view.

- [x] **Step 5: Implement session-level Evidence Memory search**

Expose explicit lookup by query/metadata over previously admitted evidence. A lookup returns candidates for Controller consideration; it never silently reactivates citations.

- [x] **Step 6: Run lifecycle tests and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_agent_evidence_lifecycle.py -q
git add Backend/app/services/agent Backend/tests/test_agent_evidence_lifecycle.py
git commit -m "feat: add evidence ledger and frozen snapshots"
```

---

## Task 4: 建立无图谱 Tool Runtime

**Files:**
- Create: `Backend/app/services/agent/tools.py`
- Create: `Backend/app/services/agent/tool_runtime.py`
- Test: `Backend/tests/test_agent_tool_runtime.py`
- Test: `Backend/tests/test_agent_architecture_guards.py`

**Interfaces:**
- Consumes: `RetrievalPort`, `EvidenceLedger`.
- Produces tools: `retrieve_kb`, `reuse_evidence`, `compose_answer`, `clarify`; plus schema validation, dispatch, timeout/idempotency and physical resource accounting.

- [x] **Step 1: Write failing registry tests**

Assert the exact public tool names are:

```python
assert registry.names() == {
    "retrieve_kb",
    "reuse_evidence",
    "compose_answer",
    "clarify",
}
assert not any("graph" in name.lower() for name in registry.names())
```

Also assert no tool description contains a semantic mandate such as “多实体必须调用” or a fixed “检索两次后停止” rule.

- [x] **Step 2: Implement typed tool inputs/observations and dispatcher**

`retrieve_kb` accepts a semantic search gap plus ordinary retrieval hints and writes returned candidates to Working Evidence. `reuse_evidence` performs explicit historical evidence lookup. `compose_answer` accepts selected evidence IDs and creates the Frozen Snapshot. `clarify` ends the turn with a structured clarification result.

- [x] **Step 3: Add physical-only resource fuse**

Track total Controller steps/tool execution time as protection against infinite loops. Resource exhaustion must surface `RESOURCE_FUSE`; do not encode “N retrievals means stop” as semantics.

- [x] **Step 4: Add architecture guards**

Test that `Backend/app/services/agent` contains no imports of Chroma and no graph registry/state symbols.

- [x] **Step 5: Run and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_agent_tool_runtime.py Backend\tests\test_agent_architecture_guards.py -q
git add Backend/app/services/agent Backend/tests
git commit -m "feat: add graph-free agent tool runtime"
```

---

## Task 5: 建立 Stage Policy、Main Controller、Answer Generator 与 Reviewer

**Files:**
- Create: `Backend/app/services/agent/stage_policy.py`
- Create: `Backend/app/services/agent/controller.py`
- Create: `Backend/app/services/agent/answer_generator.py`
- Create: `Backend/app/services/agent/reviewer.py`
- Modify: `Backend/app/core/llm_config.py`
- Test: `Backend/tests/test_agent_stage_policy.py`
- Test: `Backend/tests/test_agent_answer_generation.py`
- Test: `Backend/tests/test_agent_reviewer.py`

**Interfaces:**
- Consumes: Tool Runtime and `FrozenEvidenceSnapshot`.
- Produces: `LLMStagePolicy`, Controller tool decisions, structured final answer, optional grounding review.

- [x] **Step 1: Write failing stage-policy tests**

Required behavior:

```python
policy = LLMStagePolicy(user_thinking=True, endpoint_supports_reasoning=True)
assert policy.for_stage("controller").request_reasoning is True
assert policy.for_stage("answer_generation").request_reasoning is False
assert policy.for_stage("reviewer").request_reasoning is False
```

- [x] **Step 2: Write failing answer publication tests**

Assert `knowledge_answer` cannot be created/published without a non-empty Frozen Snapshot. Limitation/clarification remains legal without knowledge evidence.

- [x] **Step 3: Implement the Controller as the only semantic planner**

The Controller receives user question, context projection, available tools and tool observations. It returns a structured next action. Runtime code must not pre-classify intent before calling it.

- [x] **Step 4: Implement Answer Generator over Frozen Evidence only**

Input contract contains user question, bounded context and Frozen Snapshot. The generator may format/derive bounded claims from those evidence items but cannot call retrieval. If structured output is invalid or `content` is empty, perform at most one clean retry with answer-generation reasoning forced OFF; never parse `reasoning_content` as answer text.

- [x] **Step 5: Implement Reviewer as optional grounding validation**

Reviewer returns supported/unsupported/overstated findings for claims and citation IDs. It never calls retrieval and never rewrites the user's semantic task.

- [x] **Step 6: Run and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_agent_stage_policy.py Backend\tests\test_agent_answer_generation.py Backend\tests\test_agent_reviewer.py Backend\tests\test_agent_architecture_guards.py -q
git add Backend/app/services/agent Backend/app/core/llm_config.py Backend/tests
git commit -m "feat: add agent LLM stage boundaries"
```

---

## Task 6: 建立 Session、Context Builder、事件模型与 Agent Runtime Loop

**Files:**
- Create: `Backend/app/services/agent/session.py`
- Create: `Backend/app/services/agent/context.py`
- Create: `Backend/app/services/agent/events.py`
- Create: `Backend/app/services/agent/runtime.py`
- Test: `Backend/tests/test_agent_runtime.py`
- Test: `Backend/tests/test_agent_context.py`

**Interfaces:**
- Consumes: Controller, Tool Runtime, Evidence Ledger, Answer Generator, Reviewer, Stage Policy.
- Produces: `AgentRuntime.run(request) -> AgentRunResult`, stable `session_id`, `trace_id`, ordered events and publication state.

- [x] **Step 1: Write failing multi-turn session tests**

Test that two turns sharing the same session can explicitly discover historical evidence, while a different session cannot. Verify no fixed `history[-6:]` behavior exists in the new context path.

- [x] **Step 2: Implement session state with explicit ownership**

Session owns conversation events, evidence memory and turn metadata. Request-carried legacy history can seed a new/migrating session but is not a second persistent truth source.

- [x] **Step 3: Implement token-budget context projection**

Build Controller context from current request + selected historical conversation/evidence metadata under a token/character budget. Keep evidence items separate from free-text history.

- [x] **Step 4: Implement the runtime loop**

Loop: build context → call Controller → dispatch one structured action → append observation/event → continue until `compose_answer`/`clarify` or physical fuse. `compose_answer` freezes evidence then invokes Answer Generator and optional Reviewer.

- [x] **Step 5: Run and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_agent_runtime.py Backend\tests\test_agent_context.py Backend\tests\test_agent_architecture_guards.py -q
git add Backend/app/services/agent Backend/tests
git commit -m "feat: add session-aware agent runtime"
```

---

## Task 7: 将 `/api/search/query` 接入新核心并保持 API 向后兼容

**Files:**
- Modify: `Backend/app/models/search_models.py`
- Modify: `Backend/app/api/search_routes.py`
- Modify: `Backend/app/services/search_service.py`
- Create: `Backend/app/services/search_application_service.py`
- Test: `Backend/tests/test_search_agent_api.py`
- Modify: `Backend/tests/test_api_contract_models.py`
- Modify: `Backend/tests/test_api_contract_openapi.py`
- Regression: `Backend/tests/test_search_demo_quota.py`

**Interfaces:**
- Consumes: deterministic `SearchService.search()` and `AgentRuntime.run()`.
- Produces one application boundary selecting search vs agent without reintroducing semantic classification.

- [x] **Step 1: Write failing request/response contract tests**

Add optional request fields:

```python
session_id: str | None = None
mode: Literal["agent", "linear"] | None = None
reviewer_enabled: bool = False
thinking: bool | None = None
```

Add response fields:

```python
session_id: str | None
trace_id: str | None
final_mode: str | None
publication_state: str | None
map_action: MapAction | None
```

- [x] **Step 2: Implement `SearchApplicationService` routing by explicit product mode only**

Rules:

```text
use_generation=false -> deterministic SearchService.search
use_generation=true  -> AgentRuntime (default mode agent)
```

Do not call `detect_intent()` to choose these paths.

- [x] **Step 3: Preserve Auth/Demo quota and existing response fields**

The route remains responsible for public contract/auth/quota behavior. New runtime metadata augments rather than replaces existing `results`, `generated_answer`, `quota`, timing fields.

- [x] **Step 4: Verify OpenAPI backward compatibility**

Compare the baseline snapshot: old request fields remain accepted and old response fields remain present; new fields are optional/defaulted.

- [x] **Step 5: Run and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_search_agent_api.py Backend\tests\test_api_contract_models.py Backend\tests\test_api_contract_openapi.py Backend\tests\test_search_demo_quota.py -q
git add Backend/app Backend/tests
git commit -m "feat: route generated search through agent runtime"
```

---

## Task 8: 前端 `conversation_id -> session_id` 接线

**Files:**
- Modify: `frontend/src/services/chatService.ts`
- Modify generated API schema through the repository's existing generation command/output: `frontend/src/lib/api/generated/schema.*`
- Modify types only where generated schema cannot express local wrapper semantics: `frontend/src/types/api.ts`, `frontend/src/types/index.ts`
- Test: existing frontend test/check command; add a focused test only if a test runner already exists.

**Interfaces:**
- Consumes: Task 7 optional `session_id` request/response.
- Produces: every continuing chat sends its local conversation ID as runtime session ID and adopts the server-returned session ID.

- [x] **Step 1: Regenerate or update the OpenAPI client from the backend contract**

Do not hand-maintain a divergent duplicate SearchRequest type if the generated schema is the source of truth.

- [x] **Step 2: Send `session_id` in `chatService.sendMessage()`**

The request object must include:

```ts
session_id: conversationId,
```

and returned `conversation_id` must prefer `searchResponse.session_id` before locally generating a fallback.

- [x] **Step 3: Keep `history` only as migration compatibility**

Do not remove it in this task; ensure runtime session continuity no longer depends solely on it.

- [x] **Step 4: Run frontend type/build checks and commit**

Use the scripts declared by `frontend/package.json` (for example `npm run build`/`npm run check` if present), then:

```bat
git add frontend
git commit -m "feat: connect chat conversations to agent sessions"
```

---

## Task 9: 升级 DocumentIndexingService 的 parser/chunker 内核

**Files:**
- Create: `Backend/app/services/document_parser.py`
- Create: `Backend/app/services/document_chunker.py`
- Modify: `Backend/app/services/document_indexing_service.py`
- Modify if necessary: `Backend/app/services/document_text_extractor.py`
- Test: `Backend/tests/test_document_parser.py`
- Test: `Backend/tests/test_document_chunker.py`
- Regression: `Backend/tests/test_document_indexing_service.py`, `Backend/tests/test_document_text_extractor.py`

**Interfaces:**
- Consumes: existing MinIO download/index job lifecycle.
- Produces: normalized parsed blocks/chunks while still writing through the existing repository into PostgreSQL/pgvector.

- [x] **Step 1: Write failing structure-preservation tests**

Cover heading boundaries, Markdown tables, fenced code blocks, Word cleanup and Excel-to-Markdown representation using small fixture strings/files already supported by repository dependencies.

- [x] **Step 2: Implement parser normalization and deterministic chunker**

Adapt the useful behavior from the source RAG project, but expose GeoRAG-native `parse(path)` and `chunk(parsed_document)` contracts. Do not import the source project's directory scanner, Chroma ingestion or graph extraction.

- [x] **Step 3: Replace `_split_text` ownership in `DocumentIndexingService`**

Keep `run_job()` lifecycle and repository/storage boundaries unchanged; only swap parsing/chunking internals.

- [x] **Step 4: Run indexing regression tests and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_document_parser.py Backend\tests\test_document_chunker.py Backend\tests\test_document_indexing_service.py Backend\tests\test_document_text_extractor.py -q
git add Backend/app/services Backend/tests
git commit -m "feat: preserve document structure during indexing"
```

---

## Task 10: 引入结构化 `MapAction` 并建立唯一兼容边界

**Files:**
- Modify: `Backend/app/models/search_models.py`
- Create: `Backend/app/services/map_action_adapter.py`
- Modify: `Backend/app/services/agent/contracts.py`
- Modify: `Backend/app/services/agent/answer_generator.py`
- Modify: `frontend/src/App.tsx`
- Test: `Backend/tests/test_map_action_compatibility.py`

**Interfaces:**
- Produces `MapAction(type, target, adcode, name, payload)` as structured response data.

- [x] **Step 1: Write failing backend compatibility tests**

Assert a generated structured `MapAction` is returned in `SearchResponse.map_action` and, while migration compatibility is enabled, a single Response Adapter may render the legacy Markdown JSON representation.

- [x] **Step 2: Implement structured MapAction generation/output**

Keep map action outside Evidence objects. If the action relies on a knowledge claim (for example an administrative code found in documents), that claim still requires frozen evidence.

- [x] **Step 3: Make frontend prefer `response.map_action`**

Retain old text extraction only as fallback during this task. Once structured path is proven by frontend regression/E2E, remove the fallback in Task 12.

- [x] **Step 4: Run tests/build and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_map_action_compatibility.py -q
git add Backend frontend
git commit -m "feat: add structured map actions"
```

---

## Task 11: 将 SSE/流式输出收敛到 Runtime Event Stream

**Files:**
- Modify: `Backend/app/services/agent/events.py`
- Modify: `Backend/app/services/agent/runtime.py`
- Modify: `Backend/app/api/search_routes.py`
- Modify: `frontend/src/services/chatService.ts`
- Test: `Backend/tests/test_agent_stream_events.py`

**Interfaces:**
- Produces ordered runtime events with stable `session_id`, `trace_id`, `turn_id`, event type and payload.

- [x] **Step 1: Write failing event-order tests**

For a simple retrieval answer, assert observable order such as controller decision → tool started/completed → evidence frozen → answer generated → publication completed. Tests verify ordering/identity, not hidden chain-of-thought text.

- [x] **Step 2: Implement a runtime event iterator/bridge**

Events expose stage/status/tool/evidence facts and readable summaries only. Do not stream raw private reasoning or rely on provider-specific reasoning payloads.

- [x] **Step 3: Adapt SSE route/client without creating a second execution path**

Streaming and non-streaming requests must call the same Runtime. SSE is only a projection of the same events/result.

- [x] **Step 4: Run tests/build and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests\test_agent_stream_events.py -q
git add Backend frontend
git commit -m "feat: stream agent runtime events"
```

---

## Task 12: 删除旧 `SearchService` 语义/生成核心与所有迁移残留

**Files:**
- Modify: `Backend/app/services/search_service.py`
- Modify: `Backend/app/api/search_routes.py`
- Delete obsolete tests or migrate their intent to new owner: `Backend/tests/test_chat_intent.py`, `Backend/tests/test_search_follow_up.py`
- Modify: `frontend/src/App.tsx`
- Modify configs: `Backend/app/core/config.py`, `Backend/app/core/llm_config.py` only for fields proven obsolete by repository search.
- Test: `Backend/tests/test_agent_architecture_guards.py`

**Interfaces:**
- Produces one deterministic retrieval/search core and one Agent generation core; no parallel semantic router/generator remains.

- [x] **Step 1: Extend architecture guards to fail while legacy core remains**

Guard against definitions/references for:

```text
SearchService.detect_intent
SearchService.handle_dialog_management
SearchService.generate_chitchat_response
SearchService.generate_answer
SearchService.generate_stream_answer
history[-6:] / _truncate_history
legacy answer map JSON prompt
NON_SEARCH_INTENTS
```

- [x] **Step 2: Delete old semantic ownership from `SearchService`**

Remove both duplicate `detect_intent()` definitions and all methods now owned by Controller/Session/Answer Generator. Retain only deterministic search/data helpers that have not already moved into `PostgresRetrievalAdapter`.

- [x] **Step 3: Remove the old frontend Markdown JSON extractor after structured MapAction is the primary path**

Delete `extractAdcodeAndPurify` (or its current equivalent) only after the Task 10 structured path is covered by tests/build.

- [x] **Step 4: Run a repository-wide residue audit**

Search for: `Chroma`, `GraphWorkingSet`, `GraphBudget`, `expand_graph_scope`, `detect_intent`, `generate_chitchat_response`, duplicate answer prompts, `reasoning_content` answer recovery, old map JSON parsing and unused reviewer/graph settings. Every hit must be either required by unrelated product code or removed; document justified survivors.

- [x] **Step 5: Run full automated verification and commit**

```bat
.venv\Scripts\python.exe -m pytest Backend\tests -q
git status --short
git diff --check
git add Backend frontend docs
git commit -m "refactor: retire legacy search generation core"
```

---

## Task 13: 真实 PostgreSQL + LLM + Frontend E2E 与最终验收

**Files:**
- Create: `docs/superpowers/verification/2026-09-20-georag-agent-e2e.md`
- Add only minimal executable E2E fixtures/scripts if the repository has an established location; do not create a parallel test framework.

**Interfaces:**
- Validates the complete production-like path, not just pytest mocks.

- [ ] **Step 1: Verify services/config use the intended real environment**

Record exact Git commit, Python version, PostgreSQL/pgvector availability, selected real LLM endpoint/model, frontend build commit and whether Reviewer is OFF/ON for each case. Do not print secrets.

- [ ] **Step 2: Exercise deterministic search cases**

Verify exact standard code, semantic/hybrid retrieval, metadata filter and spatial filter with `use_generation=false`; confirm no LLM stage is invoked.

- [ ] **Step 3: Exercise Agent knowledge cases**

Verify retrieval-backed answer, evidence citations, insufficient-evidence limitation/clarification, Reviewer OFF and Reviewer ON behavior, and that no knowledge answer publishes without Frozen Evidence.

- [ ] **Step 4: Exercise real multi-turn session**

Use frontend conversation continuity to prove the same `session_id` persists, historical Evidence can be explicitly reused, and stale historical Evidence is not automatically cited after scope changes.

- [ ] **Step 5: Exercise upload → index → query**

Upload a real supported document through the existing document lifecycle, wait for the existing job to reach success, then retrieve/answer from its new PostgreSQL chunks.

- [ ] **Step 6: Exercise MapAction and runtime event rendering**

Verify structured map action drives the frontend and that stream/non-stream paths converge on the same final result/trace semantics.

- [ ] **Step 7: Restart backend and verify persisted product data remains consistent**

Session persistence expectations must match the implementation chosen in Task 6; document whether session runtime state is intentionally in-memory or persisted. PostgreSQL documents/chunks must remain unchanged and queryable.

- [ ] **Step 8: Run final full test/build/residue audit**

Required final evidence includes:

```text
Backend full pytest result
frontend type/build result
git diff --check
git status --short
architecture guard result
real E2E case table with pass/fail and trace/session IDs
```

- [ ] **Step 9: Commit verification evidence**

```bat
git add docs/superpowers/verification
git commit -m "test: verify GeoRAG agent adaptation end to end"
```

---

## Implementation Order and Review Gates

The dependency order is intentional:

```text
Task 1 baseline
  -> Task 2 retrieval boundary
  -> Task 3 evidence
  -> Task 4 tool runtime
  -> Task 5 LLM stages
  -> Task 6 runtime/session
  -> Task 7 API wiring
  -> Task 8 frontend session
  -> Task 9 ingestion
  -> Task 10 map action
  -> Task 11 streaming
  -> Task 12 legacy removal/residue audit
  -> Task 13 real E2E
```

Do not begin Task 5 while Task 2 still exposes retrieval through `SearchService`-specific private callbacks, and do not perform Task 12 cleanup before Task 7-11 replacement paths have passing tests. Each task must be reviewable as a coherent architectural step rather than a partially wired compatibility patch.

## Final Acceptance Conditions

The adaptation is complete only when all of the following are demonstrated by code/tests/E2E evidence:

1. Auth, Demo quota, Document, Spatial and existing deterministic Search paths still work.
2. PostgreSQL/pgvector remains the only knowledge index.
3. `use_generation=true` uses the new Agent Runtime; `false` never invokes LLM stages.
4. Runtime has no graph subsystem and does not make semantic intent decisions.
5. Main Controller plans tool usage; Answer Generator only consumes Frozen Evidence.
6. Reviewer is explicit and OFF by default.
7. Controller/Answer/Reviewer reasoning policies are stage-specific.
8. Session identity is carried from frontend conversation to backend Runtime.
9. Evidence Memory is accessible across turns without automatic stale citation reuse.
10. MapAction is structured; legacy text parsing is removed after migration.
11. Streaming is a projection of the same Runtime, not a parallel answer pipeline.
12. `SearchService` no longer contains the old intent/dialog/generation core or duplicate `detect_intent` definitions.
13. Python 3.12 backend tests and frontend build/type checks pass, modulo only explicitly documented pre-existing baseline failures that were not caused by this work.
14. Real PostgreSQL + real LLM + frontend E2E is executed and recorded.
15. Final repository-wide residue audit finds no dead graph/Chroma/legacy-generation compatibility code introduced or left by this migration.
