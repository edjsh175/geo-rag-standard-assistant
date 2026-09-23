from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from geoai_eval_contract import DEFAULT_MANIFEST, load_manifest


def evaluate(results: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_by_id = {task["id"]: task for task in tasks}
    result_ids = [row.get("id") for row in results]
    if len(results) != len(tasks) or len(set(result_ids)) != len(results):
        raise ValueError("result set must contain exactly one record for every task")
    if set(result_ids) != set(task_by_id):
        raise ValueError("result ids must exactly match the evaluation manifest")
    if any(not isinstance(row.get("completed"), bool) for row in results):
        raise ValueError("every result requires boolean completed")

    for row in results:
        task = task_by_id[row["id"]]
        evidence = row.get("assertions")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"task {row['id']} requires assertion evidence")
        required_types = [assertion["type"] for assertion in task["assertions"]]
        observed_required = [
            assertion
            for assertion in evidence
            if isinstance(assertion, dict) and assertion.get("required", True)
        ]
        observed_types = [assertion.get("type") for assertion in observed_required]
        if observed_types != required_types:
            raise ValueError(f"task {row['id']} assertion evidence does not match manifest")
        computed = all(assertion.get("passed") is True for assertion in observed_required)
        if row["completed"] is not computed:
            raise ValueError(f"task {row['id']} completed must equal required assertion outcome")

    per_category: dict[str, dict[str, int | float]] = defaultdict(lambda: {"completed": 0, "total": 0, "rate": 0.0})
    failures: list[dict[str, Any]] = []
    completed = 0
    for row in results:
        task = task_by_id[row["id"]]
        category = task["category"]
        per_category[category]["total"] += 1
        if row["completed"]:
            completed += 1
            per_category[category]["completed"] += 1
        else:
            failures.append({"id": row["id"], "failure_reason": row.get("failure_reason")})
    for stats in per_category.values():
        stats["rate"] = stats["completed"] / stats["total"]
    return {
        "completed": completed,
        "total": len(tasks),
        "rate": completed / len(tasks),
        "per_category": dict(per_category),
        "failures": failures,
    }


def completion_exit_code(summary: dict[str, Any]) -> int:
    return 0 if summary.get("rate") == 1.0 else 4


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate executed GeoAI Agent evaluation results.")
    parser.add_argument("results", type=Path, help="JSON array with one executed result per manifest task")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    summary = evaluate(json.loads(args.results.read_text(encoding="utf-8")), load_manifest(args.manifest))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(completion_exit_code(summary))


if __name__ == "__main__":
    main()
