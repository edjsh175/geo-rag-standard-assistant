"""Export the FastAPI OpenAPI schema for frontend type generation."""

from __future__ import annotations

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "Backend"
DEFAULT_OUTPUT = PROJECT_ROOT / "frontend" / "src" / "lib" / "api" / "generated" / "openapi.json"


def main() -> None:
    sys.path.insert(0, str(BACKEND_ROOT))

    import main as backend_main

    output_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(backend_main.app.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI schema exported to {output_path}")


if __name__ == "__main__":
    main()
