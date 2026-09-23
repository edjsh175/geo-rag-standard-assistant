from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT_DIR = ROOT / "evals" / "results" / "latest"


class CommandResult:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


RunCommand = Callable[..., object]


def _returncode(result: object) -> int:
    value = getattr(result, "returncode", None)
    if not isinstance(value, int):
        raise TypeError("run_command must return an object with integer returncode")
    return value


def _subprocess_run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env else None,
        text=True,
        check=False,
    )


def run_pipeline(
    *,
    root: Path = ROOT,
    result_dir: Path = DEFAULT_RESULT_DIR,
    run_command: RunCommand = _subprocess_run,
) -> int:
    python = sys.executable
    preflight = [python, str(root / "scripts" / "preflight_geoai_agent_e2e.py")]
    preflight_result = run_command(preflight, cwd=root)
    if _returncode(preflight_result) != 0:
        return _returncode(preflight_result)

    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    env = os.environ.copy()
    env["GEOAI_E2E_RESULT_DIR"] = str(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    playwright = [npm, "run", "e2e:geoai"]
    playwright_result = run_command(playwright, cwd=root / "frontend", env=env)
    if _returncode(playwright_result) != 0:
        return _returncode(playwright_result)

    results_file = result_dir / "results.json"
    if not results_file.exists():
        print(f"GeoAI E2E did not produce expected result file: {results_file}", file=sys.stderr)
        return 3

    evaluator = [
        python,
        str(root / "scripts" / "evaluate_geoai_agent_results.py"),
        str(results_file),
    ]
    evaluator_result = run_command(evaluator, cwd=root)
    return _returncode(evaluator_result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real browser-backed GeoAI 36-task E2E pipeline.")
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    args = parser.parse_args()
    raise SystemExit(run_pipeline(result_dir=args.result_dir.resolve()))


if __name__ == "__main__":
    main()
