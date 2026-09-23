from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "evals" / "geoai_agent_36_tasks.json"


def validate_manifest(tasks: list[dict[str, Any]]) -> None:
    if len(tasks) != 36:
        raise ValueError("GeoAI evaluation manifest must contain exactly 36 tasks")

    ids = [task.get("id") for task in tasks]
    if len(set(ids)) != 36 or any(not isinstance(task_id, str) or not task_id for task_id in ids):
        raise ValueError("GeoAI evaluation task ids must be 36 unique non-empty strings")

    required = {
        "id",
        "category",
        "scenario",
        "depends_on",
        "prompt",
        "required_capabilities",
        "success_criteria",
        "assertions",
    }
    known_ids = set(ids)
    for task in tasks:
        if not required.issubset(task):
            raise ValueError(f"GeoAI evaluation task {task.get('id')!r} is missing required fields")
        if not isinstance(task["scenario"], str) or not task["scenario"].strip():
            raise ValueError(f"task {task['id']} requires a non-empty scenario")
        if not isinstance(task["depends_on"], list):
            raise ValueError(f"task {task['id']} depends_on must be a list")
        if not isinstance(task["assertions"], list) or not task["assertions"]:
            raise ValueError(f"task {task['id']} requires at least one assertion")
        for assertion in task["assertions"]:
            if not isinstance(assertion, dict) or not isinstance(assertion.get("type"), str):
                raise ValueError(f"task {task['id']} contains an invalid assertion")
        for dependency in task["depends_on"]:
            if dependency not in known_ids:
                raise ValueError(f"task {task['id']} has unknown dependency {dependency}")

    graph = {task["id"]: list(task["depends_on"]) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError("evaluation manifest dependency cycle detected")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("GeoAI evaluation manifest must be a JSON array")
    validate_manifest(tasks)
    return tasks
