from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "evals" / "geoai_agent_36_tasks.json"


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list) or len(tasks) != 36:
        raise ValueError("GeoAI evaluation manifest must contain exactly 36 tasks")
    ids = [task.get("id") for task in tasks]
    if len(set(ids)) != 36 or any(not isinstance(task_id, str) or not task_id for task_id in ids):
        raise ValueError("GeoAI evaluation task ids must be 36 unique non-empty strings")
    required = {"id", "category", "prompt", "required_capabilities", "success_criteria"}
    if any(not required.issubset(task) for task in tasks):
        raise ValueError("GeoAI evaluation task is missing required fields")
    return tasks


def evaluate(results: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_by_id = {task["id"]: task for task in tasks}
    result_ids = [row.get("id") for row in results]
    if len(results) != len(tasks) or len(set(result_ids)) != len(results):
        raise ValueError("result set must contain exactly one record for every task")
    if set(result_ids) != set(task_by_id):
        raise ValueError("result ids must exactly match the evaluation manifest")
    if any(not isinstance(row.get("completed"), bool) for row in results):
        raise ValueError("every result requires boolean completed")

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate executed GeoAI Agent evaluation results.")
    parser.add_argument("results", type=Path, help="JSON array with one executed result per manifest task")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    summary = evaluate(json.loads(args.results.read_text(encoding="utf-8")), load_manifest(args.manifest))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
