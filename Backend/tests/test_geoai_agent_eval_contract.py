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

CONTRACT_SCRIPT = ROOT / "scripts" / "geoai_eval_contract.py"
CONTRACT_SPEC = importlib.util.spec_from_file_location("geoai_eval_contract", CONTRACT_SCRIPT)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
CONTRACT = importlib.util.module_from_spec(CONTRACT_SPEC)
CONTRACT_SPEC.loader.exec_module(CONTRACT)


def test_manifest_has_exactly_36_unique_tasks() -> None:
    tasks = CONTRACT.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    assert len(tasks) == 36
    assert len({task["id"] for task in tasks}) == 36
    assert all(task["scenario"] for task in tasks)
    assert all(task["assertions"] for task in tasks)


def test_manifest_rejects_unknown_dependency() -> None:
    tasks = CONTRACT.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    broken = [dict(task) for task in tasks]
    broken[0]["depends_on"] = ["UNKNOWN"]
    with pytest.raises(ValueError, match="unknown dependency"):
        CONTRACT.validate_manifest(broken)


def test_manifest_rejects_dependency_cycle() -> None:
    tasks = CONTRACT.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    broken = [dict(task) for task in tasks]
    broken[0]["depends_on"] = [broken[1]["id"]]
    broken[1]["depends_on"] = [broken[0]["id"]]
    with pytest.raises(ValueError, match="cycle"):
        CONTRACT.validate_manifest(broken)


def test_evaluator_requires_complete_result_set_and_measures_rate() -> None:
    tasks = MODULE.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    results = []
    for index, task in enumerate(tasks):
        passed = index < 33
        results.append({
            "id": task["id"],
            "completed": passed,
            "assertions": [
                {"type": assertion["type"], "required": True, "passed": passed}
                for assertion in task["assertions"]
            ],
        })
    summary = MODULE.evaluate(results, tasks)
    assert summary["completed"] == 33
    assert summary["total"] == 36
    assert summary["rate"] == pytest.approx(33 / 36)

    with pytest.raises(ValueError, match="exactly one"):
        MODULE.evaluate(results[:-1], tasks)


def test_evaluator_rejects_bare_completed_true_without_assertion_evidence() -> None:
    tasks = MODULE.load_manifest(ROOT / "evals" / "geoai_agent_36_tasks.json")
    results = [{"id": task["id"], "completed": True} for task in tasks]
    with pytest.raises(ValueError, match="assertion evidence"):
        MODULE.evaluate(results, tasks)


def test_completion_exit_code_requires_full_completion() -> None:
    assert MODULE.completion_exit_code({"rate": 1.0}) == 0
    assert MODULE.completion_exit_code({"rate": 35 / 36}) != 0


def test_geojson_fixtures_exist_and_use_feature_collections() -> None:
    import json

    for name in ("sample_polygons.geojson", "sample_points.geojson"):
        payload = json.loads((ROOT / "evals" / "fixtures" / name).read_text(encoding="utf-8"))
        assert payload["type"] == "FeatureCollection"
        assert payload["features"]

    shapefile_dir = ROOT / "evals" / "fixtures" / "sample_shapefile"
    assert {path.suffix for path in shapefile_dir.iterdir()} >= {".shp", ".dbf", ".shx", ".prj"}
