# GeoRAG GIS Observation, Spatial Tools and Evaluation Design

## 1. Goal

Close the remaining gap between the GeoAI project description and the implemented system without inventing benchmark numbers.

The implementation must make these statements true and inspectable:

1. the Agent can observe the complete active OpenLayers layer tree;
2. imported vector features have stable `feature_ref` identities for the lifetime of the browser GIS runtime;
3. feature properties and exact geometry are available through bounded browser tools instead of being dumped into every `MapContext`;
4. PostGIS spatial relation and overlay operations are first-class Agent tools;
5. browser and PostGIS tool facts can become frozen evidence for final publication;
6. the repository contains a 36-task evaluation suite and a runner that reports measured task completion only from executed results.

## 2. First-principles boundaries

### 2.1 Browser owns browser state

OpenLayers remains authoritative for viewport, layer visibility, user-vector objects and imported feature identity. The backend never reconstructs OpenLayers objects.

`MapContext` contains bounded state that is useful on every Controller step:

- viewport;
- supported tools;
- available browser files;
- all current map layers as a recursive layer tree;
- compact user-layer summaries.

Feature properties and full geometries are not copied into every `MapContext`. They are retrieved on demand by browser tools.

### 2.2 Stable references are lifecycle identities

- `file_ref` identifies browser-local input data;
- `layer_ref` identifies an imported user vector layer;
- `feature_ref` identifies one feature inside that runtime-owned layer.

The mapping is created once during import and retained until the GIS runtime is disposed. Tool calls never depend on JavaScript object addresses or array indexes.

### 2.3 Tool output is factual evidence, not a second answer path

Successful and failed browser receipts and deterministic PostGIS results are external facts. They are admitted into the session `EvidenceLedger` as observation evidence. Final natural-language publication still goes through:

`Controller -> compose_answer -> Frozen Evidence -> Answer Generator -> optional Reviewer -> Publication`.

This prevents GIS tools from creating a second ungrounded publication path.

### 2.4 Spatial semantics stay in PostGIS

The Agent chooses the semantic operation. PostGIS executes geometry predicates and overlays through parameterized SQL. Runtime code does not infer whether two geometries are related.

Supported first-class operations:

- relation: `intersects`, `within`, `contains`, `overlaps`, `disjoint`, `touches`;
- overlay: `intersection`, `union`, `difference`.

Each operand is either:

- a GeoJSON geometry obtained from browser observation; or
- a `spatial_regions` entity resolved by `adcode` or exact `region_name`.

No graph database is introduced. “Entity relation” here means authoritative spatial relation between GIS entities, which is the relation model this project actually owns.

## 3. Browser contract

`BrowserMapContext.schema_version` becomes `2` and gains `layer_tree`.

Each layer node contains:

- stable runtime `layer_ref`;
- optional parent reference;
- name;
- kind (`base`, `annotation`, `business`, `user_vector`, `group`, `unknown`);
- visibility;
- opacity;
- z-index;
- optional child nodes.

User-vector import additionally creates feature identities. The compact layer summary exposes at most the first ten `feature_ref` values so the Controller has a discoverable entry point.

Two bounded browser tools are added:

- `inspect_layer_features(layer_ref, offset, limit)` returns feature refs, geometry type and properties for at most 50 features;
- `get_feature_geometry(feature_ref)` returns the exact GeoJSON geometry and properties for one feature.

## 4. Evidence admission

`EvidenceLedger` gains one deterministic observation-admission method. Observation evidence is immutable and deduplicated from:

- session id;
- source;
- stable observation key;
- content hash.

Browser receipts are admitted on continuation before the next Controller decision. PostGIS tool results are admitted inside `ToolRuntime` and their `evidence_id` is returned in the tool observation.

## 5. PostGIS Agent tools

The existing `SpatialService` becomes the single owner of relation and overlay SQL.

`ToolRuntime` receives the service through dependency injection. The default Agent construction in `search_routes.py` provides it. Tests and alternate runtimes may omit it; selecting a spatial tool without a configured service yields a failed observation rather than a process crash.

Spatial result text written into the Evidence Ledger is deterministic JSON so Answer Generator citations can point to the exact operation result.

## 6. Evaluation

The repository gains exactly 36 evaluation scenarios covering:

- knowledge-only retrieval;
- browser file import;
- multi-step layer operations;
- viewport location;
- feature observation and feature reference reuse;
- PostGIS relation/overlay use;
- failure observation and recovery.

The evaluator consumes actual scenario result records and calculates:

- completed tasks;
- total tasks;
- task-completion rate;
- per-category completion;
- failure reasons.

The runner must reject missing, duplicate or unknown scenario ids. It must not contain hard-coded `91.7%` or `94.4%`. Those values may only appear later if a real run produces them.

## 7. Acceptance criteria

1. `MapContext` exposes all active OpenLayers layers, not only Agent-created user layers.
2. A feature imported once keeps the same `feature_ref` across later inspect/geometry tool calls.
3. A successful or failed browser operation can be frozen and cited without a KB retrieval.
4. PostGIS relation/overlay calls are parameterized and reachable from the same Controller tool registry as RAG/browser tools.
5. The 36-task manifest is machine validated as exactly 36 unique tasks.
6. Any reported score is generated from result records, never written into README/source as an unsupported claim.
