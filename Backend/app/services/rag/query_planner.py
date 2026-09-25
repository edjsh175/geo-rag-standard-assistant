"""Query Planner for RAG retrieval execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from app.services.rag.contracts import RetrievalQuery


STANDARD_CODE_QUERY_PATTERN = re.compile(
    r"""
    (?P<code>
        [A-Z]{1,6}\d{0,4}
        (?:\s*[/_]\s*[A-Z])?
        (?:\s*[-_/]?\s*\d+(?:\.\d+)*)+
        \s*[-—]\s*\d{4}
    )
    """,
    re.VERBOSE,
)
COMPACT_STANDARD_CODE_PATTERN = re.compile(r"^[A-Z]{2,10}\d{6,}$")
COMPARATIVE_TERMS = ("区别", "对比", "不同", "差异", "相比", "哪一个", "还是", "比较")


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """Execution plan determined for a single retrieval request."""

    query_text: str
    top_k: int
    candidate_k: int
    search_mode: str
    use_rerank: bool
    intent: str
    channel_weights: Mapping[str, float] = field(default_factory=dict)


class QueryPlanner:
    """Classifies retrieval intent and derives candidate pool sizes and branch weights."""

    def plan(self, query: RetrievalQuery) -> RetrievalPlan:
        text = (query.query_text or "").strip()
        top_k = max(1, query.top_k)

        # 1. Standard code detection
        upper_text = text.upper()
        is_standard_code = bool(STANDARD_CODE_QUERY_PATTERN.search(upper_text))
        if not is_standard_code:
            compact = re.sub(r"[^0-9A-Z]+", "", upper_text)
            if COMPACT_STANDARD_CODE_PATTERN.fullmatch(compact) and compact[-4:].isdigit():
                is_standard_code = True

        if is_standard_code:
            return RetrievalPlan(
                query_text=text,
                top_k=top_k,
                candidate_k=max(top_k * 3, 15),
                search_mode=query.mode,
                use_rerank=query.use_rerank,
                intent="standard_code",
                channel_weights={
                    "exact": 2.5,
                    "keyword": 1.2,
                    "vector": 0.8,
                },
            )

        # 2. Spatial filter present or query mentions spatial terms
        if query.spatial_filter is not None or any(
            term in text for term in ("范围", "坐标", "位置", "红线", "宗地", "区域", "边界", "地块")
        ):
            return RetrievalPlan(
                query_text=text,
                top_k=top_k,
                candidate_k=max(top_k * 4, 20),
                search_mode=query.mode,
                use_rerank=query.use_rerank,
                intent="spatial",
                channel_weights={
                    "exact": 1.0,
                    "keyword": 1.2,
                    "vector": 1.5,
                },
            )

        # 3. Comparative intent
        if any(term in text for term in COMPARATIVE_TERMS):
            return RetrievalPlan(
                query_text=text,
                top_k=top_k,
                candidate_k=max(top_k * 3, 18),
                search_mode=query.mode,
                use_rerank=query.use_rerank,
                intent="comparative",
                channel_weights={
                    "exact": 1.0,
                    "keyword": 1.0,
                    "vector": 1.2,
                },
            )

        # 4. Default general hybrid
        return RetrievalPlan(
            query_text=text,
            top_k=top_k,
            candidate_k=max(top_k * 3, 12),
            search_mode=query.mode,
            use_rerank=query.use_rerank,
            intent="general",
            channel_weights={
                "exact": 1.5,
                "keyword": 1.0,
                "vector": 1.0,
            },
        )
