# GeoAI 行政区选中、标准适用范围与空间信息融合 PRD

- **Document status**：IN_PROGRESS / Phase 0–4 核心实现完成，Phase 5 的真实模型 2D/3D 主链路已通过；其余验收项待验证
- **日期**：2026-10-02
- **目标仓库**：GeoAI
- **适用范围**：Browser GIS Runtime、Agent Tool Calling、RAG Retrieval、PostGIS、标准元数据、Linear / Agent 查询链路
- **优先级**：P0
- **实施原则**：第一性原则、最小充分原则、复用优先、单事实源、先约束候选再排序、可验证而非提示词补丁

---

## 1. 背景与用户目标

当前需求不是单纯增加一个“飞到四川”的地图动作，而是建立真正的**空间信息融合闭环**。

用户有两种等价入口：

### 入口 A：手动选区

```text
用户点击四川省
  ↓
四川高亮成为当前 active_region
  ↓
不自动发起问答
  ↓
用户下一次提问
  ↓
知识检索默认受到“四川适用范围”约束
```

例如：

```text
用户手动选中四川
用户：查一下地质灾害监测相关标准
```

系统应只从**空间适用范围覆盖四川**的标准集合中继续做主题检索和排序。

### 入口 B：Agent 自动选区

```text
用户：查一下四川的标准
  ↓
Controller 识别“需要切换当前行政区”
  ↓
select_region("四川")
  ↓
后端确定性解析为四川省 / 510000
  ↓
浏览器真正选中、高亮四川
  ↓
Browser Receipt 返回新的 active_region
  ↓
同一 Turn 继续执行区域标准查询
```

这里的关键要求是：

> **Agent 不能只移动视角；必须改变真实的地图选中状态，使手动选中与 Agent 选中走同一个 active_region 状态。**

同时，“四川的标准”不能只理解为 `DB51*` 地方标准，还必须覆盖**在四川具有空间适用性的国家标准、行业标准以及四川地方标准**。

---

# 2. 第一性原则

## 2.1 最终目标

空间信息融合的本质不是“给 RAG 再加一个地区关键词”，而是建立一个可验证的业务约束：

```text
最终候选标准
=
主题相关
∩ 当前有效
∩ 空间适用范围覆盖目标区域
∩ 数据库中已纳入的标准集合
```

其中：

- **地图负责产生“用户当前选中了哪里”这一事实**；
- **PostGIS / 标准适用范围数据负责判断哪些标准在空间上有资格进入候选集**；
- **RAG 负责在合格标准内部找与问题最相关的条款**；
- **LLM 负责语义决策和工作流编排，不负责伪造空间事实。**

## 2.2 不可变约束

1. `active_region` 的当前值以 Browser GIS Runtime 为权威来源；
2. 手动选区与 Agent 选区必须写入同一个 `useMapStore.activeRegion`，不得产生第二套“AgentSelectedRegion”；
3. `locate_map` 只代表视角移动，不能继续冒充行政区选中；
4. Agent 不得自行编造 adcode，区域名称必须经过现有 `SpatialService.resolve_region()` 确定性解析；
5. `spatial_filter` 与“标准空间适用范围”是两个不同概念，不得继续混用；
6. 标准适用范围必须在 RAG Candidate Retrieval **之前**成为候选资格约束，不能只在 Top-K 之后做过滤；
7. 国家 / 行业标准不能因为不是 `DB51` 而被排除；
8. “全部标准 / 有哪些 / 数量”属于确定性目录查询，不能用向量检索 Top-K 冒充全集；
9. `application_scope` 原始文本可以作为证据来源，但不能直接把自然语言字符串当空间事实；
10. 不允许新增第二个 Agent Runtime、第二套地图状态或第二套 Tool Calling 协议；
11. Linear 与 Agent 两条链路消费同一套区域适用性服务；
12. 数据无法证明完整覆盖时，系统必须明确说“库内已判定/已核验范围”，不得宣称现实世界中的“全部标准”。

---

# 3. 当前实现事实审计

## 3.1 当前已经存在的地图选区事实源

已有权威状态：

- `frontend/src/store/useMapStore.ts`
  - `activeRegion: { adcode, name } | null`
  - `setActiveRegion()`
  - `resetView()`
- `frontend/src/components/OpenLayersMap.tsx`
  - 用户点击省份后执行 `setActiveRegion({ adcode, name })`
  - 当前省份真正高亮
- `frontend/src/components/CesiumGlobe.tsx`
  - 同样订阅 `activeRegion`
  - 根据 adcode 高亮区域

因此：

> **新的功能不需要再设计“选中区域状态”；已有 `activeRegion` 就是正确的 Browser 单事实源。**

## 3.2 当前 Map Context 已经携带 active_region

已有：

- `frontend/src/gis/mapContext.ts`
- `frontend/src/gis/cesiumRuntime.ts`
- `frontend/src/services/chatService.ts`

当前每次请求已经可以发送：

```json
{
  "map_context": {
    "active_region": {
      "adcode": "510000",
      "name": "四川省"
    }
  }
}
```

后端：

- `Backend/app/services/agent/context/admission.py`

已经会清洗和接纳 `active_region`。

因此当前链路已经完成：

```text
Browser activeRegion
  ↓
map_context.active_region
  ↓
Backend Agent Context
  ↓
Controller 可见
```

**真正缺失的是从这个事实继续投影到 Retrieval Scope。**

## 3.3 当前 locate_map 只有“移动视角”语义

已有：

- `Backend/app/services/agent/tools.py::LocateMapInput`
- `Backend/app/services/agent/tool_runtime.py`
- `frontend/src/gis/frontendExecutor.ts`
- `frontend/src/gis/cesiumRuntime.ts`

`locate_map` 输入为：

```text
longitude
latitude
zoom
```

执行结果只是：

```text
camera / viewport move
```

不会改变：

```text
useMapStore.activeRegion
```

所以当前出现：

```text
Agent：定位四川
  ↓
地图飞过去
  ↓
四川没有成为 selected / highlighted region
  ↓
下一轮 map_context.active_region 仍为空或旧值
```

这不是提示词问题，而是**缺少一个物理能力 `select_region`**。

## 3.4 当前 active_region 没有成为 RAG 约束

当前：

- `SearchRequest.spatial_filter`
- `SearchApplicationService._retrieval_constraints()`

只会把显式 `request.spatial_filter` 复制到：

```text
RetrievalRequestConstraints.spatial_filter
```

而：

```text
map_context.active_region
```

只是 Controller 可见上下文，并不会自动变成检索约束。

所以手动选中四川后，虽然前端请求里已经有四川：

```text
active_region = 四川
```

`retrieve_kb` 仍然可能进行全国范围普通 RAG。

## 3.5 当前空间过滤发生得太晚

`Backend/app/services/rag/postgres_adapter.py` 当前执行顺序为：

```text
exact
keyword
vector
  ↓
RRF fuse / candidate_k
  ↓
apply_spatial_filter
  ↓
rerank
```

因此空间条件只是对**已经召回的有限候选**进行二次过滤。

如果一个四川适用标准没有先进入 `candidate_k`，后续空间过滤永远没有机会看到它。

对于“区域适用标准”这一类**候选资格约束**，正确顺序必须是：

```text
区域适用性约束
  ↓
在合法标准集合中 exact / keyword / vector
  ↓
RRF
  ↓
rerank
```

## 3.6 当前 region prefix 方案只能覆盖地方标准

`Backend/app/services/rag/filters.py` 当前存在：

```text
四川省 -> DB51
北京市 -> DB11
...
```

当文档没有几何时，空间过滤最终会退化为：

```text
standard_code.startswith("DB51")
```

这只能表达：

> “这是四川地方标准。”

不能表达：

> “这个标准空间上适用于四川。”

因为：

- `GB*` 国家标准也可能在四川适用；
- `NB* / QX* / SL*` 等行业标准也可能在四川适用；
- 某些地方标准可能只覆盖省内更小范围；
- 单纯标准号前缀不是标准正文适用范围的完整事实。

## 3.7 现有区域解析能力可以直接复用

已有：

- `Backend/app/services/spatial_service.py::resolve_region()`

能力包括：

- adcode 精确解析；
- region_name 精确解析；
- `四川` -> `四川省` 的前缀解析；
- 多候选时显式抛出 `RegionAmbiguityError`；
- 不使用静默 `LIMIT 1` 猜测。

因此：

> **不新增第二套省市名称解析器，不让 LLM 自己生成 adcode。**

## 3.8 2026-10-02 数据库基线

本次重新读取当前 PostgreSQL：

```text
policy_chunks               = 32,448 chunks
distinct standard_code      = 279
distinct document_name      = 322
```

按标准号字母前缀粗分：

```text
DB  = 247
GB  = 29
NB  = 1
QX  = 1
SL  = 1
```

其中当前 `DB51*` 约有：

```text
5 个 distinct standard_code
```

国家 / 行业类当前共有：

```text
GB 29 + NB/QX/SL 3 = 32 个 distinct standard_code
```

`application_scope` 虽然大量行非 NULL，但绝大部分是占位内容；按当前占位值清洗口径，仅约 **4 个标准号**具有非占位范围文本。

所以当前数据不能支持：

> “根据 `application_scope` 已经精确知道 279 个标准分别适用于哪里。”

这也是本 PRD 必须新增**标准级适用范围事实层**的原因。

---

# 4. 问题根因

当前系统实际是五段断开的能力：

```text
地图点击
  → activeRegion                    已有

Agent 地图动作
  → locate_map                     已有，但只有移动视角

Map Context
  → active_region                  已有

RAG spatial_filter
  → geometry / DBxx prefix         已有，但语义不同

application_scope
  → 文本字段                       已有，但未结构化为空间事实
```

缺失的是：

```text
Region Selection
  ↓
Canonical Region Fact
  ↓
Standard Applicability Scope
  ↓
Retrieval Eligibility Constraint
  ↓
RAG / Catalogue Query
```

因此，不能用下面任何一种局部补丁解决：

```text
❌ 给 Controller 提示词写“看到四川就检索 DB51”
❌ locate_map 后在 App.tsx 猜 adcode
❌ 把 active_region 直接塞成关键词“四川”
❌ RAG Top-K 后再删掉非 DB51
❌ application_scope LIKE '%四川%'
❌ 给 Agent 单独维护一个 selected_region
```

---

# 5. 目标架构

```text
                    ┌─────────────────────────┐
                    │   Browser GIS Runtime   │
                    │                         │
Manual Click ──────▶│ useMapStore.activeRegion│
                    │          ▲              │
                    │          │ select_region│
                    └──────────┼──────────────┘
                               │ Browser Receipt
                               │
                      ┌────────┴────────┐
                      │ Agent Controller│
                      └────────┬────────┘
                               │
                    region name / adcode
                               │
                ┌──────────────▼──────────────┐
                │ SpatialService.resolve_region│
                └──────────────┬──────────────┘
                               │ canonical region
                               ▼
                    select_region browser action
                               │
                               ▼
                    active_region receipt
                               │
                               ▼
              ┌────────────────────────────────┐
              │ RegionScopeProjector            │
              │ active_region -> scope constraint│
              └────────────────┬───────────────┘
                               │
                               ▼
              ┌────────────────────────────────┐
              │ Standard Applicability Resolver │
              │ nationwide / admin / custom     │
              └────────────────┬───────────────┘
                               │
              ┌────────────────┴───────────────┐
              ▼                                ▼
      retrieve_kb                      list_applicable_standards
   主题问题 / 条款检索                    全部 / 清单 / 数量
              │                                │
              └──────────────┬─────────────────┘
                             ▼
                     Evidence / Answer
```

---

# 6. 核心领域概念

## 6.1 active_region

含义：

> 浏览器当前真正选中并高亮的行政区。

权威来源：

```text
Browser GIS Runtime
```

最小结构保持现状：

```json
{
  "adcode": "510000",
  "name": "四川省"
}
```

不把完整 GeoJSON 放入 Map Context。

需要几何时，后端通过 `spatial_regions.adcode` 获取。

## 6.2 StandardApplicabilityScope

含义：

> 一个标准在地理空间上具有什么适用资格。

它与普通文档几何不同。

建议类型：

```text
nationwide
admin_region
custom_geometry
unresolved
```

示例：

```text
GB/T xxxx
→ nationwide

DB51/T xxxx
→ admin_region: 510000 四川省

DB5132/T xxxx
→ admin_region: 对应自治州 / 市级行政区
```

## 6.3 RegionScopeConstraint

这是由当前 Browser `active_region` 派生的**临时检索约束**，不是第二状态源。

示例：

```text
RegionScopeConstraint(
    adcode="510000",
    region_name="四川省",
    relation="covers"
)
```

生命周期：

```text
当前 Browser Map Context
  ↓ 每次 request / browser resume 重新投影
临时 RegionScopeConstraint
```

不得把它另存成独立长期会话事实。

---

# 7. P0-1：新增 select_region Tool

## 7.1 为什么必须独立于 locate_map

两个动作语义不同：

```text
locate_map
= 改变 viewport

select_region
= 改变 active_region + 高亮 + 必要的视角联动
```

不得继续通过 `locate_map` 的附加字段隐式完成选区。

## 7.2 Tool 输入契约

建议：

```python
class SelectRegionInput(BaseModel):
    adcode: str | None = None
    region_name: str | None = None

    # exactly one
```

Controller 可直接调用：

```text
select_region(region_name="四川")
```

不得要求模型先猜：

```text
四川 = 510000
```

## 7.3 后端执行

`ToolRuntime` 对 `select_region` 做一次确定性规范化：

```text
Tool Call
  ↓
SpatialService.resolve_region(
    adcode=...,
    region_name=...
)
  ↓
{adcode: "510000", region_name: "四川省"}
  ↓
browser action
```

Browser Action：

```json
{
  "type": "select_region",
  "target": "browser_map",
  "payload": {
    "adcode": "510000",
    "name": "四川省"
  }
}
```

## 7.4 Browser Runtime 执行

2D 与 3D 都必须声明：

```text
supported_tools += select_region
```

执行原则：

1. 先验证当前行政区图层确实存在该 adcode；
2. 更新唯一状态：`useMapStore.setActiveRegion()`；
3. 复用当前 OpenLayers / Cesium 已有 `activeRegion -> syncHighlight()` 订阅；
4. 允许已有 fly-to 逻辑响应，不重新实现第二套飞行动画；
5. snapshot 必须立即反映新的 `active_region`；
6. Browser Receipt 成功后才能进入下一 Agent Step。

成功 Receipt 必须至少能证明：

```json
{
  "tool_name": "select_region",
  "status": "succeeded",
  "output": {
    "adcode": "510000",
    "name": "四川省"
  },
  "map_context": {
    "active_region": {
      "adcode": "510000",
      "name": "四川省"
    }
  }
}
```

---

# 8. P0-2：手动选区与 Agent 选区统一

最终只有一条状态链：

```text
Manual Click ─────┐
                  ├─> useMapStore.activeRegion
Agent select ─────┘
                         ↓
                OpenLayers / Cesium highlight
                         ↓
                  Browser Map Context
                         ↓
                    Backend Context
```

不得新增：

```text
agentSelectedRegion
retrievalSelectedRegion
sessionSelectedRegion
```

这些都属于重复状态。

---

# 9. P0-3：新增标准适用范围事实层

## 9.1 为什么不能直接使用 application_scope

当前 `application_scope` 是文本元数据：

```text
"本文件适用于……"
```

它可能包含：

- 地理范围；
- 行业范围；
- 对象范围；
- 工程条件；
- 大量占位值。

所以不能直接作为 PostGIS 条件。

必须先转成结构化事实。

## 9.2 建议表：standard_applicability

建议 PostgreSQL 新增：

```text
standard_applicability
```

最小字段：

```text
id
standard_key            canonical normalized standard identity
raw_standard_code       source value for audit/display
scope_type
scope_adcode           nullable
scope_geometry         nullable, geometry(MultiPolygon, 4326)
scope_text             nullable
basis_type
basis_chunk_id         nullable
verification_status
created_at
updated_at
```

其中长期关联键必须使用 `standard_key`；`raw_standard_code` 只保留来源值，不能再被其他模块当成另一套主键。

约束：

```text
scope_type:
  nationwide
  admin_region
  custom_geometry
  unresolved

basis_type:
  explicit_scope_clause
  jurisdiction_default
  standard_code_derived
  manual_verified

verification_status:
  verified
  derived
  unresolved
```

## 9.3 数据优先级

空间适用范围的优先级必须确定性固定：

```text
1. manual_verified / explicit verified scope
2. explicit_scope_clause 的结构化事实
3. jurisdiction_default
4. standard_code_derived
5. unresolved
```

高优先级事实存在时，不再被低优先级默认规则覆盖。

## 9.4 初始数据 bootstrap

为了避免等待 279 个标准全部人工整理后功能才可用，允许做一次**带 provenance 的确定性 bootstrap**。

### 国家 / 行业标准

例如：

```text
GB*
NB*
QX*
SL*
```

如果没有更具体的地理限制事实：

```text
scope_type = nationwide
basis_type = jurisdiction_default
verification_status = derived
```

这表示：

> 空间行政辖区维度上默认不排除四川。

不表示：

> 该标准对四川的所有业务场景都必然适用。

具体行业 / 工程对象仍由 RAG 问题相关性和原文范围判断。

### 地方标准

复用现有：

```text
REGION_STANDARD_PREFIXES
ADCODE_PREFIXES
```

将：

```text
DB51...
```

结构化为：

```text
scope_type = admin_region
scope_adcode = 510000
basis_type = standard_code_derived
verification_status = derived
```

对于：

```text
DB5132...
DB5101...
```

如果 `spatial_regions` 中存在对应完整 adcode，则优先映射到更细行政区；无法确定时不得静默降级成错误省级范围，应进入 `unresolved` 或仅保留可信上级范围并标记来源。

### application_scope

已有 `application_scope` 只作为**来源文本**进入抽取 / 核验流程。

运行时不得：

```sql
WHERE application_scope LIKE '%四川%'
```

来替代结构化适用性事实。

---

# 10. P0-4：标准适用性判定

## 10.1 默认语义：覆盖整个目标行政区

“适用于四川”的默认空间语义为：

```text
standard_scope covers target_region
```

对于行政区 scope：

```sql
ST_Covers(scope_region.geometry, target_region.geometry)
```

这可以自然支持：

```text
全国范围标准 covers 四川
四川省标准 covers 成都市
成都市标准 does not cover 整个四川省
```

## 10.2 与区域“有交集”必须使用另一语义

如果用户明确问：

```text
和四川有交集的规则 / 跨界标准
```

才允许：

```text
intersects
```

同时不能仅因边界接触判定有业务覆盖。

建议判定：

```text
ST_Intersects = true
AND intersection area > 0
```

而不是只用 `ST_Intersects`。

---

# 11. P0-5：active_region -> Retrieval Scope

## 11.1 新增 RegionScopeProjector

它只做一件事：

```text
Map Context.active_region
  ↓
RegionScopeConstraint
```

例如：

```text
active_region:
  510000 / 四川省

→

RegionScopeConstraint:
  adcode=510000
  relation=covers
```

## 11.2 不把 RegionScopeConstraint 变成持久状态

关键原则：

```text
Browser active_region = 权威状态
RegionScopeConstraint = 每次运行时重新派生
```

因此 Browser Receipt 更新 active_region 后，Agent continuation 再进入 Runtime 时必须**重新投影** RegionScopeConstraint。

不能继续直接复用浏览器调用前冻结的旧 region scope。

现有 `PendingBrowserExecution.retrieval_constraints` 中：

- top_k
- threshold
- search_mode
- rerank
- metadata_filter

可以继续持久化；

但**区域适用性 scope 必须从 resume 后的最新 `request_context.browser_observations.map_context.active_region` 重新推导。**

这一步是保证：

```text
同一 Turn：select 四川 → 再 retrieve_kb
```

真正按四川过滤的关键。

---

# 12. P0-6：Retrieval 前置约束，而不是后置删除

## 12.1 新 Retrieval Contract

建议在：

- `Backend/app/services/rag/contracts.py`

新增独立约束：

```python
@dataclass(frozen=True)
class StandardScopeConstraint:
    adcode: str
    region_name: str
    relation: Literal["covers", "intersects"] = "covers"
```

并加入：

```text
RetrievalQuery.standard_scope
```

不要继续塞进通用 `SpatialFilter`。

## 12.2 检索顺序

目标顺序：

```text
StandardScopeConstraint
  ↓
SQL eligibility predicate
  ↓
exact / keyword / vector
  ↓
RRF
  ↓
rerank
```

而不是：

```text
exact / keyword / vector
  ↓
RRF Top-K
  ↓
再过滤
```

## 12.3 三个检索通道必须共享同一个资格约束

必须同时约束：

```text
_exact_standard_code_search
_keyword_search
_vector_search
```

不得只改 keyword，导致：

```text
keyword 是四川
vector 还是全国
```

形成隐性双语义。

## 12.4 RRF / rerank 不再决定“是否适用”

适用性属于布尔资格：

```text
eligible / ineligible / unresolved
```

rerank 只在 eligible 候选内部决定相关性排序。

不得用“空间匹配 +0.1 分”代替资格过滤。

---

# 13. P0-7：“全部标准”不能走普通 RAG Top-K

这是本 PRD 必须明确解决的语义边界。

用户说：

```text
查一下四川有哪些标准
四川适用的全部标准
四川一共有多少标准
```

这类问题的目标是：

```text
集合枚举 / count
```

而不是：

```text
找 Top-10 最相关 chunk
```

因此新增确定性工具：

```text
list_applicable_standards
```

## 13.1 最小输入

```text
query?      可选主题条件
limit       默认 20
cursor?     可选
```

区域不让模型重复传。

它直接消费 Runtime 当前的：

```text
StandardScopeConstraint
```

如果当前没有 active_region，则：

- Agent 应先 `select_region`；或
- 工具返回 `REGION_SCOPE_REQUIRED`。

## 13.2 返回

```json
{
  "region": {
    "adcode": "510000",
    "name": "四川省"
  },
  "total": "<database-computed>",
  "items": [
    {
      "standard_code": "...",
      "title": "...",
      "scope_basis": "jurisdiction_default",
      "verification_status": "derived"
    }
  ],
  "next_cursor": null,
  "unresolved_count": 0
}
```

`total` 实际运行时为整数，由数据库实时计算，不得由模型推断或硬编码。

## 13.3 为什么必须和 retrieve_kb 分开

```text
retrieve_kb
→ 回答“这个区域关于某主题有什么规定”

list_applicable_standards
→ 回答“这个区域有哪些 / 多少标准”
```

两个目标不同，强行共用 Top-K 会产生“拿排名结果冒充全集”的错误。

---

# 14. Agent 区域标准工作流

不新增第二套 workflow engine。

继续复用当前：

```text
LangGraph planning
Controller
Tool Runtime
Browser interrupt / resume
Evidence Ledger
Answer Generator
```

只新增能力和语义契约。

## 14.1 用户：查一下四川的标准

期望轨迹：

```text
Step 1
Controller
→ select_region(region_name="四川")

Step 2
SpatialService
→ resolve 四川 = 四川省 / 510000

Step 3
Browser
→ set activeRegion
→ 四川真正高亮
→ receipt(active_region=510000)

Step 4
Agent resume
→ RegionScopeProjector(510000)

Step 5
Controller
→ list_applicable_standards(...)

Step 6
→ Evidence / catalogue facts

Step 7
→ Answer
```

## 14.2 用户已经手动选中四川，再问主题

```text
Map Context:
active_region = 四川

用户：地质灾害监测有什么标准？
```

期望：

```text
不重复 select_region
  ↓
直接派生四川 StandardScopeConstraint
  ↓
retrieve_kb
  ↓
只在四川 spatially eligible standards 中做 RAG
```

## 14.3 当前选中四川，但用户说“查重庆的标准”

Controller 必须看到：

```text
Current Map = 四川
Explicit user region = 重庆
```

显式当前请求优先：

```text
select_region("重庆")
→ receipt 重庆
→ 再查询重庆
```

不得在旧四川 scope 下先检索，再事后改地图。

## 14.4 当前已经是四川，用户再次说“查四川的标准”

不重复执行浏览器副作用。

Controller 应直接进入：

```text
list_applicable_standards
```

---

# 15. Linear 模式兼容

Linear 不承担“理解自然语言并自动操作地图”的 Agent 能力。

因此：

### 手动已选区域

Linear 必须消费：

```text
map_context.active_region
```

并应用同一套：

```text
StandardScopeConstraint
```

### 用户只输入“查四川标准”，但地图未选中四川

Linear 不新增另一套 region NLP parser 去模仿 Agent。

原因：

> 否则会形成 Agent 一套语义决策、Linear 又一套硬编码语义决策。

Linear 只保证：

```text
已有明确 Browser active_region 时，区域过滤与 Agent 一致。
```

Agent 模式负责：

```text
自然语言 -> select_region -> 同 Turn 查询
```

---

# 16. Controller Tool Policy

## select_region

**Use when**：

- 用户明确要求某行政区成为当前地图查询范围；
- 用户提出地区标准查询，且当前 active_region 与目标地区不一致；
- 需要先建立稳定区域上下文，再执行区域敏感工具。

**Avoid when**：

- 只要求移动到某经纬度：使用 `locate_map`；
- 当前 active_region 已经是目标地区；
- 用户没有要求更改当前区域。

## retrieve_kb

如果存在 `StandardScopeConstraint`：

```text
自动在该区域合法标准集合中检索
```

模型无需重复传 adcode。

## list_applicable_standards

**Use when**：

- “有哪些标准”
- “全部标准”
- “标准清单”
- “有多少标准”

**Avoid when**：

- 需要回答具体条款、规范要求、业务问题，应使用 `retrieve_kb`。

---

# 17. 适用性证据与回答口径

标准被纳入区域候选时，至少要能解释：

```text
为什么它空间上被认为适用于四川？
```

结果 metadata 建议附带：

```text
scope_type
scope_adcode
scope_basis
verification_status
scope_source_chunk_id
```

回答时区分：

### verified

可以表述：

```text
已核验适用范围覆盖四川。
```

### derived

应表述：

```text
按国家/行业标准的辖区默认规则，空间范围上视为可在四川适用；具体业务适用条件仍以标准原文为准。
```

### unresolved

不得进入“已适用”确定集合。

可单列：

```text
适用范围待核验
```

---

# 18. “全部”的产品口径

系统只能承诺：

> **当前知识库中、已建立空间适用性事实的全部标准。**

不能承诺：

> 四川现实世界中所有现行国家、行业、地方标准。

因此 `list_applicable_standards` 必须同时返回：

```text
eligible_count
unresolved_count
scope_coverage
```

例如：

```text
已判断空间适用范围：318/322 个库内文档
适用于四川：N 个
仍有 4 个范围待核验
```

具体数字由实时数据生成。

当 `unresolved_count > 0` 时，不允许生成：

```text
“这就是四川全部标准。”
```

只能说：

```text
“以下是当前知识库中已判定适用于四川的全部标准；另有 N 个标准适用范围待核验。”
```

---

# 19. 错误与边界行为

## 19.1 区域不存在

```text
select_region("不存在行政区")
```

后端 `SpatialService.resolve_region()` 失败。

不得向浏览器发出 selection action。

## 19.2 区域有歧义

复用已有 `RegionAmbiguityError`。

如果存在多个合法候选：

```text
Runtime 候选
→ Clarify
```

模型不得自行选第一个。

## 19.3 浏览器图层未就绪

如果：

```text
select_region
```

不在当前 `supported_tools` 中，Controller 不得调用。

## 19.4 后端解析成功，但浏览器不存在对应 adcode

Browser Tool Receipt：

```text
failed
UNKNOWN_REGION
```

不得更新 activeRegion。

## 19.5 当前选区被用户手动改变

Browser 状态永远优先于旧 Agent 推断。

每次新的用户请求必须重新读取最新 `getBrowserMapContext()`。

同一 Browser Tool 完成后，以 Receipt 中的 `map_context` 作为该 continuation 的执行事实。

后续实现不得把 Controller 早先看到的旧 active_region 写回浏览器。

## 19.6 active_region = null

普通知识检索不自动增加区域约束。

`list_applicable_standards` 如果语义要求区域，则返回 `REGION_SCOPE_REQUIRED`，由 Agent 先建立区域。

---

# 20. 数据质量要求

当前 `standard_code` 已存在格式噪声，例如不同分隔符和不完整标准号形式。

因此 scope bootstrap 前必须复用已有：

```text
DocumentAssetService.normalize_standard_code()
```

并建立标准级稳定键。

不能直接用原始 `standard_code` 字符串做长期 scope 主键后再到处新增不同 normalization。

建议：

```text
standard_key = canonical normalized standard code
```

`policy_chunks` 与 `standard_applicability` 都通过同一规范化函数匹配。

如果某标准号无法得到合法稳定键：

```text
verification_status = unresolved
```

不得猜测归属。

---

# 21. 物理边界设计

## Browser GIS

负责：

- 真实选中状态；
- 高亮；
- 视角联动；
- Browser Receipt；
- `active_region` snapshot。

不负责：

- 判断国家标准是否适用于四川；
- 解析标准适用范围。

## SpatialService

负责：

- 行政区实体解析；
- adcode -> geometry；
- 空间关系。

不负责：

- RAG 排名。

## Standard Applicability Service

负责：

- 标准级空间适用范围事实；
- scope bootstrap；
- scope precedence；
- target region eligibility；
- catalogue list / count。

## RAG Retrieval

负责：

- 在 eligible standards 内 exact / keyword / vector；
- RRF；
- rerank；
- chunk evidence。

## Controller

负责：

- 判断是否需要选区；
- 判断是知识检索还是标准目录枚举；
- 组织 Tool sequence。

不负责：

- 自己算 adcode；
- 自己判断空间包含关系；
- 自己用标准号字符串猜最终适用性。

---

# 22. 预计代码改动边界

## Backend

### Agent Tool

- `Backend/app/services/agent/tools.py`
  - `SelectRegionInput`
  - `select_region`
  - `ListApplicableStandardsInput`
  - `list_applicable_standards`

### Tool Runtime

- `Backend/app/services/agent/tool_runtime.py`
  - `select_region` 先复用 `SpatialService.resolve_region()`
  - 注入当前 `StandardScopeConstraint`
  - catalogue tool dispatch

### Runtime / Context

- `Backend/app/services/agent/runtime.py`
- 必要时 `Backend/app/services/agent/orchestration/browser_continuation.py`
  - browser resume 后重新从最新 map_context 派生 scope
  - 不引入新长期状态

### RAG Contract

- `Backend/app/services/rag/contracts.py`
  - `StandardScopeConstraint`
  - `RetrievalQuery.standard_scope`

### RAG Adapter

- `Backend/app/services/rag/postgres_adapter.py`
  - exact / keyword / vector 都应用相同 eligibility predicate

### Applicability

建议新增：

- `Backend/app/services/standard_applicability.py`

仅负责标准空间适用事实，不塞回 `filters.py` 形成巨型模块。

### Migration

- `Backend/migrations/<date>_standard_applicability.sql`

## Frontend

### Contracts

- `frontend/src/gis/contracts.ts`

### 2D

- `frontend/src/gis/mapContext.ts`
- `frontend/src/gis/createBrowserGisRuntime.ts`
- `frontend/src/gis/frontendExecutor.ts`
- 必要时 `frontend/src/components/OpenLayersMap.tsx`

### 3D

- `frontend/src/gis/cesiumRuntime.ts`
- `frontend/src/components/CesiumGlobe.tsx`

原则：

> 复用现有 `useMapStore.activeRegion` 与 `syncHighlight`，不重新实现一套 Region Store。

---

# 23. 实施阶段

## Phase 0：事实基线与数据契约

1. 固定当前 DB baseline；
2. 统计标准级 scope 覆盖率；
3. 定义 `standard_key` normalization；
4. 新增 `standard_applicability` migration；
5. 写 bootstrap 脚本与 dry-run 报告；
6. 不修改 Agent 行为。

验收：

```text
每个 scope row 都能说明：
standard_key
scope
basis
verification_status
```

## Phase 1：select_region Browser 闭环

1. Tool schema；
2. `SpatialService.resolve_region` 复用；
3. 2D supported_tools；
4. 3D supported_tools；
5. Browser executor；
6. receipt；
7. 单元测试；
8. Playwright 真地图测试。

验收：

```text
Agent select_region("四川")
→ 真实高亮四川
→ active_region = 510000
→ receipt revision 增加
```

## Phase 2：Region Scope 投影

1. 从 admitted map_context 派生 scope；
2. Agent first-run 生效；
3. Browser resume 后重新派生；
4. Linear 手动选区生效；
5. 无 active_region 不加约束。

## Phase 3：RAG 前置 eligibility

1. `RetrievalQuery.standard_scope`；
2. exact 加 scope；
3. keyword 加 scope；
4. vector 加 scope；
5. RRF / rerank 只处理 eligible set；
6. diagnostics 输出 scope basis。

## Phase 4：Catalogue Query

1. `list_applicable_standards`；
2. count；
3. pagination；
4. unresolved_count；
5. Evidence；
6. Controller tool policy。

## Phase 5：真实 Agent Workflow E2E

覆盖手动入口与自然语言入口。

## 23.1 2026-10-02 实施记录

当前实施状态以代码、测试与本地 PostgreSQL 实测为准：

- **Phase 0：CORE_IMPLEMENTED**
  - 已新增 `standard_applicability` migration、migration guard、bootstrap dry-run/apply 脚本；
  - `standard_key` 复用 `DocumentAssetService.normalize_standard_code()`；
  - 本地真实基线：`policy_chunks=32448`、原始标准号 `279`、规范化标准键 `278`；
  - bootstrap 结果：`nationwide=31`、`admin_region=198`、`unresolved=49`，共写入 `278` 条事实；
  - `GB_T / DBxx_T` 等缺少具体编号的占位值已按 fail-closed 处理为 `unresolved`；
  - migration 已在本地 PostgreSQL 实际执行成功，bootstrap 已实际 apply 成功。
- **Phase 1：CORE_IMPLEMENTED / PLAYWRIGHT_PENDING**
  - `select_region` Tool、`SpatialService.resolve_region()` 复用、2D/3D supported tool、Browser executor 与唯一 `activeRegion` 写入路径已接通；
  - 未知行政区使用 `UNKNOWN_REGION`；
  - 2D/3D 定向单测已通过；
  - 真实浏览器地图高亮 + receipt revision 的 Playwright 验收仍待执行。
- **Phase 2：IMPLEMENTED**
  - Agent first-run、Browser resume 与 Linear 均从 admitted `map_context.active_region` 即时派生 `StandardScopeConstraint`；
  - scope 不进入 Pending/Session 持久状态，Browser resume 后按最新 receipt map_context 重新派生；
  - 无 `active_region` 时保持原有无区域约束行为。
- **Phase 3：CORE_IMPLEMENTED / DIAGNOSTICS_PENDING**
  - exact / keyword / vector 均在各自 SQL `LIMIT` 与 RRF/rerank 之前执行统一 eligibility；
  - 高优先级 applicability fact 会屏蔽低优先级默认事实；
  - 区域约束下没有标准级 applicability 事实的 uploaded-document 候选不会混入确定候选集；
  - `covers` 与正面积 `intersects` SQL 规则已实现；
  - RAG diagnostics 中进一步显式输出每条候选的 scope basis 尚待补齐。
- **Phase 4：IMPLEMENTED**
  - 新增 `list_applicable_standards`，支持主题过滤、count、cursor pagination、`unresolved_count`、`coverage_complete`；
  - Catalogue 结果写入 Evidence Ledger；
  - Controller 已明确“清单/全部/数量 → Catalogue；具体条款/要求/解释 → retrieve_kb”；
  - 四川 `510000 + 地质灾害` 本地真实 smoke：Catalogue `eligible_count=2`、`unresolved_count=49`；RAG 同时返回四川 DB51 与全国 GB 标准。
- **Phase 5：PENDING**
  - 尚未执行真实模型自然语言 `select_region → browser receipt → same-turn scoped retrieval` Workflow E2E。

回归记录：

- 后端本轮相关定向测试：54 项通过；
- 前端 `npm run test:unit`：11 个 Vitest 文件 / 54 项通过，附带 tsx 测试通过；`selectRegionRuntime.test.ts` 已纳入 `test:unit`；
- 前端 `npm run lint`：编码检查、API contract、TypeScript 均通过；
- 后端全量 `pytest tests -q`：仅 1 项既有环境失败，原因是当前 `MINIO_SECRET_KEY` 为空导致 MinIO client 构造失败，与本 PRD 改动路径无关。

## 23.2 2026-10-04 真实模型主链路复验

- `frontend/e2e/region-standard-scope.spec.ts` 保持严格的 `publication_state === "published"` 断言，2D 与 3D 合计 `2 passed (3.2m)`。
- 2D `turn-24` / `trace_id=71b7ebf1-574d-402f-bafd-fd2894eb454d`、3D `turn-25` / `trace_id=b11ac88b-de78-4b96-956f-c07df0f753a4` 均完成真实 `select_region` Browser Receipt，选区为四川 `510000`，随后执行 `list_applicable_standards`，产生 `answer_generated` 和非空答案，最终 `publication_state=published`。
- 真实 PostgreSQL catalogue 的四川结果为 `eligible_count=35`、`unresolved_count=49`；回答只能代表库内已判定范围。
- 本轮修复 DeepSeek 客户端与锁定版本 `httpx==0.28.1` 的参数兼容问题：显式代理使用 `proxy`，无代理时不传代理参数。回归测试先复现 `proxies` 参数异常，再通过 2 个用例。
- 后端 Controller/Runtime/Answer/Scope/Applicability/DeepSeek 定向测试 122 项通过；前端 unit 54 项、lint/TypeScript、生产 build 均通过。
- Phase 5 的自动选区标准目录主链路已验证。手动选区后的查询、四川切重庆、已选中四川时避免重复选区，以及其余测试矩阵场景尚未在本次真实 E2E 中逐项验证，因此本 PRD 仍为 `IN_PROGRESS`。

---

# 24. 测试矩阵

## 24.1 Browser Tool 单测

### B-01 2D 四川选中

```text
select_region(510000)
→ activeRegion 四川
→ supported
→ succeeded
```

### B-02 3D 四川选中

同上。

### B-03 未知 adcode

```text
→ failed
→ UNKNOWN_REGION
→ activeRegion 不改变
```

### B-04 幂等

连续两次同一 `tool_call_id` 同参数：

```text
不得重复副作用
```

## 24.2 Region Resolver

### R-01 四川

```text
四川 -> 四川省 / 510000
```

### R-02 精确 adcode

```text
510000 -> 四川省
```

### R-03 歧义名称

```text
→ RegionAmbiguityError
→ 不 silent first
```

## 24.3 Applicability

### A-01 全国标准

```text
nationwide covers 四川 = true
```

### A-02 四川省地方标准

```text
510000 covers 510000 = true
```

### A-03 四川省标准与成都

```text
四川 scope covers 成都 target = true
```

### A-04 成都标准与整个四川

```text
成都 scope covers 四川 target = false
```

### A-05 仅边界接触

```text
intersects=true
intersection_area=0
→ 不算正面积覆盖
```

## 24.4 Retrieval

### Q-01 四川 + 主题检索

输入：

```text
active_region=四川
query=地质灾害监测
```

断言：

- exact 只读取 eligible 标准；
- keyword 只读取 eligible 标准；
- vector 只读取 eligible 标准；
- 不出现其他省地方标准；
- 国家 / 行业标准允许进入候选。

### Q-02 无 active_region

不增加区域限制。

### Q-03 空间约束必须在 RRF 前

构造：

- 全国高相似噪声；
- 四川中等相似正确结果。

断言：

```text
四川正确结果不会因为候选池被全国噪声挤出而消失
```

## 24.5 Catalogue

### C-01 四川全部标准

断言：

```text
total = SQL eligible count
不是 top_k count
```

### C-02 Pagination

多页结果无重复、无漏项。

### C-03 unresolved

`unresolved_count > 0` 时回答不得声称现实世界全集。

## 24.6 Agent Real-model E2E

### E2E-01 Agent 自动选择四川

用户：

```text
查一下四川的标准
```

要求完整 Trace：

```text
Controller
→ select_region
→ browser_tool_requested
→ browser_tool_completed
→ map_context.active_region=510000
→ list_applicable_standards
→ answer
```

同时视觉断言：

```text
四川实际处于 selected highlight 状态
```

### E2E-02 手动选四川后提问

```text
手动点击四川
→ 不产生查询
→ 再问主题问题
→ retrieve_kb 自动按四川 scope 查询
```

### E2E-03 四川切换重庆

```text
当前四川
用户：查重庆的标准
→ 先 select_region 重庆
→ 后检索
→ 不使用旧四川 scope
```

### E2E-04 已经选中四川

```text
当前四川
用户：查四川的标准
→ 不重复 browser select
→ 直接 catalogue query
```

### E2E-05 国家标准不能丢

四川 active 时查询一个已有 GB 标准相关主题：

```text
GB 结果仍可被召回
```

### E2E-06 外省地方标准不能混入

四川 active：

```text
DB11 / DB32 等外省地方标准不得作为“适用于四川”的确定结果进入最终答案
```

---

# 25. 验收标准

本 PRD 只有同时满足下面条件才算完成。

## 地图状态

- [ ] 手动选四川真实高亮；
- [ ] Agent `select_region("四川")` 也真实高亮；
- [ ] 两者都写入同一个 `activeRegion`；
- [ ] `locate_map` 与 `select_region` 语义彻底分离；
- [ ] Browser Receipt 可证明新的 active_region。

## Agent

- [ ] “查四川的标准”先建立四川选区；
- [ ] browser resume 后同一 Turn 使用新的四川 scope；
- [ ] 当前已经是四川时不重复选择；
- [ ] 四川 -> 重庆时不使用旧 scope；
- [ ] 区域解析不靠模型猜 adcode。

## RAG

- [ ] active_region 真正成为后端检索资格约束；
- [ ] eligibility 在 exact / keyword / vector 之前生效；
- [ ] 不再依赖 RRF 后过滤作为主要区域限制；
- [ ] 四川查询能包含适用的 GB / 行业标准；
- [ ] 外省地方标准不会混入四川确定结果；
- [ ] scope basis 可解释。

## Catalogue

- [ ] “全部 / 有哪些 / 数量”不使用 Top-K 冒充全集；
- [ ] 支持 total；
- [ ] 支持 pagination；
- [ ] 返回 unresolved_count；
- [ ] 数据不完整时不宣称外部世界全集。

## Linear

- [ ] 手动 active_region 在 Linear 中也生效；
- [ ] 不为 Linear 复制一套自然语言 region parser。

## 数据

- [ ] `standard_applicability` 有 provenance；
- [ ] `standard_key` 使用单一 normalization；
- [ ] derived / verified / unresolved 可区分；
- [ ] 当前 scope 覆盖率有可复现统计报告。

## 验证

- [ ] Backend 定向 pytest；
- [ ] frontend unit tests；
- [ ] 2D browser E2E；
- [ ] 3D browser E2E；
- [ ] real-model Agent E2E；
- [ ] 数据库真实 SQL 校验；
- [ ] Trace 中能看到 region selection → receipt → scoped retrieval 因果链。

---

# 26. 禁止实现方式

以下实现即使短期“看起来能跑”，也不接受：

1. `prompt += "四川就搜 DB51"`；
2. 在前端根据回答文本正则提取四川；
3. `locate_map` 偷偷更新 activeRegion；
4. 新建 Agent 专用 Region Store；
5. 只修改 OpenLayers，不支持 Cesium；
6. 只修改 keyword search，不改 vector / exact；
7. Top-K 后再删非四川候选；
8. `application_scope LIKE '%四川%'` 作为主判据；
9. 只返回 DB51，漏掉 GB / 行业标准；
10. 用 LLM 直接生成 SQL 判断标准适用范围；
11. 用 RAG Top-K 回答“全部标准”；
12. 无 coverage 统计却声称“全部”；
13. 用标准号前缀结果冒充已人工核验事实；
14. 在 Linear 再造一套独立 region 语义解析；
15. 为这个功能建立第二个 LangGraph / Agent Runtime。

---

# 27. 最终目标状态

完成后，系统行为应收敛为：

```text
用户手动点四川
        │
        └──────────────┐
                       ▼
                active_region
                       ▲
        ┌──────────────┘
        │
用户：查四川的标准
        ↓
Controller
        ↓
select_region("四川")
        ↓
SpatialService.resolve_region
        ↓
Browser 真正高亮四川
        ↓
Receipt active_region=510000
        ↓
RegionScopeProjector
        ↓
Standard Applicability
        ├─ 国家标准
        ├─ 行业标准
        └─ 四川地方标准
        ↓
eligible standard set
        ├─ 主题问题 → retrieve_kb → RAG
        └─ 全部/清单 → list_applicable_standards
        ↓
Evidence
        ↓
Answer
```

核心结论：

> **地图选区不是一个视觉装饰，而是后续知识查询的结构化空间上下文；Agent 选区必须产生真实 Browser 状态，标准适用范围必须成为检索前置资格约束，RAG 只负责在合法候选中找相关条款。**
