"""Dry-run or apply deterministic standard applicability bootstrap facts."""

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
from app.services.standard_applicability import StandardApplicabilityService


async def _run(*, apply: bool) -> None:
    await db_manager._init_postgres()
    try:
        service = StandardApplicabilityService()
        report = await service.build_bootstrap_report()
        summary = {key: value for key, value in report.items() if key != "facts"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if apply:
            count = await service.apply_bootstrap(report["facts"])
            print(json.dumps({"applied": count}, ensure_ascii=False))
    finally:
        await db_manager.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist deterministic bootstrap facts. Without this flag the command is read-only.",
    )
    args = parser.parse_args()
    asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    main()
