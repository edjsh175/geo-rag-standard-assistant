from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_geoai_agent_e2e.py"
SPEC = importlib.util.spec_from_file_location("geoai_e2e_runner", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_pipeline_stops_when_preflight_fails(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object):
        calls.append(command)
        return RUNNER.CommandResult(returncode=2)

    result = RUNNER.run_pipeline(root=ROOT, result_dir=tmp_path, run_command=fake_run)
    assert result == 2
    assert len(calls) == 1
    assert "preflight_geoai_agent_e2e.py" in " ".join(calls[0])


def test_pipeline_runs_playwright_then_evaluator(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object):
        calls.append(command)
        if "e2e:geoai" in command:
            (tmp_path / "results.json").write_text("[]", encoding="utf-8")
        return RUNNER.CommandResult(returncode=0)

    result = RUNNER.run_pipeline(root=ROOT, result_dir=tmp_path, run_command=fake_run)
    assert result == 0
    assert len(calls) == 3
    assert "preflight_geoai_agent_e2e.py" in " ".join(calls[0])
    assert "e2e:geoai" in calls[1]
    assert "evaluate_geoai_agent_results.py" in " ".join(calls[2])


def test_pipeline_fails_if_playwright_does_not_produce_results(tmp_path: Path) -> None:
    def fake_run(command: list[str], **_: object):
        return RUNNER.CommandResult(returncode=0)

    result = RUNNER.run_pipeline(root=ROOT, result_dir=tmp_path, run_command=fake_run)
    assert result == 3
