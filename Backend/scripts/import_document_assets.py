"""
Batch import original standard documents into MinIO and write asset mappings to MySQL.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import logging
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import db_manager
from app.services.document_asset_service import ASSET_METADATA_COLUMNS, DocumentAssetService
from app.services.document_service import DocumentService

logger = logging.getLogger("import_document_assets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        required=True,
        help="Root directory containing the original files, typically the folder above 'pdf/'.",
    )
    parser.add_argument(
        "--bucket-prefix",
        default="standards",
        help="Object key prefix inside the MinIO bucket.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional maximum number of metadata rows to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect matches and planned object keys without uploading or writing MySQL.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-upload even when the object already exists with the same key.",
    )
    return parser.parse_args()


async def run_import(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.exists():
        logger.error("Source root does not exist: %s", source_root)
        return 2

    await db_manager.initialize()
    asset_service = DocumentAssetService()

    try:
        available_columns = await asset_service.get_metadata_columns(refresh=True)
        missing_columns = [column for column in ASSET_METADATA_COLUMNS if column not in available_columns]
        if missing_columns:
            if args.dry_run:
                logger.warning("Asset columns are missing and dry-run will not add them: %s", ", ".join(missing_columns))
            else:
                logger.info("Adding missing asset columns: %s", ", ".join(missing_columns))
                await asset_service.ensure_asset_columns()

        document_service: DocumentService | None = None
        if not args.dry_run:
            document_service = DocumentService()

        metadata_rows = await asset_service.list_metadata_rows()
        if args.limit > 0:
            metadata_rows = metadata_rows[: args.limit]

        total_rows = len(metadata_rows)
        matched_rows = 0
        uploaded_rows = 0
        ready_rows = 0
        missing_rows = 0
        failed_rows = 0

        logger.info("Processing %s metadata rows from %s", total_rows, source_root)

        for index, row in enumerate(metadata_rows, start=1):
            source_path = asset_service.resolve_local_source_path(row, source_root)
            if not source_path:
                missing_rows += 1
                logger.warning("[%s/%s] Missing file for %s", index, total_rows, row.get("standard_code"))
                if not args.dry_run:
                    await asset_service.update_asset_metadata(
                        int(row["standard_id"]),
                        {
                            "asset_status": "missing",
                            "asset_error": "Source file not found under the provided source root.",
                        },
                    )
                continue

            matched_rows += 1
            object_name = asset_service.build_object_name(row, bucket_prefix=args.bucket_prefix)
            content_type = asset_service.detect_content_type(source_path)
            file_size = source_path.stat().st_size
            filename = source_path.name

            if args.dry_run:
                logger.info(
                    "[%s/%s] WOULD UPLOAD %s -> %s",
                    index,
                    total_rows,
                    source_path,
                    object_name,
                )
                continue

            assert document_service is not None

            try:
                upload_required = True
                if not args.force:
                    try:
                        stat = document_service.minio_client.stat_object(document_service.bucket_name, object_name)
                        upload_required = stat.size != file_size
                    except Exception:
                        upload_required = True

                if upload_required:
                    document_service.minio_client.fput_object(
                        document_service.bucket_name,
                        object_name,
                        str(source_path),
                        content_type=content_type,
                    )
                    uploaded_rows += 1

                await asset_service.update_asset_metadata(
                    int(row["standard_id"]),
                    {
                        "minio_object_name": object_name,
                        "original_filename": filename,
                        "mime_type": content_type,
                        "file_size_bytes": file_size,
                        "asset_status": "ready",
                        "asset_error": None,
                        "asset_imported_at": datetime.utcnow(),
                    },
                )
                ready_rows += 1
                logger.info("[%s/%s] READY %s", index, total_rows, object_name)
            except Exception as exc:
                failed_rows += 1
                logger.exception("[%s/%s] Failed to import %s: %s", index, total_rows, source_path, exc)
                await asset_service.update_asset_metadata(
                    int(row["standard_id"]),
                    {
                        "asset_status": "error",
                        "asset_error": str(exc)[:4000],
                    },
                )

        logger.info(
            "Import finished: total=%s matched=%s uploaded=%s ready=%s missing=%s failed=%s dry_run=%s",
            total_rows,
            matched_rows,
            uploaded_rows,
            ready_rows,
            missing_rows,
            failed_rows,
            args.dry_run,
        )
        return 0 if failed_rows == 0 else 1
    finally:
        await db_manager.close()


def main() -> int:
    args = parse_args()
    return asyncio.run(run_import(args))


if __name__ == "__main__":
    raise SystemExit(main())
