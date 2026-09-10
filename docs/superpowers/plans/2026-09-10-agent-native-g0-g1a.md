# Agent-Native V3 G0-G1a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 冻结 GeoAI V3 迁移前行为，建立可追溯的只读上游来源清单和校验器，并用默认关闭的 feature flag 为后续内置 Agent Runtime 迁入建立安全门。

**Architecture:** G0 保持 `/api/search/*` 与前端旧聊天链路不变，只记录已通过的回归基线。G1a 使用 TOML source manifest 描述两个上游仓库、冻结 commit、候选迁入闭包和排除边界，并用 Python 标准库与 Git CLI 做确定性校验；本计划不创建 `Backend/agent_runtime/`，不复制上游代码。

**Tech Stack:** Python 3.12、Pydantic Settings 2.5、pytest 7.4、TOML/tomllib、Git、React 19/Vite 6 现有验证脚本。

---

## 文件结构

- Modify: `.gitignore` — 忽略项目内隔离 worktree 目录。
- Modify: `Backend/app/core/config.py` — 定义 `legacy | agent` 运行模式，默认 `legacy`。
- Create: `Backend/scripts/verify_agent_native_sources.py` — 校验 manifest、冻结 commit、工作树状态和候选路径。
- Create: `Backend/tests/test_agent_native_feature_flag.py` — feature flag 的 RED/GREEN 契约。
- Create: `Backend/tests/test_agent_native_g0_contract.py` — 冻结旧 API、前端聊天目标与 map action 契约。
- Create: `Backend/tests/test_agent_native_source_manifest.py` — source manifest 与排除边界契约。
- Create: `Backend/tests/test_verify_agent_native_sources.py` — provenance verifier 的单元测试。
- Create: `docs/agent-native/G0_BASELINE.md` — 基线命令、结果和已知警告。
- Create: `docs/upstream-sources/agent-native-v3.toml` — 上游来源、授权、候选闭包和目标边界。
- Create: `docs/upstream-sources/README.md` — Fork at Integration Boundary 同步规则。
- Modify: `docs/superpowers/specs/2026-09-10-agent-native-g0-g1-design.md` — 将 manifest 格式锁定为 TOML。

## Task 0：保存现有工作并建立隔离 worktree

- [ ] **Step 1: 确认基线验证证据**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests --basetemp .codex_tmp/pytest-g0-full -p no:cacheprovider
Set-Location frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: Backend `85 passed`；frontend 7 个脚本测试通过，lint exit 0，build exit 0。允许现有 Pydantic/deprecation 与 bundle-size warning，不允许失败或 error。

- [ ] **Step 2: 将项目 worktree 目录加入忽略规则**

在 `.gitignore` 末尾加入：

```gitignore

# Isolated Codex feature worktrees
.worktrees/
```

- [ ] **Step 3: 验证 worktree 目录确实被忽略**

Run:

```powershell
git check-ignore .worktrees/probe
```

Expected: 输出 `.worktrees/probe`，exit 0。

- [ ] **Step 4: 创建可恢复的 pre-V3 基线分支和快照提交**

Run:

```powershell
git switch -c baseline/v3-pre-upgrade-20260910
git add -A
git commit -m "chore: snapshot pre-v3 baseline"
```

Expected: commit 包含用户当前已有修改、PRD/设计/计划及 `.gitignore`；`git status --short` 为空。不得清理、重置或重写任一现有文件。

- [ ] **Step 5: 创建隔离实现 worktree**

Run:

```powershell
git worktree add .worktrees/v3-agent-native-g0-g1a -b feature/v3-agent-native-g0-g1a baseline/v3-pre-upgrade-20260910
```

Expected: worktree 位于仓库内 `.worktrees/v3-agent-native-g0-g1a`，分支为 `feature/v3-agent-native-g0-g1a`。

- [ ] **Step 6: 复用原 checkout 已验证的本地依赖环境**

Run（working directory 改为新 worktree）：

```powershell
New-Item -ItemType Junction -Path 'Backend\.venv' -Target (Resolve-Path '..\..\Backend\.venv')
New-Item -ItemType Junction -Path 'frontend\node_modules' -Target (Resolve-Path '..\..\frontend\node_modules')
```

Expected: 两个 junction 创建成功；它们分别受 `.venv` 和 `node_modules/` 忽略规则保护，不进入 Git。

- [ ] **Step 7: 在隔离 worktree 复跑快速基线**

Run（working directory 改为新 worktree）：

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_chat_intent.py Backend/tests/test_search_follow_up.py Backend/tests/test_search_evidence_formatting.py Backend/tests/test_search_map_action_contract.py Backend/tests/test_search_demo_quota.py Backend/tests/test_search_service_standard_code.py Backend/tests/test_demo_auth.py Backend/tests/test_demo_quota_service.py Backend/tests/test_rag_retriever_degradation.py Backend/tests/test_rag_metadata_filters.py Backend/tests/test_rag_spatial_filters.py Backend/tests/test_api_contract_models.py Backend/tests/test_api_contract_openapi.py --basetemp .codex_tmp/pytest-g0-targeted -p no:cacheprovider
```

Expected: `46 passed`。

## Task 1：用测试冻结 G0 旧链路

**Files:**

- Create: `Backend/tests/test_agent_native_g0_contract.py`
- Create: `docs/agent-native/G0_BASELINE.md`

- [ ] **Step 1: 写入 G0 契约测试**

```python
from __future__ import annotations

from pathlib import Path

import main

from app.models.search_models import SearchResponse
from app.services.search_service import SearchService


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_query_routes_remain_registered() -> None:
    paths = main.app.openapi()["paths"]

    assert "post" in paths["/api/search/query"]
    assert "post" in paths["/api/search/query/stream"]


def test_legacy_stream_route_remains_event_stream() -> None:
    stream = main.app.openapi()["paths"]["/api/search/query/stream"]["post"]

    assert "text/event-stream" in stream["responses"]["200"]["content"]


def test_frontend_chat_service_still_targets_legacy_query() -> None:
    source = (ROOT / "frontend/src/services/chatService.ts").read_text(encoding="utf-8")

    assert "apiPost('/api/search/query'" in source
    assert "/api/agent/query/stream" not in source


def test_map_action_contract_remains_frozen() -> None:
    answer = 'Answer.\n```json\n{"adcode":"510000","name":"Sichuan"}\n```'

    purified, action = SearchService.extract_map_action(answer)
    response = SearchResponse(query="locate", generated_answer=purified, map_action=action)

    assert response.generated_answer == "Answer."
    assert response.map_action is not None
    assert response.map_action.adcode == "510000"
```

- [ ] **Step 2: 运行测试并确认它描述当前基线**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_agent_native_g0_contract.py -v --basetemp .codex_tmp/pytest-g0-contract -p no:cacheprovider
```

Expected: 4 passed。G0 是行为刻画测试，允许首次即通过；它不对应新增生产行为。

- [ ] **Step 3: 写入基线文档**

`docs/agent-native/G0_BASELINE.md` 必须包含：

```markdown
# Agent-Native V3 G0 Baseline

## Frozen behavior

- Backend chat remains on `POST /api/search/query`.
- Legacy streaming remains on `POST /api/search/query/stream` with `text/event-stream`.
- Frontend `chatService` still calls `/api/search/query`.
- Structured `map_action` and legacy markdown JSON extraction remain regression behavior until G7.
- Agent Runtime mode defaults to `legacy`; no automatic fallback may combine two knowledge sources.

## Verified on 2026-09-10

- Backend full suite: `85 passed`.
- Backend focused chat/search/auth/quota suite: `46 passed`.
- Frontend test scripts: passed.
- Frontend lint/type/contract checks: passed.
- Frontend production build: passed.

## Existing non-blocking warnings

- Pydantic class-based config deprecation.
- UTC-naive datetime deprecation in existing auth/document code.
- Vite bundle-size warning.

The full backend suite must use a writable `--basetemp` and `-p no:cacheprovider` in the managed Windows sandbox.
```

- [ ] **Step 4: 提交 G0 基线**

```powershell
git add Backend/tests/test_agent_native_g0_contract.py docs/agent-native/G0_BASELINE.md
git commit -m "test: freeze agent-native g0 baseline"
```

## Task 2：为 Agent Runtime 模式建立 RED 测试

**Files:**

- Create: `Backend/tests/test_agent_native_feature_flag.py`
- Modify: `Backend/app/core/config.py`

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_agent_runtime_mode_defaults_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_RUNTIME_MODE", raising=False)

    assert Settings(_env_file=None).AGENT_RUNTIME_MODE == "legacy"


@pytest.mark.parametrize("mode", ["legacy", "agent"])
def test_agent_runtime_mode_accepts_supported_values(mode: str) -> None:
    assert Settings(_env_file=None, AGENT_RUNTIME_MODE=mode).AGENT_RUNTIME_MODE == mode


def test_agent_runtime_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, AGENT_RUNTIME_MODE="proxy")
```

- [ ] **Step 2: 运行并确认 RED**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_agent_native_feature_flag.py -v --basetemp .codex_tmp/pytest-agent-mode-red -p no:cacheprovider
```

Expected: FAIL，原因是 `Settings` 尚无 `AGENT_RUNTIME_MODE` 或未知值未被拒绝。

- [ ] **Step 3: 添加最小配置实现**

在 `Backend/app/core/config.py` 的应用基础配置后加入：

```python
from typing import Literal
```

并在 `Settings` 中加入：

```python
    AGENT_RUNTIME_MODE: Literal["legacy", "agent"] = "legacy"
```

- [ ] **Step 4: 运行并确认 GREEN**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_agent_native_feature_flag.py Backend/tests/test_agent_native_g0_contract.py -v --basetemp .codex_tmp/pytest-agent-mode-green -p no:cacheprovider
```

Expected: 8 passed；旧路由和前端目标不变。

- [ ] **Step 5: 提交 feature flag**

```powershell
git add Backend/app/core/config.py Backend/tests/test_agent_native_feature_flag.py
git commit -m "feat: add agent runtime migration mode"
```

## Task 3：用测试定义 source manifest

**Files:**

- Create: `Backend/tests/test_agent_native_source_manifest.py`
- Create: `docs/upstream-sources/agent-native-v3.toml`
- Create: `docs/upstream-sources/README.md`

- [ ] **Step 1: 写失败的 manifest 契约测试**

```python
from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/upstream-sources/agent-native-v3.toml"


def _manifest() -> dict:
    with MANIFEST.open("rb") as stream:
        return tomllib.load(stream)


def _source(source_id: str) -> dict:
    return next(item for item in _manifest()["sources"] if item["id"] == source_id)


def test_manifest_records_owner_authorization_and_frozen_commits() -> None:
    data = _manifest()

    assert data["schema_version"] == 1
    assert data["authorized_by"] == "edjsh175"
    assert _source("agentic-rag")["commit"] == "2eab8d5c479ba32c27b7c929a35c273edf0a2f64"
    assert _source("gis-agent-core")["commit"] == "ee3d30667fbd0b970633d32265f97c6d147c35c1"


def test_manifest_forbids_runtime_imports_from_external_paths() -> None:
    data = _manifest()

    assert data["policy"]["upstream_read_only"] is True
    assert data["policy"]["external_runtime_imports"] is False
    assert data["policy"]["whole_repository_copy"] is False


def test_agentic_runtime_inventory_contains_full_responsibility_chain() -> None:
    candidates = set(_source("agentic-rag")["candidate_files"])

    required = {
        "rag_knowledge/services/agent_orchestration/runtime.py",
        "rag_knowledge/services/agent_orchestration/models.py",
        "rag_knowledge/services/conversation_context.py",
        "rag_knowledge/services/dialogue_understanding.py",
        "rag_knowledge/services/knowledge_search.py",
        "rag_knowledge/services/graph_retrieval.py",
        "rag_knowledge/services/evidence_pack.py",
        "rag_knowledge/services/answer_finalizer.py",
        "rag_knowledge/services/helper_grounding_reviewer.py",
        "rag_knowledge/services/qa_trace.py",
    }
    assert required <= candidates


def test_gis_inventory_is_minimal_and_excludes_harness_features() -> None:
    source = _source("gis-agent-core")
    candidates = set(source["candidate_files"])

    assert "src/gis/runtime/createMapRuntime.js" in candidates
    assert "src/gis/integration/featureReferenceStore.js" in candidates
    assert "src/gis/integration/createMapContext.js" in candidates
    assert all(not PurePosixPath(path).is_absolute() for path in candidates)
    assert all(not path.startswith(("harness/", "src/gis/user-vector/")) for path in candidates)
    assert "harness/" in source["excluded_prefixes"]
    assert "src/gis/user-vector/" in source["excluded_prefixes"]
```

- [ ] **Step 2: 运行并确认 RED**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_agent_native_source_manifest.py -v --basetemp .codex_tmp/pytest-manifest-red -p no:cacheprovider
```

Expected: FAIL with `FileNotFoundError` for `agent-native-v3.toml`。

- [ ] **Step 3: 写最小 source manifest**

```toml
schema_version = 1
authorized_by = "edjsh175"
authorization = "Owner-approved selective migration into GeoAI"
target_repository = "geo-rag-planning-assistant"

[policy]
upstream_read_only = true
external_runtime_imports = false
whole_repository_copy = false
sync_requires_diff_review = true

[[sources]]
id = "agentic-rag"
repository_url = "git@github.com:edjsh175/agentic-rag.git"
local_path = 'D:\work\Project\agentic rag'
commit = "2eab8d5c479ba32c27b7c929a35c273edf0a2f64"
target_root = "Backend/agent_runtime"
license_basis = "repository-owner-authorization"
candidate_files = [
  "rag_knowledge/services/agent_orchestration/__init__.py",
  "rag_knowledge/services/agent_orchestration/models.py",
  "rag_knowledge/services/agent_orchestration/runtime.py",
  "rag_knowledge/services/agent_orchestration/graph_working_set.py",
  "rag_knowledge/services/agent_orchestration/evidence_gate.py",
  "rag_knowledge/services/agent_orchestration/gap_support.py",
  "rag_knowledge/services/conversation_context.py",
  "rag_knowledge/services/dialogue_understanding.py",
  "rag_knowledge/services/identity_scope.py",
  "rag_knowledge/services/entity_candidate_resolver.py",
  "rag_knowledge/services/query_clarification.py",
  "rag_knowledge/services/query_contextualizer.py",
  "rag_knowledge/services/query_planner.py",
  "rag_knowledge/services/exploration_grant.py",
  "rag_knowledge/services/knowledge_search.py",
  "rag_knowledge/services/text_evidence_admission.py",
  "rag_knowledge/services/retrieval_scope.py",
  "rag_knowledge/services/retrieval_intent.py",
  "rag_knowledge/services/retrieval_strategy.py",
  "rag_knowledge/services/retrieval_quality.py",
  "rag_knowledge/services/graph_retrieval.py",
  "rag_knowledge/services/graph_traversal.py",
  "rag_knowledge/services/evidence_pack.py",
  "rag_knowledge/services/evidence_scope.py",
  "rag_knowledge/services/answer_finalizer.py",
  "rag_knowledge/services/helper_grounding_reviewer.py",
  "rag_knowledge/services/model_stream_runner.py",
  "rag_knowledge/services/execution_explanation.py",
  "rag_knowledge/services/qa_trace.py",
  "rag_knowledge/services/runtime_evidence_provider.py",
  "rag_knowledge/repository/vector_store.py",
  "rag_knowledge/repository/relational_db.py",
  "rag_knowledge/config.py",
  "rag_knowledge/llm_http.py",
  "rag_knowledge/ollama_http.py",
]
excluded_prefixes = [
  "gpu_agent/",
  "web/",
  "web2/",
  "rag_knowledge/mcp/",
  "rag_knowledge/evaluation/",
]

[[sources]]
id = "gis-agent-core"
repository_url = "https://github.com/edjsh175/gis-agent-core.git"
local_path = 'D:\work\Project\gis-agent-core'
commit = "ee3d30667fbd0b970633d32265f97c6d147c35c1"
target_root = "frontend/src/gis-agent"
license_basis = "MIT-and-repository-owner-authorization"
candidate_files = [
  "src/gis/contracts.js",
  "src/gis/runtime/createMapRuntime.js",
  "src/gis/integration/contracts.js",
  "src/gis/integration/featureReferenceStore.js",
  "src/gis/integration/createMapContext.js",
  "src/gis/client/createClientCapabilities.js",
  "src/gis/adapters/openlayersAdapter.js",
]
excluded_prefixes = [
  "harness/",
  "src/gis/user-vector/",
  "src/business-artifacts/",
]
```

- [ ] **Step 4: 写入同步规则文档**

`docs/upstream-sources/README.md`：

```markdown
# Upstream source policy

GeoAI uses a Fork at Integration Boundary:

1. Freeze an upstream commit and keep the upstream worktree read-only.
2. Record candidate and migrated files in `agent-native-v3.toml`.
3. Copy only a dependency-reviewed responsibility closure into GeoAI.
4. Adapt and evolve only the GeoAI-owned copy.
5. For an upstream update, record the new commit, review the diff, selectively sync, and rerun parity tests.

Runtime code must never import `D:\work\Project\agentic rag` or `D:\work\Project\gis-agent-core`. Harness, user-vector, business-artifact, MCP, web UI, and evaluation modules stay out unless a later approved phase changes scope.
```

- [ ] **Step 5: 运行并确认 GREEN**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_agent_native_source_manifest.py -v --basetemp .codex_tmp/pytest-manifest-green -p no:cacheprovider
```

Expected: 4 passed。

- [ ] **Step 6: 提交 manifest 契约**

```powershell
git add Backend/tests/test_agent_native_source_manifest.py docs/upstream-sources/agent-native-v3.toml docs/upstream-sources/README.md docs/superpowers/specs/2026-09-10-agent-native-g0-g1-design.md
git commit -m "docs: freeze agent-native upstream sources"
```

## Task 4：测试先行实现 provenance verifier

**Files:**

- Create: `Backend/tests/test_verify_agent_native_sources.py`
- Create: `Backend/scripts/verify_agent_native_sources.py`

- [ ] **Step 1: 写 verifier 的失败测试**

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.verify_agent_native_sources import load_manifest, validate_manifest, verify_source


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def frozen_source(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "GeoAI Tests")
    source_file = repo / "runtime.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "runtime.py")
    _git(repo, "commit", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_validate_manifest_rejects_external_runtime_imports() -> None:
    errors = validate_manifest(
        {
            "schema_version": 1,
            "authorized_by": "edjsh175",
            "policy": {
                "upstream_read_only": True,
                "external_runtime_imports": True,
                "whole_repository_copy": False,
            },
            "sources": [],
        }
    )

    assert "external_runtime_imports must be false" in errors


def test_verify_source_accepts_clean_frozen_commit(frozen_source: tuple[Path, str]) -> None:
    repo, commit = frozen_source
    source = {
        "id": "fixture",
        "local_path": str(repo),
        "commit": commit,
        "candidate_files": ["runtime.py"],
        "excluded_prefixes": ["harness/"],
    }

    assert verify_source(source) == []


def test_verify_source_rejects_dirty_worktree(frozen_source: tuple[Path, str]) -> None:
    repo, commit = frozen_source
    (repo / "runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    source = {
        "id": "fixture",
        "local_path": str(repo),
        "commit": commit,
        "candidate_files": ["runtime.py"],
        "excluded_prefixes": [],
    }

    assert "fixture: worktree is not clean" in verify_source(source)


def test_load_manifest_reads_toml(tmp_path: Path) -> None:
    path = tmp_path / "source.toml"
    path.write_text('schema_version = 1\nauthorized_by = "edjsh175"\n', encoding="utf-8")

    assert load_manifest(path)["authorized_by"] == "edjsh175"
```

- [ ] **Step 2: 运行并确认 RED**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_verify_agent_native_sources.py -v --basetemp .codex_tmp/pytest-verifier-red -p no:cacheprovider
```

Expected: collection ERROR，因为 `scripts.verify_agent_native_sources` 尚不存在。

- [ ] **Step 3: 实现最小 verifier**

```python
from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not manifest.get("authorized_by"):
        errors.append("authorized_by is required")
    policy = manifest.get("policy", {})
    if policy.get("upstream_read_only") is not True:
        errors.append("upstream_read_only must be true")
    if policy.get("external_runtime_imports") is not False:
        errors.append("external_runtime_imports must be false")
    if policy.get("whole_repository_copy") is not False:
        errors.append("whole_repository_copy must be false")
    if not manifest.get("sources"):
        errors.append("at least one source is required")
    return errors


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def verify_source(source: dict[str, Any]) -> list[str]:
    source_id = str(source.get("id", "unknown"))
    repo = Path(str(source.get("local_path", "")))
    commit = str(source.get("commit", ""))
    errors: list[str] = []
    if not repo.is_dir():
        return [f"{source_id}: source repository not found: {repo}"]
    if _git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode != 0:
        errors.append(f"{source_id}: frozen commit does not exist")
    status = _git(repo, "status", "--porcelain", check=False)
    if status.returncode != 0 or status.stdout.strip():
        errors.append(f"{source_id}: worktree is not clean")
    for candidate in source.get("candidate_files", []):
        path = PurePosixPath(candidate)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"{source_id}: invalid candidate path: {candidate}")
            continue
        exists = _git(repo, "cat-file", "-e", f"{commit}:{candidate}", check=False)
        if exists.returncode != 0:
            errors.append(f"{source_id}: candidate missing at frozen commit: {candidate}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    errors = validate_manifest(manifest)
    for source in manifest.get("sources", []):
        errors.extend(verify_source(source))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("agent-native upstream sources verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行并确认 GREEN**

Run:

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_verify_agent_native_sources.py -v --basetemp .codex_tmp/pytest-verifier-green -p no:cacheprovider
```

Expected: 4 passed。

- [ ] **Step 5: 对两个真实只读上游运行 verifier**

Run:

```powershell
Backend\.venv\Scripts\python.exe Backend/scripts/verify_agent_native_sources.py --manifest docs/upstream-sources/agent-native-v3.toml
```

Expected: `agent-native upstream sources verified`，exit 0；两个源仓库保持 clean 且 HEAD 未改变。

- [ ] **Step 6: 提交 verifier**

```powershell
git add Backend/scripts/verify_agent_native_sources.py Backend/tests/test_verify_agent_native_sources.py
git commit -m "feat: verify agent-native upstream provenance"
```

## Task 5：G0-G1a 最终验证与阶段出口

- [ ] **Step 1: 运行新增目标测试**

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests/test_agent_native_g0_contract.py Backend/tests/test_agent_native_feature_flag.py Backend/tests/test_agent_native_source_manifest.py Backend/tests/test_verify_agent_native_sources.py -v --basetemp .codex_tmp/pytest-g1a-targeted -p no:cacheprovider
```

Expected: 16 passed。

- [ ] **Step 2: 运行完整后端回归**

```powershell
Backend\.venv\Scripts\python.exe -m pytest Backend/tests --basetemp .codex_tmp/pytest-g1a-full -p no:cacheprovider
```

Expected: 原 85 项 + 新 16 项全部通过；准确总数以 pytest collection 为准，无 error/failure。

- [ ] **Step 3: 运行前端回归**

```powershell
Set-Location frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

Expected: tests、lint、build 均 exit 0。

- [ ] **Step 4: 验证上游未被修改且 GeoAI 无外部运行时 import**

```powershell
git -C "D:\work\Project\agentic rag" status --short
git -C "D:\work\Project\agentic rag" rev-parse HEAD
git -C "D:\work\Project\gis-agent-core" status --short
git -C "D:\work\Project\gis-agent-core" rev-parse HEAD
rg -n "D:\\\\work\\\\Project\\\\(agentic rag|gis-agent-core)" Backend frontend -g "!*.md"
```

Expected: 两个 status 无输出；commit 分别为 `2eab8d5c479ba32c27b7c929a35c273edf0a2f64` 和 `ee3d30667fbd0b970633d32265f97c6d147c35c1`；`rg` 无生产代码匹配。

- [ ] **Step 5: 检查 diff 并提交阶段记录**

```powershell
git diff --check
git status --short
```

Expected: 仅存在本计划列出的预期文件，无空白错误。若验证产生额外记录，只提交明确属于 G0-G1a 的文件。

- [ ] **Step 6: 进入下一阶段**

G0-G1a 完成后，为 G1b 创建独立设计/计划：只迁入 deterministic Agent Runtime 协议闭包（orchestration models/runtime、conversation context、evidence gate、gap support、graph working set），以注入式 `decide_fn` 和 handlers 验证 Controller、预算、EvidencePool 与事件顺序；不提前接真实数据库、LLM、GIS 或前端。
