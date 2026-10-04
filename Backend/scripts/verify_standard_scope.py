"""Smoke-test catalogue and RAG qualification for one administrative region."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import db_manager
from app.services.rag.contracts import RetrievalQuery, StandardScopeConstraint
from app.services.rag.postgres_adapter import PostgresRetrievalAdapter
from app.services.standard_applicability import StandardApplicabilityService


async def _run(*, adcode: str, name: str, query: str) -> None:
    await db_manager._init_postgres()
    try:
        scope = StandardScopeConstraint(adcode=adcode, region_name=name)
        catalogue = await StandardApplicabilityService().list_applicable_standards(
            scope=scope,
            query=query or None,
            limit=10,
        )
        retrieval = await PostgresRetrievalAdapter().retrieve(
            RetrievalQuery(
                query_text=query or "标准规范",
                top_k=5,
                threshold=0.0,
                search_mode="keyword",
                use_rerank=False,
                standard_scope=scope,
            )
        )
        print(
            json.dumps(
                {
                    "catalogue": catalogue,
                    "rag_candidates": [
                        {
                            "standard_code": item.metadata.get("standard_code"),
                            "title": item.title,
                            "score": item.score,
                            "standard_scope": item.metadata.get("standard_scope"),
                        }
                        for item in retrieval.candidates
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await db_manager.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adcode", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--query", default="")
    args = parser.parse_args()
    asyncio.run(_run(adcode=args.adcode, name=args.name, query=args.query))


if __name__ == "__main__":
    main()
