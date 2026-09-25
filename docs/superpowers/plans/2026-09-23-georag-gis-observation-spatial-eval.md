# GeoRAG GIS Observation, Spatial Tools and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make full map-layer observation, stable feature references, Agent-accessible PostGIS spatial operations and a real 36-task evaluation contract part of the existing GeoRAG Agent runtime.

**Architecture:** OpenLayers stays authoritative for browser state and feature identity; expensive feature detail is read through bounded browser tools. Browser/PostGIS facts enter the existing Evidence Ledger so final publication still uses Frozen Evidence. PostGIS operations are injected into the existing ToolRuntime rather than creating a second Agent or spatial planner.

**Tech Stack:** TypeScript 5.8, OpenLayers 10.8, React 19, Python 3.12, FastAPI, Pydantic v2, SQLAlchemy Async, PostgreSQL/PostGIS, pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-georag-gis-observation-spatial-eval-design.md`

## Global Constraints

- Do not introduce a graph database.
- Do not dump all feature properties/geometries into every `MapContext`.
- Do not add a GIS-specific publication bypass around Frozen Evidence.
- Do not hard-code benchmark percentages.
- Reuse the current Browser Bridge continuation and ToolRuntime ownership boundaries.

---

### Task 1: Browser layer and feature observation contract

**Files:**
- Modify: `frontend/src/gis/contracts.ts`
- Modify: `frontend/src/gis/openlayersAdapter.ts`
- Modify: `frontend/src/gis/userVectorCapabilities.ts`
- Modify: `frontend/src/gis/mapContext.ts`
- Modify: `frontend/src/gis/createBrowserGisRuntime.ts`
- Modify: `frontend/src/gis/frontendExecutor.ts`
- Modify: `frontend/src/components/OpenLayersMap.tsx`

**Interfaces:**
- Produces: `LayerTreeNode`, `FeatureObservation`, schema-v2 `BrowserMapContext`.
- Produces: `capabilities.inspectFeatures({layer_ref, offset, limit})` and `capabilities.getFeatureGeometry({feature_ref})`.
- Produces: browser actions `inspect_layer_features` and `get_feature_geometry`.

- [ ] Add contract types for recursive `layer_tree`, compact feature refs and bounded feature observations.
- [ ] Assign metadata to system layers at map construction and make `mapContext` recursively enumerate the complete OpenLayers layer collection.
- [ ] Create one stable `feature_ref` for every imported OpenLayers feature and index it inside `createUserVectorCapabilities`.
- [ ] Add bounded feature inspection (`limit <= 50`) and exact single-feature geometry retrieval.
- [ ] Route the two new actions through `FrontendExecutor`.
- [ ] Run `npm run lint` from `frontend` and fix type/contract errors.

### Task 2: Observation facts use the existing Evidence Ledger

**Files:**
- Modify: `Backend/app/services/agent/evidence.py`
- Modify: `Backend/app/services/agent/runtime.py`
- Modify: `Backend/tests/test_agent_evidence_lifecycle.py`
- Modify: `Backend/tests/test_agent_runtime.py`

**Interfaces:**
- Produces: `EvidenceLedger.add_observation(...) -> EvidenceItem`.
- Consumes: browser `BrowserToolReceipt` already validated by `AgentRuntime`.

- [ ] Add deterministic observation admission using source, observation key and content hash.
- [ ] Admit every validated browser receipt before the resumed Controller step, including failed receipts.
- [ ] Ensure admitted receipt evidence is active for the current logical turn and appears in the Controller working evidence catalogue.
- [ ] Add focused regression coverage proving a browser-only turn can freeze receipt evidence.

### Task 3: PostGIS relation and overlay Agent tools

**Files:**
- Modify: `Backend/app/services/spatial_service.py`
- Modify: `Backend/app/services/agent/tools.py`
- Modify: `Backend/app/services/agent/tool_runtime.py`
- Modify: `Backend/app/services/agent/runtime.py`
- Modify: `Backend/app/api/search_routes.py`
- Modify: `Backend/tests/test_agent_tool_runtime.py`

**Interfaces:**
- Produces: `SpatialService.query_relation(left, right, relation)`.
- Produces: `SpatialService.overlay(left, right, operation)`.
- Produces Agent tools: `query_spatial_relation`, `spatial_overlay`.
- Each successful spatial operation activates one Evidence Ledger observation and returns its `evidence_id`.

- [ ] Add Pydantic contracts for geometry or `spatial_regions` operands and the relation/overlay tool inputs.
- [ ] Resolve region operands by parameterized `adcode` or exact `region_name`; resolve geometry operands with `ST_GeomFromGeoJSON` and SRID 4326.
- [ ] Execute relation predicates and overlay operations through parameterized PostGIS SQL and return deterministic JSON-compatible result objects.
- [ ] Inject `SpatialService` into `AgentRuntime -> ToolRuntime`; keep it optional for isolated tests.
- [ ] Convert service failure into a non-terminal failed ToolObservation so Controller can recover or stop.
- [ ] Admit successful spatial results into Evidence Ledger and expose the evidence id to Controller.
- [ ] Run the focused Agent tool/runtime pytest files.

### Task 4: Controller catalogue and browser tools

**Files:**
- Modify: `Backend/app/services/agent/tools.py`
- Modify: `Backend/app/services/agent/tool_runtime.py`
- Modify: `frontend/src/gis/mapContext.ts`

**Interfaces:**
- Consumes all new browser/spatial tool contracts from Tasks 1 and 3.
- Produces one default ToolRegistry used by MainController and ToolRuntime.

- [ ] Register `inspect_layer_features` and `get_feature_geometry` as browser-executed tools.
- [ ] Register `query_spatial_relation` and `spatial_overlay` as server-executed tools.
- [ ] Ensure `supported_tools` in `MapContext` matches the browser-executable subset exactly.
- [ ] Verify the same registry names are accepted by MainController and ToolRuntime.

### Task 5: 36-task evaluation contract

**Files:**
- Create: `evals/geoai_agent_36_tasks.json`
- Create: `scripts/evaluate_geoai_agent_results.py`
- Create: `Backend/tests/test_geoai_agent_eval_contract.py`
- Modify: `README.md`

**Interfaces:**
- Manifest: exactly 36 unique `{id, category, prompt, required_capabilities, success_criteria}` records.
- Runner input: JSON array of `{id, completed, failure_reason?, evidence?}`.
- Runner output: JSON summary with completed/total/rate/per_category/failures.

- [ ] Add 36 concrete tasks spanning knowledge, import, layer control, locate, feature observation, spatial analysis and failure recovery.
- [ ] Implement strict manifest/result validation and measured completion aggregation.
- [ ] Add a test that fails if task count is not 36, ids are duplicated, or a result set is incomplete.
- [ ] Update README to describe the evaluation suite without claiming a score that has not been run.
- [ ] Run the evaluation contract test and, if actual result records are available, run the evaluator to produce the measured score.

### Task 6: Integration verification and closure

**Files:** all files changed by Tasks 1-5.

**Interfaces:** final repository state only.

- [ ] Run frontend static verification (`npm run lint`, then `npm run build`).
- [ ] Run focused backend tests for Agent evidence, runtime, tool runtime and evaluation contract.
- [ ] Inspect `git diff --check`, `git status`, and the combined diff for dead code or duplicated ownership.
- [ ] Commit the isolated worktree changes with a single coherent feature commit after verification.
- [ ] Do not claim an E2E percentage unless the 36 scenario result records were actually executed and evaluated.
