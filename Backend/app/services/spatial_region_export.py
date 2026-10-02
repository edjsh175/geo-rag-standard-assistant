from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import text


def _canonical_source_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    canonical = [
        {
            "adcode": str(row["adcode"]),
            "region_name": str(row["region_name"]),
            "source_geometry_hex": str(row["source_geometry_hex"]),
        }
        for row in rows
    ]
    canonical.sort(key=lambda row: row["adcode"])
    return canonical


def compute_region_source_hash(rows: Iterable[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        _canonical_source_rows(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def build_region_feature_collection(
    rows: Iterable[Mapping[str, Any]],
    *,
    generated_at: str | None = None,
    simplify_tolerance: float = 0.001,
) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    source_hash = compute_region_source_hash(materialized)
    version = f"spatial-regions-v1-{source_hash.split(':', 1)[1][:12]}"
    features = [
        {
            "type": "Feature",
            "properties": {
                "adcode": str(row["adcode"]),
                "name": str(row["region_name"]),
                "region_name": str(row["region_name"]),
            },
            "geometry": row["geometry"],
        }
        for row in sorted(materialized, key=lambda item: str(item["adcode"]))
    ]
    return {
        "type": "FeatureCollection",
        "dataset_meta": {
            "dataset_version": version,
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "source_hash": source_hash,
            "source_relation": "spatial_regions",
            "simplify_tolerance": simplify_tolerance,
            "feature_count": len(features),
        },
        "features": features,
    }


async def load_region_export_rows(
    session: Any,
    *,
    simplify_tolerance: float = 0.001,
) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT adcode,
                   region_name,
                   encode(ST_AsEWKB(geometry), 'hex') AS source_geometry_hex,
                   ST_AsGeoJSON(ST_SimplifyPreserveTopology(geometry, :simplify))::json AS geometry
            FROM spatial_regions
            ORDER BY adcode ASC
            """
        ),
        {"simplify": simplify_tolerance},
    )
    return [dict(row) for row in result.mappings().all()]


async def export_region_dataset(
    session: Any,
    output_path: Path,
    *,
    simplify_tolerance: float = 0.001,
) -> dict[str, Any]:
    rows = await load_region_export_rows(session, simplify_tolerance=simplify_tolerance)
    if not rows:
        raise RuntimeError(
            "spatial_regions contains no rows; refusing to publish an empty region artifact"
        )
    document = build_region_feature_collection(
        rows,
        simplify_tolerance=simplify_tolerance,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return document


if __name__ == "__main__":
    import asyncio
    import sys
    from app.core.database import db_manager

    default_output = Path(__file__).resolve().parents[3] / "frontend" / "public" / "data" / "china-provinces.json"
    target_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default_output

    async def _cli() -> None:
        async with db_manager.get_postgres_session() as session:
            doc = await export_region_dataset(session, target_path)
            meta = doc["dataset_meta"]
            print(
                f"Exported {meta['feature_count']} features to {target_path} "
                f"version={meta['dataset_version']} hash={meta['source_hash']}"
            )

    asyncio.run(_cli())
