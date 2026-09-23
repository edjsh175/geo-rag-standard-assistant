from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_geoai_agent_results.py"
SPEC = importlib.util.spec_from_file_location("geoai_eval", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_manifest_has_exactly_36_unique_tasks() -> None:
    tasks = MODULE.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    assert len(tasks) == 36
    assert len({task["id"] for task in tasks}) == 36


def test_evaluator_requires_complete_result_set_and_measures_rate() -> None:
    tasks = MODULE.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    results = [{"id": task["id"], "completed": index < 33} for index, task in enumerate(tasks)]
    summary = MODULE.evaluate(results, tasks)
    assert summary["completed"] == 33
    assert summary["total"] == 36
    assert summary["rate"] == pytest.approx(33 / 36)

    with pytest.raises(ValueError, match="exactly one"):
        MODULE.evaluate(results[:-1], tasks)
